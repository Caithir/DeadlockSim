"""Build and simulation state management.

Encapsulates the mutable state that is shared across GUI tabs
(build items, hero/boon selection, sim settings) behind a validated
API.  This module has **no NiceGUI dependency** — it depends only on
domain models and the build engine, making it fully testable without
a browser.
"""

from __future__ import annotations

from ..models import Build, BuildStats, CombatConfig, HeroStats, Item
from ..engine.builds import BuildEngine
from ..engine.simulation import SimSettings
from ..data import souls_to_boons, souls_to_ability_points, ABILITY_TIER_COSTS

_MAX_ITEMS = 12
_MAX_BOONS = 50


class BuildState:
    """Fluent API for build configuration with validation."""

    def __init__(self) -> None:
        self._hero_name: str = ""
        self._extra_souls: int = 0
        self._items: list[Item] = []
        self._disabled_abilities: dict[str, set[int]] = {}
        self._ability_priority: dict[str, list[int]] = {}
        # Per-hero ability upgrade tiers: {hero_name: {ability_idx: max_tier_purchased}}
        # e.g. {\"Haze\": {0: 2, 1: 1}} means ability 0 has T1+T2, ability 1 has T1
        self._ability_upgrades: dict[str, dict[int, int]] = {}
        # Cached build stats — invalidated on any item change.
        self._cached_stats: BuildStats | None = None

    # ── Read-only properties ──────────────────────────────────────

    @property
    def hero_name(self) -> str:
        return self._hero_name

    @property
    def total_souls(self) -> int:
        """Total souls = item cost + extra (unspent) souls."""
        return sum(i.cost for i in self._items) + self._extra_souls

    @property
    def boons(self) -> int:
        """Auto-derived boon count from total souls gathered."""
        return souls_to_boons(self.total_souls)

    @property
    def ability_points_available(self) -> int:
        """Total ability points earned at the current soul level."""
        return souls_to_ability_points(self.total_souls)

    @property
    def ability_points_spent(self) -> int:
        """Total ability points allocated to upgrades for the current hero."""
        upgrades = self._ability_upgrades.get(self._hero_name, {})
        spent = 0
        for _idx, max_tier in upgrades.items():
            for t in range(max_tier):
                if t < len(ABILITY_TIER_COSTS):
                    spent += ABILITY_TIER_COSTS[t]
        return spent

    @property
    def ability_points_remaining(self) -> int:
        return max(0, self.ability_points_available - self.ability_points_spent)

    @property
    def extra_souls(self) -> int:
        return self._extra_souls

    @property
    def items(self) -> list[Item]:
        """Return a *copy* so external code can't bypass validation."""
        return list(self._items)

    # ── Fluent setters ────────────────────────────────────────────

    def set_hero(self, name: str) -> "BuildState":
        if name != self._hero_name:
            old = self._hero_name
            self._hero_name = name
            # Clear ability config for the *old* hero.
            self._disabled_abilities.pop(old, None)
            self._ability_priority.pop(old, None)
        return self

    def set_extra_souls(self, souls: int) -> "BuildState":
        self._extra_souls = max(0, souls)
        return self

    def add_item(self, item: Item) -> "BuildState":
        if len(self._items) >= _MAX_ITEMS:
            return self
        if any(i.name == item.name for i in self._items):
            return self
        self._items.append(item)
        self._invalidate()
        return self

    def remove_item(self, index: int) -> "BuildState":
        if 0 <= index < len(self._items):
            self._items.pop(index)
            self._invalidate()
        return self

    def clear_items(self) -> "BuildState":
        self._items.clear()
        self._invalidate()
        return self

    # ── Ability config ────────────────────────────────────────────

    def disable_ability(self, hero_name: str, idx: int) -> "BuildState":
        self._disabled_abilities.setdefault(hero_name, set()).add(idx)
        return self

    def enable_ability(self, hero_name: str, idx: int) -> "BuildState":
        s = self._disabled_abilities.get(hero_name)
        if s:
            s.discard(idx)
        return self

    def is_ability_disabled(self, hero_name: str, idx: int) -> bool:
        return idx in self._disabled_abilities.get(hero_name, set())

    def set_ability_priority(self, hero_name: str, indices: list[int]) -> "BuildState":
        self._ability_priority[hero_name] = list(indices)
        return self

    def get_disabled_abilities(self) -> dict[str, set[int]]:
        return self._disabled_abilities

    def get_ability_priority(self) -> dict[str, list[int]]:
        return self._ability_priority

    # ── Ability upgrades ──────────────────────────────────────────

    def set_ability_upgrade(self, hero_name: str, ability_idx: int, tier: int) -> "BuildState":
        """Set ability *ability_idx* to have upgrades up to *tier* (1-3).

        Tier 0 means no upgrades purchased.
        """
        self._ability_upgrades.setdefault(hero_name, {})
        if tier <= 0:
            self._ability_upgrades[hero_name].pop(ability_idx, None)
        else:
            self._ability_upgrades[hero_name][ability_idx] = min(tier, 3)
        return self

    def get_ability_upgrade_tier(self, hero_name: str, ability_idx: int) -> int:
        """Return the max purchased tier for an ability (0 = none)."""
        return self._ability_upgrades.get(hero_name, {}).get(ability_idx, 0)

    def get_ability_upgrades_map(self, hero_name: str | None = None) -> dict[int, list[int]]:
        """Return ``{ability_idx: [1, 2, ...]}`` for the engine.

        Each value is a list of purchased tier numbers.
        """
        name = hero_name or self._hero_name
        upgrades = self._ability_upgrades.get(name, {})
        return {idx: list(range(1, max_tier + 1)) for idx, max_tier in upgrades.items()}

    # ── Config construction ───────────────────────────────────────

    def get_build_stats(self) -> BuildStats:
        """Aggregate stats for the current item set (cached)."""
        if self._cached_stats is None:
            self._cached_stats = BuildEngine.aggregate_stats(self.to_build())
        return self._cached_stats

    def get_combat_config(self, **overrides: object) -> CombatConfig:
        """Build a :class:`CombatConfig` from current state.

        Any keyword argument is forwarded as an override to the
        ``CombatConfig`` constructor.
        """
        stats = self.get_build_stats()
        cfg = BuildEngine.build_to_attacker_config(stats, boons=self.boons)
        for k, v in overrides.items():
            if hasattr(cfg, k):
                object.__setattr__(cfg, k, v)
        return cfg

    def to_build(self) -> Build:
        return Build(items=list(self._items))

    def to_dict(self) -> dict:
        return {
            "hero_name": self._hero_name,
            "boons": self.boons,
            "extra_souls": self._extra_souls,
            "items": [i.name for i in self._items],
            "ability_upgrades": {
                h: dict(m) for h, m in self._ability_upgrades.items()
            },
        }

    # ── Internals ─────────────────────────────────────────────────

    def _invalidate(self) -> None:
        self._cached_stats = None


class SimSettingsState:
    """Simulation knobs with validated setters."""

    def __init__(self) -> None:
        # Combat
        self.duration: float = 15.0
        self.accuracy: float = 0.65
        self.headshot_rate: float = 0.10
        self.headshot_multiplier: float = 1.50
        self.weapon_uptime: float = 1.0
        self.ability_uptime: float = 1.0
        self.active_item_uptime: float = 1.0
        # Melee
        self.weave_melee: bool = False
        self.melee_after_reload: bool = True
        # Bidirectional
        self.bidirectional: bool = False
        # Custom item values
        self.custom_item_dps: dict[str, float] = {}
        self.custom_item_ehp: dict[str, float] = {}
        # Ability config (per-hero)
        self.disabled_abilities: dict[str, set[int]] = {}
        self.ability_priority: dict[str, list[int]] = {}

    def to_sim_settings(
        self, atk_boons: int = 0, def_boons: int = 0
    ) -> SimSettings:
        """Convert to the engine's :class:`SimSettings` dataclass."""
        return SimSettings(
            duration=self.duration,
            accuracy=self.accuracy,
            headshot_rate=self.headshot_rate,
            headshot_multiplier=self.headshot_multiplier,
            weapon_uptime=self.weapon_uptime,
            ability_uptime=self.ability_uptime,
            active_item_uptime=self.active_item_uptime,
            weave_melee=self.weave_melee,
            melee_after_reload=self.melee_after_reload,
            attacker_boons=atk_boons,
            defender_boons=def_boons,
            bidirectional=self.bidirectional,
        )

    def to_dict(self) -> dict:
        """Snapshot all settings as a plain dict (mirrors the old global)."""
        return {
            "duration": self.duration,
            "accuracy": self.accuracy,
            "headshot_rate": self.headshot_rate,
            "headshot_multiplier": self.headshot_multiplier,
            "weapon_uptime": self.weapon_uptime,
            "ability_uptime": self.ability_uptime,
            "active_item_uptime": self.active_item_uptime,
            "weave_melee": self.weave_melee,
            "melee_after_reload": self.melee_after_reload,
            "bidirectional": self.bidirectional,
            "disabled_abilities": {
                k: list(v) for k, v in self.disabled_abilities.items()
            },
            "ability_priority": dict(self.ability_priority),
            "custom_item_dps": dict(self.custom_item_dps),
            "custom_item_ehp": dict(self.custom_item_ehp),
        }


# ── Module-level singletons ──────────────────────────────────────

_build_state = BuildState()
_sim_settings_state = SimSettingsState()


def build() -> BuildState:
    """Return the singleton :class:`BuildState`."""
    return _build_state


def sim_settings() -> SimSettingsState:
    """Return the singleton :class:`SimSettingsState`."""
    return _sim_settings_state
