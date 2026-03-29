"""Event-driven combat timeline simulation engine.

Simulates a full combat encounter tick-by-tick using a priority queue.
Models weapon firing, item procs, DoTs, buildup mechanics, ability usage,
melee weaving, and cross-item interactions (EE stacks, Mystic Vuln, etc.).

All calculations are pure — no UI, no I/O, no side effects.
Leverages DamageCalculator for base damage math.
"""

from __future__ import annotations

import enum
import heapq
import math
from dataclasses import dataclass, field

from ..models import Build, BuildStats, HeroAbility, HeroStats, Item
from .builds import BuildEngine
from .damage import DamageCalculator


# ── Enums ─────────────────────────────────────────────────────────


class EventType(enum.Enum):
    """Types of events in the simulation timeline."""

    BULLET_FIRE = "bullet_fire"
    RELOAD_START = "reload_start"
    RELOAD_END = "reload_end"
    PROC_TRIGGER = "proc_trigger"
    DOT_TICK = "dot_tick"
    DOT_EXPIRE = "dot_expire"
    BUILDUP_DECAY = "buildup_decay"
    STACK_APPLY = "stack_apply"
    STACK_EXPIRE = "stack_expire"
    DEBUFF_APPLY = "debuff_apply"
    DEBUFF_EXPIRE = "debuff_expire"
    ACTIVE_USE = "active_use"
    ABILITY_USE = "ability_use"
    MELEE_HIT = "melee_hit"
    PULSE_TRIGGER = "pulse_trigger"
    REGEN_TICK = "regen_tick"
    SIM_END = "sim_end"


class DamageType(enum.Enum):
    """Damage type for resist calculations."""

    BULLET = "bullet"
    SPIRIT = "spirit"
    MELEE = "melee"


class ItemBehaviorType(enum.Enum):
    """How an item participates in the simulation."""

    PASSIVE_STAT = "passive_stat"
    PROC_ON_HIT = "proc_on_hit"
    BUILDUP = "buildup"
    DOT_ACTIVE = "dot_active"
    PULSE_PASSIVE = "pulse_passive"
    STACK_AMPLIFIER = "stack_amplifier"
    RESIST_SHRED = "resist_shred"


# ── Configuration ─────────────────────────────────────────────────


@dataclass
class ActiveUse:
    """Schedule entry for an active item activation."""

    item_name: str
    first_use: float = 0.0
    use_on_cooldown: bool = True


@dataclass
class AbilityUse:
    """Schedule entry for a hero ability activation."""

    ability_index: int  # 0-3 mapping to hero.abilities
    first_use: float = 0.0
    use_on_cooldown: bool = True


@dataclass
class SimSettings:
    """User-configurable simulation settings (maps to a settings UI).

    These are the knobs a user would tweak on a settings page
    to configure how the simulation runs.
    """

    # Timing
    duration: float = 15.0  # simulation length in seconds

    # Accuracy model
    accuracy: float = 0.65  # fraction of shots that land
    headshot_rate: float = 0.10  # fraction of hits that are headshots
    headshot_multiplier: float = 1.5

    # Uptime / engagement
    weapon_uptime: float = 1.0  # fraction of time actively shooting (1.0 = always)
    ability_uptime: float = 1.0  # multiplier on ability usage frequency
    active_item_uptime: float = 1.0  # multiplier on active item usage

    # Melee
    weave_melee: bool = False  # weave light melee between reloads
    melee_after_reload: bool = True  # heavy melee during reload window

    # Boons
    attacker_boons: int = 0
    defender_boons: int = 0


@dataclass
class SimConfig:
    """Full input configuration for a combat simulation."""

    # Combatants
    attacker: HeroStats = field(default_factory=lambda: HeroStats(name="Unknown"))
    attacker_build: Build = field(default_factory=Build)
    defender: HeroStats = field(default_factory=lambda: HeroStats(name="Dummy"))
    defender_build: Build = field(default_factory=Build)

    # Settings (user-configurable knobs)
    settings: SimSettings = field(default_factory=SimSettings)

    # Schedules for active items and abilities (auto-populated if empty)
    active_schedule: list[ActiveUse] = field(default_factory=list)
    ability_schedule: list[AbilityUse] = field(default_factory=list)


# ── Item behavior classification ──────────────────────────────────


@dataclass
class ItemBehavior:
    """Describes how a specific item participates in the simulation.

    Built from Item.raw_properties by classify_item().
    """

    item: Item
    behavior_type: ItemBehaviorType
    damage_type: DamageType = DamageType.SPIRIT

    # Proc items (Tesla Bullets, Mystic Shot)
    proc_chance: float = 100.0  # percentage
    proc_cooldown: float = 0.0  # seconds between procs
    proc_damage: float = 0.0  # base damage per proc
    spirit_scale: float = 0.0  # spirit scaling coefficient
    boon_scale: float = 0.0  # boon scaling coefficient

    # Buildup items (Toxic Bullets)
    buildup_per_shot: float = 0.0
    buildup_decay_time: float = 0.0

    # DoT parameters
    dot_tick_rate: float = 0.5  # seconds between ticks
    dot_duration: float = 0.0
    dot_dps: float = 0.0  # base DPS or damage per tick
    dot_spirit_scale: float = 0.0
    dot_is_percent_hp: bool = False

    # Stack/debuff parameters (EE, Mystic Vuln)
    stack_value: float = 0.0  # per-stack bonus percentage
    max_stacks: int = 0
    debuff_duration: float = 0.0
    debuff_value: float = 0.0  # e.g., -8% spirit resist

    # Pulse items (Torment Pulse)
    pulse_damage: float = 0.0
    pulse_cooldown: float = 0.0
    pulse_spirit_scale: float = 0.0

    # Active item cooldown
    active_cooldown: float = 0.0


def _prop_float(props: dict, key: str, default: float = 0.0) -> float:
    """Extract a float value from a property dict."""
    prop = props.get(key)
    if not isinstance(prop, dict):
        return default
    try:
        return float(prop.get("value", default))
    except (ValueError, TypeError):
        return default


def _prop_scale(props: dict, key: str) -> tuple[str, float]:
    """Extract scale_function type and coefficient from a property."""
    prop = props.get(key)
    if not isinstance(prop, dict):
        return ("", 0.0)
    sf = prop.get("scale_function")
    if not isinstance(sf, dict):
        return ("", 0.0)
    scale_type = sf.get("specific_stat_scale_type", "")
    try:
        stat_scale = float(sf.get("stat_scale", 0.0))
    except (ValueError, TypeError):
        stat_scale = 0.0
    return (scale_type, stat_scale)


def classify_item(item: Item) -> ItemBehavior | None:
    """Classify an item into its simulation behavior type.

    Inspects raw_properties to determine how the item should be modeled
    in the combat simulation. Returns None for passive-stat-only items.
    """
    props = item.raw_properties
    if not props:
        return None

    # 1. Stack amplifiers (Escalating Exposure)
    if "MagicIncreasePerStack" in props and "MaxStacks" in props:
        return ItemBehavior(
            item=item,
            behavior_type=ItemBehaviorType.STACK_AMPLIFIER,
            damage_type=DamageType.SPIRIT,
            stack_value=_prop_float(props, "MagicIncreasePerStack"),
            max_stacks=int(_prop_float(props, "MaxStacks")),
            debuff_duration=_prop_float(props, "AbilityDuration", 12.0),
            proc_cooldown=_prop_float(props, "ProcCooldown", 0.7),
            debuff_value=_prop_float(props, "TechArmorDamageReduction"),
        )

    # 2. Buildup items (Toxic Bullets)
    if "BuildUpPerShot" in props:
        dot_dps = _prop_float(props, "DotHealthPercent")
        dot_scale_type, dot_scale = _prop_scale(props, "DotHealthPercent")
        return ItemBehavior(
            item=item,
            behavior_type=ItemBehaviorType.BUILDUP,
            damage_type=DamageType.SPIRIT,
            buildup_per_shot=_prop_float(props, "BuildUpPerShot"),
            buildup_decay_time=_prop_float(props, "BuildUpDuration", 5.0),
            dot_dps=dot_dps,
            dot_spirit_scale=dot_scale if dot_scale_type == "ETechPower" else 0.0,
            dot_duration=_prop_float(props, "DotDuration", 4.0),
            dot_tick_rate=_prop_float(props, "TickRate", 0.5),
            dot_is_percent_hp=dot_dps > 0 and dot_dps < 20,  # heuristic: small = %HP
        )

    # 3. Resist shred debuffs (Mystic Vulnerability) — has TechArmorDamageReduction
    #    but NOT MagicIncreasePerStack (which would be EE)
    if "TechArmorDamageReduction" in props and "MagicIncreasePerStack" not in props:
        dur = _prop_float(props, "AbilityDuration", 7.0)
        if dur > 0:
            return ItemBehavior(
                item=item,
                behavior_type=ItemBehaviorType.RESIST_SHRED,
                damage_type=DamageType.SPIRIT,
                debuff_duration=dur,
                debuff_value=_prop_float(props, "TechArmorDamageReduction"),
            )

    # 4. Pulse items (Torment Pulse — auto-fires on cooldown)
    if "DamagePulseAmount" in props:
        scale_type, scale_val = _prop_scale(props, "DamagePulseAmount")
        return ItemBehavior(
            item=item,
            behavior_type=ItemBehaviorType.PULSE_PASSIVE,
            damage_type=DamageType.SPIRIT,
            pulse_damage=_prop_float(props, "DamagePulseAmount"),
            pulse_cooldown=_prop_float(props, "AbilityCooldown", 1.4),
            pulse_spirit_scale=scale_val if scale_type == "ETechPower" else 0.0,
        )

    # 5. Active DoT items (Decay, Alchemical Fire)
    if item.is_active and ("DotHealthPercent" in props or "DPS" in props):
        dps_key = "DPS" if "DPS" in props else "DotHealthPercent"
        scale_type, scale_val = _prop_scale(props, dps_key)
        return ItemBehavior(
            item=item,
            behavior_type=ItemBehaviorType.DOT_ACTIVE,
            damage_type=DamageType.SPIRIT,
            dot_dps=_prop_float(props, dps_key),
            dot_spirit_scale=scale_val if scale_type == "ETechPower" else 0.0,
            dot_duration=_prop_float(props, "AbilityDuration", 10.0),
            dot_tick_rate=_prop_float(props, "TickRate", 1.0),
            active_cooldown=_prop_float(props, "AbilityCooldown", 30.0),
        )

    # 6. Proc-on-hit items (Tesla Bullets, Mystic Shot, Siphon Bullets)
    if "ProcCooldown" in props:
        damage_info = DamageCalculator._extract_item_damage(props)
        if damage_info:
            base_dmg, scale_type, stat_scale, is_dps, _, proc_chance = damage_info
            return ItemBehavior(
                item=item,
                behavior_type=ItemBehaviorType.PROC_ON_HIT,
                damage_type=DamageType.SPIRIT if scale_type == "ETechPower" else DamageType.BULLET,
                proc_chance=proc_chance,
                proc_cooldown=_prop_float(props, "ProcCooldown"),
                proc_damage=base_dmg,
                spirit_scale=stat_scale if scale_type == "ETechPower" else 0.0,
                boon_scale=stat_scale if scale_type == "ELevelUpBoons" else 0.0,
            )

    # No simulation behavior — passive stat item
    return None


def classify_build(build: Build) -> list[ItemBehavior]:
    """Classify all items in a build, returning only those with sim behaviors."""
    behaviors = []
    for item in build.items:
        b = classify_item(item)
        if b is not None:
            behaviors.append(b)
    return behaviors


# ── Simulation event ──────────────────────────────────────────────


@dataclass(order=True)
class SimEvent:
    """A single event in the simulation priority queue.

    Sorted by (time, priority) so ties resolve deterministically.
    Lower priority number fires first at the same timestamp.
    """

    time: float
    priority: int = 0
    event_type: EventType = field(compare=False, default=EventType.BULLET_FIRE)
    source: str = field(compare=False, default="")
    metadata: dict = field(compare=False, default_factory=dict)


# ── Mutable combat state ─────────────────────────────────────────


@dataclass
class TargetState:
    """Mutable state of the defender during the simulation.

    Tracks HP, shields, regen, and active debuffs applied by the attacker.
    Initialized from defender HeroStats + defender Build.
    """

    # Health
    hp: float = 0.0
    max_hp: float = 0.0
    bullet_shield: float = 0.0
    spirit_shield: float = 0.0
    hp_regen: float = 0.0

    # Base resists (from hero + items)
    base_bullet_resist: float = 0.0
    base_spirit_resist: float = 0.0

    # Active resist shred debuffs: source_name -> (shred_amount, expire_time)
    resist_shreds: dict[str, tuple[float, float]] = field(default_factory=dict)

    # Amplification stacks on target: source_name -> (stacks, per_stack_pct, expire_time)
    amp_stacks: dict[str, tuple[int, float, float]] = field(default_factory=dict)

    def effective_bullet_resist(self, time: float) -> float:
        """Current bullet resist — no dynamic shred system yet for bullet."""
        return max(0.0, min(1.0, self.base_bullet_resist))

    def effective_spirit_resist(self, time: float) -> float:
        """Current spirit resist after active debuffs (Mystic Vuln, EE shred)."""
        shred_total = 0.0
        for source, (amount, expire) in self.resist_shreds.items():
            if expire > time:
                shred_total += amount
        shred_total = min(1.0, shred_total)
        return max(0.0, self.base_spirit_resist * (1.0 - shred_total))

    def effective_spirit_amp(self, time: float) -> float:
        """Spirit damage amp from stacks on target (e.g. Escalating Exposure)."""
        total_pct = 0.0
        for source, (stacks, per_stack, expire) in self.amp_stacks.items():
            if expire > time:
                total_pct += stacks * per_stack
        return total_pct / 100.0  # convert percentage to multiplier


@dataclass
class AttackerState:
    """Mutable state of the attacker during the simulation.

    Tracks ammo, cooldowns, buildup meters, and derived combat stats.
    Initialized from attacker HeroStats + attacker Build + boons.
    """

    # Weapon
    ammo_remaining: int = 0
    weapon_damage: float = 0.0  # per-bullet after boon + item bonuses
    pellets: int = 1
    fire_rate: float = 0.0  # bullets per second
    magazine_size: int = 0
    reload_time: float = 0.0

    # Melee
    light_melee_damage: float = 0.0
    heavy_melee_damage: float = 0.0

    # Spirit
    spirit_power: float = 0.0
    spirit_amp: float = 0.0
    weapon_damage_bonus: float = 0.0

    # Cooldown reduction
    cooldown_reduction: float = 0.0

    # Buildup trackers: item_name -> (current_buildup, last_shot_time)
    buildup_trackers: dict[str, tuple[float, float]] = field(default_factory=dict)

    # Proc cooldown trackers: item_name -> next_available_time
    proc_cooldowns: dict[str, float] = field(default_factory=dict)

    # Active item cooldowns: item_name -> next_available_time
    active_cooldowns: dict[str, float] = field(default_factory=dict)

    # Ability cooldowns: ability_index -> next_available_time
    ability_cooldowns: dict[int, float] = field(default_factory=dict)


# ── Simulation output ─────────────────────────────────────────────


@dataclass
class DamageEntry:
    """A single damage instance logged in the timeline."""

    time: float
    source: str  # "weapon", item name, ability name, "light_melee", "heavy_melee"
    damage: float  # after resist/amp
    damage_type: str  # "bullet", "spirit", "melee"
    is_headshot: bool = False


@dataclass
class SimResult:
    """Full output of a combat simulation."""

    # Timeline
    timeline: list[DamageEntry] = field(default_factory=list)

    # Totals
    total_damage: float = 0.0
    total_duration: float = 0.0
    overall_dps: float = 0.0

    # Per-source breakdown
    damage_by_source: dict[str, float] = field(default_factory=dict)
    dps_by_source: dict[str, float] = field(default_factory=dict)

    # Per damage-type totals
    bullet_damage: float = 0.0
    spirit_damage: float = 0.0
    melee_damage: float = 0.0

    # Counters
    bullets_fired: int = 0
    headshots: int = 0
    reloads: int = 0
    procs_triggered: dict[str, int] = field(default_factory=dict)

    # Kill info
    kill_time: float | None = None  # None if target survived
    target_hp_remaining: float = 0.0


# ── Combat simulator ──────────────────────────────────────────────


class CombatSimulator:
    """Event-driven combat timeline simulation engine.

    Processes a priority queue of SimEvents to model a full combat
    encounter with weapon firing, item procs, DoTs, cross-interactions,
    abilities, and melee.
    """

    def __init__(self, config: SimConfig) -> None:
        self.config = config
        self.settings = config.settings
        self.queue: list[SimEvent] = []
        self.timeline: list[DamageEntry] = []
        self.attacker = AttackerState()
        self.target = TargetState()
        self.behaviors: list[ItemBehavior] = []
        self._dead = False
        self._bullets_fired = 0
        self._headshots = 0
        self._reloads = 0
        self._procs: dict[str, int] = {}

        # Behavior sub-lists for fast lookup
        self._proc_items: list[ItemBehavior] = []
        self._buildup_items: list[ItemBehavior] = []
        self._spirit_trigger_items: list[ItemBehavior] = []  # EE, Mystic Vuln
        self._pulse_items: list[ItemBehavior] = []

    # ── Public API ────────────────────────────────────────────

    @classmethod
    def run(cls, config: SimConfig) -> SimResult:
        """Run a full combat simulation and return results."""
        sim = cls(config)
        sim._initialize()
        sim._execute()
        return sim._build_result()

    # ── Initialization ────────────────────────────────────────

    def _initialize(self) -> None:
        """Set up attacker/target state, classify items, seed events."""
        s = self.settings
        hero = self.config.attacker

        # Aggregate attacker build stats
        atk_stats = BuildEngine.aggregate_stats(self.config.attacker_build)

        # Attacker weapon stats
        boon_dmg = DamageCalculator.bullet_damage_at_boon(hero, s.attacker_boons)
        weapon_bonus = atk_stats.weapon_damage_pct
        dmg_per_bullet = boon_dmg * hero.pellets * (1.0 + weapon_bonus)
        fire_rate = DamageCalculator.fire_rate_with_bonus(hero, atk_stats.fire_rate_pct)
        mag_size = DamageCalculator.effective_magazine(
            hero, atk_stats.ammo_pct, atk_stats.ammo_flat
        )

        # Spirit power from boons + items
        spirit_from_boons = hero.spirit_gain * s.attacker_boons
        spirit_power = spirit_from_boons + atk_stats.spirit_power

        # Melee damage (scales with weapon bonus + boons)
        melee_boon = hero.damage_gain * s.attacker_boons
        light_melee = (hero.light_melee_damage + melee_boon) * (1.0 + weapon_bonus)
        heavy_melee = (hero.heavy_melee_damage + melee_boon) * (1.0 + weapon_bonus)

        self.attacker = AttackerState(
            ammo_remaining=mag_size,
            weapon_damage=dmg_per_bullet,
            pellets=hero.pellets,
            fire_rate=fire_rate,
            magazine_size=mag_size,
            reload_time=hero.reload_duration if hero.reload_duration > 0 else 1.0,
            light_melee_damage=light_melee,
            heavy_melee_damage=heavy_melee,
            spirit_power=spirit_power,
            spirit_amp=atk_stats.spirit_amp_pct,
            weapon_damage_bonus=weapon_bonus,
            cooldown_reduction=atk_stats.cooldown_reduction,
        )

        # Defender state from hero + build
        def_hero = self.config.defender
        def_stats = BuildEngine.aggregate_stats(self.config.defender_build)
        def_base_hp = def_hero.base_hp + (def_hero.hp_gain * s.defender_boons)
        def_hp = def_base_hp + def_stats.bonus_hp

        self.target = TargetState(
            hp=def_hp,
            max_hp=def_hp,
            bullet_shield=def_stats.bullet_shield,
            spirit_shield=def_stats.spirit_shield,
            hp_regen=def_hero.base_regen + def_stats.hp_regen,
            base_bullet_resist=def_stats.bullet_resist_pct,
            base_spirit_resist=def_stats.spirit_resist_pct,
        )

        # Classify attacker items into behaviors
        self.behaviors = classify_build(self.config.attacker_build)
        for b in self.behaviors:
            if b.behavior_type == ItemBehaviorType.PROC_ON_HIT:
                self._proc_items.append(b)
            elif b.behavior_type == ItemBehaviorType.BUILDUP:
                self._buildup_items.append(b)
            elif b.behavior_type in (
                ItemBehaviorType.STACK_AMPLIFIER,
                ItemBehaviorType.RESIST_SHRED,
            ):
                self._spirit_trigger_items.append(b)
            elif b.behavior_type == ItemBehaviorType.PULSE_PASSIVE:
                self._pulse_items.append(b)

        # Seed events
        self._push(0.0, 0, EventType.BULLET_FIRE, "weapon")

        # Pulse items start firing at t=0
        for b in self._pulse_items:
            self._push(0.0, 5, EventType.PULSE_TRIGGER, b.item.name)

        # Active items
        self._seed_active_items()

        # Abilities
        self._seed_abilities()

        # Regen ticks every 1s
        if self.target.hp_regen > 0:
            self._push(1.0, 20, EventType.REGEN_TICK, "regen")

        # End marker
        self._push(s.duration, 100, EventType.SIM_END, "sim")

    def _push(
        self, time: float, priority: int, event_type: EventType,
        source: str, metadata: dict | None = None,
    ) -> None:
        """Push an event onto the priority queue."""
        heapq.heappush(
            self.queue,
            SimEvent(time=time, priority=priority, event_type=event_type,
                     source=source, metadata=metadata or {}),
        )

    def _seed_active_items(self) -> None:
        """Schedule initial active item uses."""
        schedule = self.config.active_schedule
        if not schedule:
            # Auto-schedule all DOT_ACTIVE behaviors on cooldown
            for b in self.behaviors:
                if b.behavior_type == ItemBehaviorType.DOT_ACTIVE:
                    schedule.append(ActiveUse(
                        item_name=b.item.name, first_use=0.5,
                        use_on_cooldown=True,
                    ))
        for use in schedule:
            t = use.first_use / self.settings.active_item_uptime if self.settings.active_item_uptime > 0 else use.first_use
            self._push(t, 3, EventType.ACTIVE_USE, use.item_name,
                       {"use_on_cooldown": use.use_on_cooldown})

    def _seed_abilities(self) -> None:
        """Schedule initial ability uses."""
        schedule = self.config.ability_schedule
        if not schedule:
            # Auto-schedule all damaging abilities on cooldown
            for i, ability in enumerate(self.config.attacker.abilities):
                if ability.base_damage > 0 and ability.cooldown > 0:
                    schedule.append(AbilityUse(
                        ability_index=i, first_use=0.1 * (i + 1),
                        use_on_cooldown=True,
                    ))
        for use in schedule:
            self._push(use.first_use, 4, EventType.ABILITY_USE,
                       f"ability_{use.ability_index}",
                       {"ability_index": use.ability_index,
                        "use_on_cooldown": use.use_on_cooldown})

    # ── Weapon firing & reload ────────────────────────────────

    def _handle_bullet_fire(self, event: SimEvent) -> None:
        """Fire a bullet, apply damage, trigger on-hit items, schedule next."""
        t = event.time
        atk = self.attacker
        s = self.settings

        # Uptime check — skip this shot window if weapon isn't active
        if s.weapon_uptime < 1.0:
            # Model uptime as periodic gaps: shoot for uptime%, idle for rest
            cycle = 2.0  # 2s evaluation window
            active_window = cycle * s.weapon_uptime
            if (t % cycle) >= active_window:
                next_active = t + (cycle - (t % cycle))
                self._push(next_active, 1, EventType.BULLET_FIRE, "weapon")
                return

        # Out of ammo -> reload
        if atk.ammo_remaining <= 0:
            self._push(t, 2, EventType.RELOAD_START, "weapon")
            return

        atk.ammo_remaining -= 1
        self._bullets_fired += 1

        # Accuracy: expected-value model
        hit_mult = s.accuracy
        hs_mult = 1.0
        is_hs = False
        if s.headshot_rate > 0:
            hs_mult = 1.0 + s.headshot_rate * (s.headshot_multiplier - 1.0)
            is_hs = s.headshot_rate > 0  # for logging: partial headshot

        # Bullet resist
        resist = self.target.effective_bullet_resist(t)
        raw_dmg = atk.weapon_damage * hit_mult * hs_mult
        final_dmg = raw_dmg * (1.0 - resist)

        if final_dmg > 0:
            self._apply_damage(t, "weapon", final_dmg, "bullet", is_hs)

        if is_hs and s.headshot_rate > 0:
            self._headshots += 1

        # Trigger on-hit items
        self._on_bullet_hit(t)

        # Schedule next bullet
        if atk.fire_rate > 0:
            interval = 1.0 / atk.fire_rate
            self._push(t + interval, 1, EventType.BULLET_FIRE, "weapon")

    def _handle_reload_start(self, event: SimEvent) -> None:
        """Begin reload. Optionally weave a melee hit."""
        t = event.time
        self._reloads += 1

        # Melee during reload window
        if self.settings.melee_after_reload:
            self._push(t + 0.1, 2, EventType.MELEE_HIT, "heavy_melee")

        self._push(t + self.attacker.reload_time, 1, EventType.RELOAD_END, "weapon")

    def _handle_reload_end(self, event: SimEvent) -> None:
        """Finish reload, resume firing."""
        self.attacker.ammo_remaining = self.attacker.magazine_size
        self._push(event.time, 1, EventType.BULLET_FIRE, "weapon")

    def _on_bullet_hit(self, t: float) -> None:
        """Process on-hit effects from all proc and buildup items."""
        # Proc items
        for b in self._proc_items:
            name = b.item.name
            next_avail = self.attacker.proc_cooldowns.get(name, 0.0)
            if t < next_avail:
                continue
            # Expected-value: scale damage by proc chance
            chance = min(1.0, b.proc_chance / 100.0)
            if chance <= 0:
                continue
            self._fire_proc(t, b, chance)
            self.attacker.proc_cooldowns[name] = t + b.proc_cooldown

        # Buildup items
        for b in self._buildup_items:
            self._advance_buildup(t, b)

    # ── Proc items ────────────────────────────────────────────

    def _fire_proc(self, t: float, b: ItemBehavior, chance: float) -> None:
        """Fire a proc item's damage (expected-value scaled by chance)."""
        name = b.item.name
        base = b.proc_damage
        if b.spirit_scale > 0:
            base += b.spirit_scale * self.attacker.spirit_power
        if b.boon_scale > 0:
            base += b.boon_scale * self.settings.attacker_boons

        scaled = base * chance

        if b.damage_type == DamageType.SPIRIT:
            self._apply_spirit_damage(t, name, scaled)
        else:
            resist = self.target.effective_bullet_resist(t)
            final = scaled * (1.0 - resist)
            if final > 0:
                self._apply_damage(t, name, final, "bullet")

        self._procs[name] = self._procs.get(name, 0) + 1

    # ── Buildup items ─────────────────────────────────────────

    def _advance_buildup(self, t: float, b: ItemBehavior) -> None:
        """Add buildup from a bullet hit. Trigger DoT at 100%."""
        name = b.item.name
        current, last_time = self.attacker.buildup_trackers.get(name, (0.0, 0.0))

        # Decay if too long since last shot
        if last_time > 0 and (t - last_time) > b.buildup_decay_time:
            current = 0.0

        current += b.buildup_per_shot
        self.attacker.buildup_trackers[name] = (current, t)

        # Trigger at 100%
        if current >= 100.0:
            self.attacker.buildup_trackers[name] = (0.0, t)
            self._start_dot(t, b)

    def _start_dot(self, t: float, b: ItemBehavior) -> None:
        """Start a DoT effect: schedule tick events."""
        if b.dot_tick_rate <= 0 or b.dot_duration <= 0:
            return

        num_ticks = int(b.dot_duration / b.dot_tick_rate)
        dot_id = f"{b.item.name}_{t:.3f}"

        for i in range(num_ticks):
            tick_time = t + b.dot_tick_rate * (i + 1)
            self._push(tick_time, 6, EventType.DOT_TICK, b.item.name,
                       {"dot_id": dot_id, "behavior_name": b.item.name})

    def _handle_dot_tick(self, event: SimEvent) -> None:
        """Process a single DoT tick (from items or abilities)."""
        t = event.time
        name = event.source
        meta = event.metadata

        # Ability-sourced DoT tick (pre-computed damage in metadata)
        if "ability_damage" in meta:
            self._apply_spirit_damage(t, name, meta["ability_damage"])
            return

        # Item-sourced DoT tick
        b = self._find_behavior(name)
        if b is None:
            return

        # Compute tick damage
        base_dps = b.dot_dps
        if b.dot_spirit_scale > 0:
            base_dps += b.dot_spirit_scale * self.attacker.spirit_power

        if b.dot_is_percent_hp:
            tick_dmg = (base_dps / 100.0) * self.target.max_hp * b.dot_tick_rate
        else:
            tick_dmg = base_dps * b.dot_tick_rate

        # DoTs deal spirit damage
        self._apply_spirit_damage(t, name, tick_dmg)

    def _find_behavior(self, item_name: str) -> ItemBehavior | None:
        """Find a behavior by item name."""
        for b in self.behaviors:
            if b.item.name == item_name:
                return b
        return None

    # ── Damage application & cross-interactions ───────────────

    def _apply_damage(
        self, t: float, source: str, damage: float,
        damage_type: str, is_headshot: bool = False,
    ) -> None:
        """Record damage and reduce target HP (handles shields first)."""
        remaining = damage

        # Absorb with shields first
        if damage_type == "bullet" and self.target.bullet_shield > 0:
            absorbed = min(self.target.bullet_shield, remaining)
            self.target.bullet_shield -= absorbed
            remaining -= absorbed
        elif damage_type == "spirit" and self.target.spirit_shield > 0:
            absorbed = min(self.target.spirit_shield, remaining)
            self.target.spirit_shield -= absorbed
            remaining -= absorbed

        self.target.hp -= remaining

        self.timeline.append(DamageEntry(
            time=t, source=source, damage=damage,
            damage_type=damage_type, is_headshot=is_headshot,
        ))

        if self.target.hp <= 0 and not self._dead:
            self._dead = True

    def _apply_spirit_damage(self, t: float, source: str, raw_damage: float) -> None:
        """Apply spirit damage with dynamic resist, amp, and cross-interaction triggers.

        This is the central point for all spirit damage. It:
        1. Reads current EE stacks for spirit amp
        2. Reads current Mystic Vuln / resist shred for resist
        3. Applies attacker spirit amp
        4. Computes final damage
        5. Triggers _on_spirit_damage for EE stacking / debuff refresh
        """
        # Spirit amp: attacker base + target amp stacks (EE)
        target_amp = self.target.effective_spirit_amp(t)
        total_amp = self.attacker.spirit_amp + target_amp

        # Spirit resist after shred debuffs
        resist = self.target.effective_spirit_resist(t)

        final = raw_damage * (1.0 + total_amp) * (1.0 - resist)

        if final > 0:
            self._apply_damage(t, source, final, "spirit")

        # Trigger on-spirit-damage effects (EE stacks, Mystic Vuln refresh)
        self._on_spirit_damage(t)

    def _on_spirit_damage(self, t: float) -> None:
        """Called after any spirit damage is dealt. Handles cross-item triggers."""
        for b in self._spirit_trigger_items:
            name = b.item.name

            if b.behavior_type == ItemBehaviorType.STACK_AMPLIFIER:
                # Escalating Exposure: add stack, refresh duration
                next_avail = self.attacker.proc_cooldowns.get(name, 0.0)
                if t < next_avail:
                    continue
                current = self.target.amp_stacks.get(name, (0, b.stack_value, 0.0))
                new_stacks = min(current[0] + 1, b.max_stacks)
                expire = t + b.debuff_duration
                self.target.amp_stacks[name] = (new_stacks, b.stack_value, expire)
                self.attacker.proc_cooldowns[name] = t + b.proc_cooldown

                # Also apply resist shred if EE has it
                if b.debuff_value != 0:
                    shred_amount = abs(b.debuff_value) / 100.0
                    self.target.resist_shreds[name] = (shred_amount, expire)

            elif b.behavior_type == ItemBehaviorType.RESIST_SHRED:
                # Mystic Vulnerability: apply/refresh spirit resist shred
                shred_amount = abs(b.debuff_value) / 100.0
                expire = t + b.debuff_duration
                self.target.resist_shreds[name] = (shred_amount, expire)

    # ── Active items ──────────────────────────────────────────

    def _handle_active_use(self, event: SimEvent) -> None:
        """Activate an active item (Decay, Alchemical Fire, etc.)."""
        t = event.time
        name = event.source
        meta = event.metadata

        b = self._find_behavior(name)
        if b is None:
            return

        # Start the DoT
        self._start_dot(t, b)

        # Put on cooldown
        cd = b.active_cooldown
        if self.attacker.cooldown_reduction > 0:
            cd *= (1.0 - self.attacker.cooldown_reduction)
            cd = max(0.5, cd)
        self.attacker.active_cooldowns[name] = t + cd

        # Reschedule if use_on_cooldown
        if meta.get("use_on_cooldown", False):
            self._push(t + cd, 3, EventType.ACTIVE_USE, name, meta)

    # ── Pulse items ───────────────────────────────────────────

    def _handle_pulse_trigger(self, event: SimEvent) -> None:
        """Fire a pulse item (Torment Pulse — auto-damage on cooldown)."""
        t = event.time
        name = event.source

        b = self._find_behavior(name)
        if b is None:
            return

        base = b.pulse_damage
        if b.pulse_spirit_scale > 0:
            base += b.pulse_spirit_scale * self.attacker.spirit_power

        self._apply_spirit_damage(t, name, base)
        self._procs[name] = self._procs.get(name, 0) + 1

        # Reschedule
        if b.pulse_cooldown > 0:
            self._push(t + b.pulse_cooldown, 5, EventType.PULSE_TRIGGER, name)

    # ── Hero abilities ────────────────────────────────────────

    def _handle_ability_use(self, event: SimEvent) -> None:
        """Cast a hero ability."""
        t = event.time
        meta = event.metadata
        idx = meta.get("ability_index", 0)

        abilities = self.config.attacker.abilities
        if idx >= len(abilities):
            return
        ability = abilities[idx]
        if ability.base_damage <= 0:
            return

        # Check cooldown
        next_avail = self.attacker.ability_cooldowns.get(idx, 0.0)
        if t < next_avail:
            # Reschedule at next available time
            if meta.get("use_on_cooldown", False):
                self._push(next_avail, 4, EventType.ABILITY_USE,
                           event.source, meta)
            return

        # Compute ability damage
        spirit = self.attacker.spirit_power
        spirit_contrib = ability.spirit_scaling * spirit
        raw = ability.base_damage + spirit_contrib

        if ability.duration > 0:
            # DoT ability: schedule ticks
            tick_rate = 1.0  # default tick rate for abilities
            num_ticks = int(ability.duration / tick_rate)
            dmg_per_tick = raw / num_ticks if num_ticks > 0 else raw
            for i in range(num_ticks):
                tick_t = t + tick_rate * (i + 1)
                self._push(tick_t, 6, EventType.DOT_TICK, ability.name,
                           {"ability_damage": dmg_per_tick})
        else:
            # Instant damage
            self._apply_spirit_damage(t, ability.name, raw)

        # Cooldown
        cd = ability.cooldown
        if self.attacker.cooldown_reduction > 0:
            cd *= (1.0 - self.attacker.cooldown_reduction)
            cd = max(0.1, cd)
        self.attacker.ability_cooldowns[idx] = t + cd

        # Reschedule
        if meta.get("use_on_cooldown", False):
            self._push(t + cd, 4, EventType.ABILITY_USE, event.source, meta)

    # ── Melee ─────────────────────────────────────────────────

    def _handle_melee_hit(self, event: SimEvent) -> None:
        """Process a melee hit (light or heavy)."""
        t = event.time
        source = event.source

        if source == "heavy_melee":
            raw = self.attacker.heavy_melee_damage
        else:
            raw = self.attacker.light_melee_damage

        # Melee uses bullet resist
        resist = self.target.effective_bullet_resist(t)
        final = raw * (1.0 - resist)

        if final > 0:
            self._apply_damage(t, source, final, "melee")

    # ── Regen ─────────────────────────────────────────────────

    def _handle_regen_tick(self, event: SimEvent) -> None:
        """Heal the target by their regen amount (1s tick)."""
        t = event.time
        if self._dead:
            return

        heal = self.target.hp_regen
        self.target.hp = min(self.target.max_hp, self.target.hp + heal)

        # Schedule next regen
        if t + 1.0 <= self.settings.duration:
            self._push(t + 1.0, 20, EventType.REGEN_TICK, "regen")

    # ── Event dispatch & main loop ────────────────────────────

    _DISPATCH: dict[EventType, str] = {
        EventType.BULLET_FIRE: "_handle_bullet_fire",
        EventType.RELOAD_START: "_handle_reload_start",
        EventType.RELOAD_END: "_handle_reload_end",
        EventType.DOT_TICK: "_handle_dot_tick",
        EventType.ACTIVE_USE: "_handle_active_use",
        EventType.PULSE_TRIGGER: "_handle_pulse_trigger",
        EventType.ABILITY_USE: "_handle_ability_use",
        EventType.MELEE_HIT: "_handle_melee_hit",
        EventType.REGEN_TICK: "_handle_regen_tick",
    }

    def _execute(self) -> None:
        """Process all events in the queue until sim ends or target dies."""
        max_events = 50_000  # safety cap
        processed = 0

        while self.queue and processed < max_events:
            event = heapq.heappop(self.queue)

            if event.time > self.settings.duration:
                break

            if event.event_type == EventType.SIM_END:
                break

            # Skip damage events if target already dead (but allow non-damage)
            if self._dead and event.event_type not in (
                EventType.REGEN_TICK, EventType.SIM_END,
            ):
                continue

            handler_name = self._DISPATCH.get(event.event_type)
            if handler_name:
                handler = getattr(self, handler_name)
                handler(event)

            processed += 1

    # ── Result builder ────────────────────────────────────────

    def _build_result(self) -> SimResult:
        """Aggregate timeline into SimResult."""
        total_damage = 0.0
        bullet_damage = 0.0
        spirit_damage = 0.0
        melee_damage = 0.0
        damage_by_source: dict[str, float] = {}

        for entry in self.timeline:
            total_damage += entry.damage
            damage_by_source[entry.source] = (
                damage_by_source.get(entry.source, 0.0) + entry.damage
            )
            if entry.damage_type == "bullet":
                bullet_damage += entry.damage
            elif entry.damage_type == "spirit":
                spirit_damage += entry.damage
            elif entry.damage_type == "melee":
                melee_damage += entry.damage

        duration = self.settings.duration
        # If target died, use kill time as effective duration
        kill_time = None
        if self._dead:
            for entry in self.timeline:
                kill_time = entry.time
            # Find exact kill moment
            running = 0.0
            for entry in self.timeline:
                running += entry.damage
                if running >= self.target.max_hp:
                    kill_time = entry.time
                    break
            if kill_time is not None:
                duration = max(0.01, kill_time)

        overall_dps = total_damage / duration if duration > 0 else 0.0
        dps_by_source = {
            src: dmg / duration for src, dmg in damage_by_source.items()
        } if duration > 0 else {}

        return SimResult(
            timeline=self.timeline,
            total_damage=total_damage,
            total_duration=duration,
            overall_dps=overall_dps,
            damage_by_source=damage_by_source,
            dps_by_source=dps_by_source,
            bullet_damage=bullet_damage,
            spirit_damage=spirit_damage,
            melee_damage=melee_damage,
            bullets_fired=self._bullets_fired,
            headshots=self._headshots,
            reloads=self._reloads,
            procs_triggered=dict(self._procs),
            kill_time=kill_time,
            target_hp_remaining=max(0.0, self.target.hp),
        )
