"""Event-driven combat timeline simulation engine.

Simulates a full combat encounter tick-by-tick using a priority queue.
Models weapon firing, item procs, DoTs, buildup mechanics, ability usage,
melee weaving, and cross-item interactions (EE stacks, Mystic Vuln, etc.).

Supports both unidirectional (attacker vs. passive target) and bidirectional
(both combatants attack each other simultaneously) combat modes.

All calculations are pure — no UI, no I/O, no side effects.
Leverages DamageCalculator for base damage math.
"""

from __future__ import annotations

import enum
import heapq
import logging
import math
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

from ..models import Build, BuildStats, HeroAbility, HeroStats, Item
from .builds import BuildEngine
from .damage import DamageCalculator, apply_ability_upgrades
from .primitives import extract_item_damage, falloff_multiplier, resist_after_shred


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
    DEBUFF_APPLIER = "debuff_applier"


class DebuffType(enum.Enum):
    """Mechanic-based debuff categories. Any item can contribute to these pools."""

    SPIRIT_RESIST_SHRED = "spirit_resist_shred"
    BULLET_RESIST_SHRED = "bullet_resist_shred"
    SPIRIT_AMP_STACK = "spirit_amp_stack"  # EE-style: stacks amplify spirit damage
    FIRE_RATE_SLOW = "fire_rate_slow"
    MOVE_SPEED_SLOW = "move_speed_slow"
    HEAL_REDUCTION = "heal_reduction"
    DAMAGE_AMP = "damage_amp"  # crippling / soulshredder: target takes more damage


@dataclass
class DebuffInstance:
    """A single debuff applied to the target, tracked by source and mechanic."""

    debuff_type: DebuffType
    source: str  # item or ability name that applied it
    value: float  # the magnitude (e.g., 0.08 for 8% shred, 4.5 for 4.5% per stack)
    expire_time: float  # when it falls off
    stacks: int = 1  # for stackable debuffs (EE)
    max_stacks: int = 1


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

    # Engagement range
    distance: float = 20.0  # meters; used for damage falloff

    # Melee
    weave_melee: bool = False  # weave light melee between reloads
    melee_after_reload: bool = True  # heavy melee during reload window
    reload_cancel_melee: bool = False  # melee interrupts reload (extends reload time)

    # Boons
    attacker_boons: int = 0
    defender_boons: int = 0

    # Buildup items
    # Default time (seconds of continuous fire, 100% accuracy) to proc each
    # buildup item.  Used to derive buildup_per_shot from the hero's fire rate.
    # Keys are item names; items not listed keep their API buildup_per_shot.
    buildup_time_defaults: dict[str, float] = field(default_factory=lambda: {
        "Toxic Bullets": 1.5,
        "Slowing Bullets": 1.0,
        "Weighted Shots": 1.0,
        "Silencer": 1.0,
        "Spiritual Overflow": 1.0,
        "Inhibitor": 1.0,
        "Glass Cannon": 1.0,
    })
    # Per-item buildup_per_shot overrides (% per bullet).  When set, takes
    # precedence over both the API value and buildup_time_defaults.
    buildup_overrides: dict[str, float] = field(default_factory=dict)

    # Bidirectional combat
    bidirectional: bool = False  # defender also attacks when True


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

    # Ability upgrades: maps ability index → list of active tier numbers
    attacker_ability_upgrades: dict[int, list[int]] = field(default_factory=dict)
    defender_ability_upgrades: dict[int, list[int]] = field(default_factory=dict)

    # Defender schedules (only used when bidirectional=True)
    defender_active_schedule: list[ActiveUse] = field(default_factory=list)
    defender_ability_schedule: list[AbilityUse] = field(default_factory=list)


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

    # Mechanic-based debuffs this item applies (list of (DebuffType, value) pairs)
    # These are applied on trigger (spirit damage, bullet hit, active use, etc.)
    on_hit_debuffs: list[tuple[DebuffType, float, float]] = field(default_factory=list)
    # Each entry: (DebuffType, value_per_application, duration)

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


def _collect_debuffs(props: dict, item_name: str) -> list[tuple[DebuffType, float, float]]:
    """Extract all mechanic-based debuffs an item applies from its properties.

    Returns list of (DebuffType, value, duration) tuples.
    """
    debuffs: list[tuple[DebuffType, float, float]] = []

    # Spirit resist shred
    if "TechArmorDamageReduction" in props:
        val = _prop_float(props, "TechArmorDamageReduction")
        if val != 0:
            dur = _prop_float(props, "AbilityDuration", 7.0)
            debuffs.append((DebuffType.SPIRIT_RESIST_SHRED, abs(val) / 100.0, max(dur, 1.0)))

    # Bullet resist shred
    if "BulletArmorDamageReduction" in props:
        val = _prop_float(props, "BulletArmorDamageReduction")
        if val != 0:
            dur = _prop_float(props, "AbilityDuration", 7.0)
            debuffs.append((DebuffType.BULLET_RESIST_SHRED, abs(val) / 100.0, max(dur, 1.0)))

    # Fire rate slow
    if "FireRateSlow" in props:
        val = _prop_float(props, "FireRateSlow")
        if val != 0:
            dur = _prop_float(props, "AbilityDuration", 5.0)
            debuffs.append((DebuffType.FIRE_RATE_SLOW, abs(val), max(dur, 1.0)))

    # Move speed slow
    if "SlowPercent" in props:
        val = _prop_float(props, "SlowPercent")
        if val != 0:
            dur = _prop_float(props, "SlowDuration", _prop_float(props, "AbilityDuration", 4.0))
            debuffs.append((DebuffType.MOVE_SPEED_SLOW, abs(val), max(dur, 1.0)))

    # Heal reduction
    if "HealAmpReceivePenaltyPercent" in props:
        val = _prop_float(props, "HealAmpReceivePenaltyPercent")
        if val != 0:
            dur = _prop_float(props, "AbilityDuration", _prop_float(props, "DotDuration", 5.0))
            debuffs.append((DebuffType.HEAL_REDUCTION, abs(val), max(dur, 1.0)))

    # Damage amplification (crippling/soulshredder style)
    if "DamageReceivedIncrease" in props:
        val = _prop_float(props, "DamageReceivedIncrease")
        if val != 0:
            dur = _prop_float(props, "AbilityDuration", 5.0)
            debuffs.append((DebuffType.DAMAGE_AMP, abs(val), max(dur, 1.0)))

    return debuffs


def classify_item(item: Item) -> ItemBehavior | None:
    """Classify an item into its simulation behavior type.

    Inspects raw_properties to determine how the item should be modeled
    in the combat simulation. Items are classified by their primary
    mechanic, and all debuffs they apply are collected generically.
    Returns None for passive-stat-only items.
    """
    props = item.raw_properties
    if not props:
        return None

    # Collect all mechanic debuffs this item applies
    debuffs = _collect_debuffs(props, item.name)

    # 1. Stack amplifiers (Escalating Exposure — has MagicIncreasePerStack)
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
            on_hit_debuffs=debuffs,
        )

    # 2. Buildup items (Toxic Bullets and others with BuildUpPerShot)
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
            dot_is_percent_hp=dot_dps > 0 and dot_dps < 20,
            on_hit_debuffs=debuffs,
        )

    # 3. Pulse items (Torment Pulse — auto-fires on cooldown)
    if "DamagePulseAmount" in props:
        scale_type, scale_val = _prop_scale(props, "DamagePulseAmount")
        return ItemBehavior(
            item=item,
            behavior_type=ItemBehaviorType.PULSE_PASSIVE,
            damage_type=DamageType.SPIRIT,
            pulse_damage=_prop_float(props, "DamagePulseAmount"),
            pulse_cooldown=_prop_float(props, "AbilityCooldown", 1.4),
            pulse_spirit_scale=scale_val if scale_type == "ETechPower" else 0.0,
            on_hit_debuffs=debuffs,
        )

    # 4. Active DoT items (Decay, Alchemical Fire)
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
            on_hit_debuffs=debuffs,
        )

    # 5. Proc-on-hit items (Tesla Bullets, Mystic Shot, Siphon Bullets)
    if "ProcCooldown" in props:
        damage_info = extract_item_damage(props)
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
                on_hit_debuffs=debuffs,
            )

    # 6. Debuff-only items (Mystic Vulnerability, Spirit Shredder, etc.)
    #    Items that primarily apply debuffs but don't deal damage directly
    if debuffs:
        return ItemBehavior(
            item=item,
            behavior_type=ItemBehaviorType.DEBUFF_APPLIER,
            damage_type=DamageType.SPIRIT,
            debuff_duration=debuffs[0][2],  # use first debuff's duration
            on_hit_debuffs=debuffs,
            proc_cooldown=_prop_float(props, "ProcCooldown", 0.0),
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

    Sorted by (time, priority, combatant) so ties resolve deterministically.
    Lower priority number fires first at the same timestamp.
    Combatant "a" processes before "b" at the same (time, priority).
    """

    time: float
    priority: int = 0
    combatant: str = field(default="a")  # "a" or "b"
    event_type: EventType = field(compare=False, default=EventType.BULLET_FIRE)
    source: str = field(compare=False, default="")
    metadata: dict = field(compare=False, default_factory=dict)


# ── Mutable combat state ─────────────────────────────────────────


@dataclass
class TargetState:
    """Mutable defensive state of a combatant.

    Tracks HP, shields, regen, and active debuffs applied by the opponent.
    Debuffs are tracked by mechanic type (not by item name) so any item
    contributing to e.g. spirit_resist_shred feeds the same pool.
    """

    # Health
    hp: float = 0.0
    max_hp: float = 0.0
    bullet_shield: float = 0.0
    spirit_shield: float = 0.0
    hp_regen: float = 0.0
    base_fire_rate: float = 0.0  # defender's base fire rate (for slow calcs)

    # Base resists (from hero + items)
    base_bullet_resist: float = 0.0
    base_spirit_resist: float = 0.0

    # Mechanic-based debuff pool: all active debuffs on this target
    debuffs: list[DebuffInstance] = field(default_factory=list)

    # ── Debuff totals (computed from active debuffs) ──────────

    def total_for(self, debuff_type: DebuffType, time: float) -> float:
        """Sum all active debuff values of a given type (additive)."""
        total = 0.0
        for d in self.debuffs:
            if d.debuff_type == debuff_type and d.expire_time > time:
                total += d.value * d.stacks
        return total

    def effective_bullet_resist(self, time: float) -> float:
        """Current bullet resist after all bullet resist shred debuffs."""
        shred = min(1.0, self.total_for(DebuffType.BULLET_RESIST_SHRED, time))
        return resist_after_shred(self.base_bullet_resist, shred)

    def effective_spirit_resist(self, time: float) -> float:
        """Current spirit resist after all spirit resist shred debuffs."""
        shred = min(1.0, self.total_for(DebuffType.SPIRIT_RESIST_SHRED, time))
        return resist_after_shred(self.base_spirit_resist, shred)

    def effective_spirit_amp(self, time: float) -> float:
        """Spirit damage amp from all amp stacks on target (EE, etc.)."""
        return self.total_for(DebuffType.SPIRIT_AMP_STACK, time) / 100.0

    def effective_damage_amp(self, time: float) -> float:
        """Extra damage taken from crippling / soulshredder effects."""
        return self.total_for(DebuffType.DAMAGE_AMP, time) / 100.0

    def effective_heal_reduction(self, time: float) -> float:
        """Heal/regen reduction on target (0-1 scale, clamped)."""
        return min(1.0, self.total_for(DebuffType.HEAL_REDUCTION, time) / 100.0)

    def effective_fire_rate_slow(self, time: float) -> float:
        """Fire rate slow on target (percentage, for defender actions)."""
        return self.total_for(DebuffType.FIRE_RATE_SLOW, time) / 100.0

    def apply_debuff(
        self, debuff_type: DebuffType, source: str, value: float,
        duration: float, time: float, max_stacks: int = 1,
    ) -> None:
        """Apply or refresh a debuff. Stacking debuffs increment stacks."""
        expire = time + duration
        # Look for existing debuff from same source + type
        for d in self.debuffs:
            if d.debuff_type == debuff_type and d.source == source:
                if max_stacks > 1:
                    d.stacks = min(d.stacks + 1, max_stacks)
                d.expire_time = expire  # refresh duration
                return
        # New debuff
        self.debuffs.append(DebuffInstance(
            debuff_type=debuff_type, source=source, value=value,
            expire_time=expire, stacks=1, max_stacks=max_stacks,
        ))

    def cleanup_expired(self, time: float) -> None:
        """Remove expired debuffs."""
        self.debuffs = [d for d in self.debuffs if d.expire_time > time]

    def debuff_summary(self, time: float) -> dict[str, float]:
        """Return current totals for all debuff types (for reporting)."""
        summary: dict[str, float] = {}
        for dt in DebuffType:
            val = self.total_for(dt, time)
            if val != 0:
                summary[dt.value] = val
        return summary


@dataclass
class AttackerState:
    """Mutable offensive state of a combatant.

    Tracks ammo, cooldowns, buildup meters, and derived combat stats.
    Initialized from HeroStats + Build + boons.
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
    item_cooldown_reduction: float = 0.0

    # Distance falloff multiplier (precomputed from hero range + engagement distance)
    falloff: float = 1.0

    # Lifesteal
    bullet_lifesteal: float = 0.0
    spirit_lifesteal: float = 0.0

    # Buildup trackers: item_name -> (current_buildup, last_shot_time)
    buildup_trackers: dict[str, tuple[float, float]] = field(default_factory=dict)

    # Proc cooldown trackers: item_name -> next_available_time
    proc_cooldowns: dict[str, float] = field(default_factory=dict)

    # Active item cooldowns: item_name -> next_available_time
    active_cooldowns: dict[str, float] = field(default_factory=dict)

    # Ability cooldowns: ability_index -> next_available_time
    ability_cooldowns: dict[int, float] = field(default_factory=dict)


@dataclass
class CombatantState:
    """Full state of a combatant: offensive + defensive."""

    attack: AttackerState = field(default_factory=AttackerState)
    defense: TargetState = field(default_factory=TargetState)
    hero: HeroStats = field(default_factory=lambda: HeroStats(name="Unknown"))
    boons: int = 0

    # Per-combatant behavior lists (classified from build items)
    behaviors: list[ItemBehavior] = field(default_factory=list)
    proc_items: list[ItemBehavior] = field(default_factory=list)
    buildup_items: list[ItemBehavior] = field(default_factory=list)
    stack_amplifiers: list[ItemBehavior] = field(default_factory=list)
    debuff_items: list[ItemBehavior] = field(default_factory=list)
    pulse_items: list[ItemBehavior] = field(default_factory=list)

    # Per-combatant counters
    bullets_fired: int = 0
    headshots: int = 0
    reloads: int = 0
    procs: dict[str, int] = field(default_factory=dict)


# ── Simulation output ─────────────────────────────────────────────


@dataclass
class DamageEntry:
    """A single damage instance logged in the timeline."""

    time: float
    source: str  # "weapon", item name, ability name, "light_melee", "heavy_melee"
    damage: float  # after resist/amp
    damage_type: str  # "bullet", "spirit", "melee"
    combatant: str = "a"  # which combatant dealt this damage
    is_headshot: bool = False


@dataclass
class SimResult:
    """Full output of a combat simulation."""

    # Timeline
    timeline: list[DamageEntry] = field(default_factory=list)

    # Totals (attacker / combatant A perspective)
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

    # ── Bidirectional fields (None when unidirectional) ────────
    defender_total_damage: float | None = None
    defender_dps: float | None = None
    defender_damage_by_source: dict[str, float] | None = None
    defender_dps_by_source: dict[str, float] | None = None
    defender_bullet_damage: float | None = None
    defender_spirit_damage: float | None = None
    defender_melee_damage: float | None = None
    defender_bullets_fired: int | None = None
    defender_headshots: int | None = None
    defender_reloads: int | None = None
    defender_procs_triggered: dict[str, int] | None = None
    defender_kill_time: float | None = None
    attacker_hp_remaining: float | None = None
    winner: str | None = None  # "a", "b", or None (draw / nobody died)


# ── Combat simulator ──────────────────────────────────────────────


class CombatSimulator:
    """Event-driven combat timeline simulation engine.

    Processes a priority queue of SimEvents to model a full combat
    encounter with weapon firing, item procs, DoTs, cross-interactions,
    abilities, and melee.

    Supports bidirectional mode where both combatants attack each other.
    """

    def __init__(self, config: SimConfig) -> None:
        self.config = config
        self.settings = config.settings
        self.queue: list[SimEvent] = []
        self.timeline: list[DamageEntry] = []

        # Two combatant states (always created; B only seeds events if bidirectional)
        self.a = CombatantState()
        self.b = CombatantState()

        # Initial effective HP (HP + shields), captured after _initialize
        # so _find_kill_time uses the pre-combat values (shields deplete during sim).
        self._a_effective_hp: float = 0.0
        self._b_effective_hp: float = 0.0

    # ── Public API ────────────────────────────────────────────

    @classmethod
    def run(cls, config: SimConfig) -> SimResult:
        """Run a full combat simulation and return results."""
        t0 = time.monotonic()
        log.info(
            "Simulation start: %s vs %s (duration=%.1fs, bidirectional=%s)",
            config.attacker.name,
            config.defender.name,
            config.settings.duration,
            config.settings.bidirectional,
        )
        sim = cls(config)
        sim._initialize()
        sim._execute()
        result = sim._build_result()
        elapsed = time.monotonic() - t0
        log.info("Simulation complete in %.3fs — TTK=%.2fs", elapsed, result.kill_time or result.total_duration)
        return result

    # ── Initialization ────────────────────────────────────────

    def _build_combatant(
        self, hero: HeroStats, build: Build, boons: int,
    ) -> CombatantState:
        """Build a full CombatantState from hero + build + boons."""
        s = self.settings
        stats = BuildEngine.aggregate_stats(build)

        # Offensive state
        boon_dmg = DamageCalculator.bullet_damage_at_boon(hero, boons)
        weapon_bonus = stats.weapon_damage_pct
        eff_pellets = DamageCalculator.effective_pellets(hero)
        dmg_per_bullet = boon_dmg * eff_pellets * (1.0 + weapon_bonus)
        fire_rate = DamageCalculator.fire_rate_with_bonus(hero, stats.fire_rate_pct)
        mag_size = DamageCalculator.effective_magazine(
            hero, stats.ammo_pct, stats.ammo_flat
        )

        spirit_from_boons = hero.spirit_gain * boons
        spirit_power = (spirit_from_boons + stats.spirit_power) * (1.0 + stats.spirit_power_pct)

        melee_boon = hero.damage_gain * boons
        melee_weapon_bonus = weapon_bonus * DamageCalculator.MELEE_WEAPON_SCALE
        melee_dmg_pct = stats.melee_damage_pct
        heavy_melee_dmg_pct = stats.heavy_melee_damage_pct
        light_melee = (hero.light_melee_damage + melee_boon) * (1.0 + melee_weapon_bonus + melee_dmg_pct)
        heavy_melee = (hero.heavy_melee_damage + melee_boon) * (1.0 + melee_weapon_bonus + melee_dmg_pct + heavy_melee_dmg_pct)

        attack = AttackerState(
            ammo_remaining=mag_size,
            weapon_damage=dmg_per_bullet,
            pellets=eff_pellets,
            fire_rate=fire_rate,
            magazine_size=mag_size,
            reload_time=hero.reload_duration if hero.reload_duration > 0 else 1.0,
            light_melee_damage=light_melee,
            heavy_melee_damage=heavy_melee,
            spirit_power=spirit_power,
            spirit_amp=stats.spirit_amp_pct,
            weapon_damage_bonus=weapon_bonus,
            cooldown_reduction=stats.cooldown_reduction,
            item_cooldown_reduction=stats.item_cooldown_reduction,
            falloff=falloff_multiplier(
                s.distance, hero.falloff_range_min, hero.falloff_range_max,
            ),
            bullet_lifesteal=stats.bullet_lifesteal,
            spirit_lifesteal=stats.spirit_lifesteal,
        )

        # Defensive state
        base_hp = (hero.base_hp + (hero.hp_gain * boons)) * (1.0 + stats.base_hp_pct)
        total_hp = base_hp + stats.bonus_hp

        defense = TargetState(
            hp=total_hp,
            max_hp=total_hp,
            bullet_shield=stats.bullet_shield,
            spirit_shield=stats.spirit_shield,
            hp_regen=hero.base_regen + stats.hp_regen,
            base_bullet_resist=stats.bullet_resist_pct,
            base_spirit_resist=stats.spirit_resist_pct,
        )

        # Classify items
        behaviors = classify_build(build)
        proc_items = []
        buildup_items = []
        stack_amplifiers = []
        debuff_items = []
        pulse_items = []
        for b in behaviors:
            if b.behavior_type == ItemBehaviorType.PROC_ON_HIT:
                proc_items.append(b)
            elif b.behavior_type == ItemBehaviorType.BUILDUP:
                # Apply hero-scaled buildup rate
                name = b.item.name
                if name in s.buildup_overrides:
                    b.buildup_per_shot = s.buildup_overrides[name]
                elif name in s.buildup_time_defaults and fire_rate > 0:
                    shots = fire_rate * s.buildup_time_defaults[name]
                    b.buildup_per_shot = 100.0 / shots if shots > 0 else b.buildup_per_shot
                buildup_items.append(b)
            elif b.behavior_type == ItemBehaviorType.STACK_AMPLIFIER:
                stack_amplifiers.append(b)
            elif b.behavior_type == ItemBehaviorType.PULSE_PASSIVE:
                pulse_items.append(b)
            if b.on_hit_debuffs:
                debuff_items.append(b)

        return CombatantState(
            attack=attack,
            defense=defense,
            hero=hero,
            boons=boons,
            behaviors=behaviors,
            proc_items=proc_items,
            buildup_items=buildup_items,
            stack_amplifiers=stack_amplifiers,
            debuff_items=debuff_items,
            pulse_items=pulse_items,
        )

    def _initialize(self) -> None:
        """Set up both combatant states and seed events."""
        s = self.settings

        # Build combatant states
        self.a = self._build_combatant(
            self.config.attacker, self.config.attacker_build, s.attacker_boons,
        )
        self.b = self._build_combatant(
            self.config.defender, self.config.defender_build, s.defender_boons,
        )

        # Seed combatant A events (always)
        self._seed_combatant_events(
            "a", self.a,
            self.config.active_schedule, self.config.ability_schedule,
        )

        # Seed combatant B events (only when bidirectional)
        if s.bidirectional:
            self._seed_combatant_events(
                "b", self.b,
                self.config.defender_active_schedule,
                self.config.defender_ability_schedule,
            )

        # Regen ticks for both combatants
        if self.b.defense.hp_regen > 0:
            self._push(1.0, 20, EventType.REGEN_TICK, "regen", combatant="b")
        if s.bidirectional and self.a.defense.hp_regen > 0:
            self._push(1.0, 20, EventType.REGEN_TICK, "regen", combatant="a")

        # Capture initial effective HP (before shields are consumed)
        self._b_effective_hp = self._initial_effective_hp(self.b.defense)
        self._a_effective_hp = self._initial_effective_hp(self.a.defense)

        # End marker
        self._push(s.duration, 100, EventType.SIM_END, "sim")

    def _seed_combatant_events(
        self, cid: str, combatant: CombatantState,
        active_schedule: list[ActiveUse], ability_schedule: list[AbilityUse],
    ) -> None:
        """Seed weapon, pulse, active, and ability events for a combatant."""
        # Weapon fire
        self._push(0.0, 0, EventType.BULLET_FIRE, "weapon", combatant=cid)

        # Pulse items
        for b in combatant.pulse_items:
            self._push(0.0, 5, EventType.PULSE_TRIGGER, b.item.name, combatant=cid)

        # Active items
        schedule = list(active_schedule)
        if not schedule:
            for b in combatant.behaviors:
                if b.behavior_type == ItemBehaviorType.DOT_ACTIVE:
                    schedule.append(ActiveUse(
                        item_name=b.item.name, first_use=0.5,
                        use_on_cooldown=True,
                    ))
        for use in schedule:
            t = use.first_use / self.settings.active_item_uptime if self.settings.active_item_uptime > 0 else use.first_use
            self._push(t, 3, EventType.ACTIVE_USE, use.item_name,
                       metadata={"use_on_cooldown": use.use_on_cooldown},
                       combatant=cid)

        # Abilities
        ab_schedule = list(ability_schedule)
        if not ab_schedule:
            for i, ability in enumerate(combatant.hero.abilities):
                if ability.base_damage > 0 and ability.cooldown > 0:
                    ab_schedule.append(AbilityUse(
                        ability_index=i, first_use=0.1 * (i + 1),
                        use_on_cooldown=True,
                    ))
        for use in ab_schedule:
            self._push(use.first_use, 4, EventType.ABILITY_USE,
                       f"ability_{use.ability_index}",
                       metadata={"ability_index": use.ability_index,
                                 "use_on_cooldown": use.use_on_cooldown},
                       combatant=cid)

    def _push(
        self, time: float, priority: int, event_type: EventType,
        source: str, metadata: dict | None = None, combatant: str = "a",
    ) -> None:
        """Push an event onto the priority queue."""
        heapq.heappush(
            self.queue,
            SimEvent(time=time, priority=priority, combatant=combatant,
                     event_type=event_type, source=source,
                     metadata=metadata or {}),
        )

    # ── Weapon firing & reload ────────────────────────────────

    def _handle_bullet_fire(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Fire a bullet, apply damage, trigger on-hit items, schedule next."""
        t = event.time
        cid = event.combatant
        atk = actor.attack
        s = self.settings

        # Uptime check — skip this shot window if weapon isn't active
        if s.weapon_uptime < 1.0:
            cycle = 2.0
            active_window = cycle * s.weapon_uptime
            if (t % cycle) >= active_window:
                next_active = t + (cycle - (t % cycle))
                self._push(next_active, 1, EventType.BULLET_FIRE, "weapon", combatant=cid)
                return

        # Out of ammo -> reload
        if atk.ammo_remaining <= 0:
            self._push(t, 2, EventType.RELOAD_START, "weapon", combatant=cid)
            return

        atk.ammo_remaining -= 1
        actor.bullets_fired += 1

        # Accuracy: expected-value model
        hit_mult = s.accuracy
        hs_mult = 1.0
        is_hs = False
        if s.headshot_rate > 0:
            hero_hs_mult = actor.hero.crit_bonus_start
            hs_mult = 1.0 + s.headshot_rate * (hero_hs_mult - 1.0)
            is_hs = s.headshot_rate > 0

        # Bullet resist + damage amp from debuffs on opponent
        resist = opponent.defense.effective_bullet_resist(t)
        damage_amp = opponent.defense.effective_damage_amp(t)
        raw_dmg = atk.weapon_damage * hit_mult * hs_mult
        final_dmg = raw_dmg * atk.falloff * (1.0 + damage_amp) * (1.0 - resist)

        if final_dmg > 0:
            self._apply_damage(t, "weapon", final_dmg, "bullet", cid, actor, opponent, is_hs)

        if is_hs and s.headshot_rate > 0:
            actor.headshots += 1

        # Trigger on-hit items and bullet-triggered debuffs
        self._on_bullet_hit(t, actor, opponent, cid)
        self._on_bullet_damage(t, actor, opponent)

        # Schedule next bullet (apply fire rate slow from debuffs on actor)
        if atk.fire_rate > 0:
            fire_rate_slow = actor.defense.effective_fire_rate_slow(t)
            effective_fire_rate = atk.fire_rate * (1.0 - fire_rate_slow)
            effective_fire_rate = max(0.1, effective_fire_rate)
            interval = 1.0 / effective_fire_rate
            self._push(t + interval, 1, EventType.BULLET_FIRE, "weapon", combatant=cid)

    def _handle_reload_start(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Begin reload. Optionally weave a melee hit."""
        t = event.time
        cid = event.combatant
        actor.reloads += 1

        reload_extension = 0.0
        if self.settings.melee_after_reload:
            self._push(t + 0.1, 2, EventType.MELEE_HIT, "heavy_melee", combatant=cid)
            if self.settings.reload_cancel_melee:
                reload_extension = DamageCalculator.HEAVY_MELEE_CYCLE

        self._push(t + actor.attack.reload_time + reload_extension, 1,
                   EventType.RELOAD_END, "weapon", combatant=cid)

    def _handle_reload_end(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Finish reload, resume firing."""
        actor.attack.ammo_remaining = actor.attack.magazine_size
        self._push(event.time, 1, EventType.BULLET_FIRE, "weapon", combatant=event.combatant)

    def _on_bullet_hit(
        self, t: float, actor: CombatantState, opponent: CombatantState, cid: str,
    ) -> None:
        """Process on-hit effects from all proc and buildup items."""
        # Proc items
        for b in actor.proc_items:
            name = b.item.name
            next_avail = actor.attack.proc_cooldowns.get(name, 0.0)
            if t < next_avail:
                continue
            chance = min(1.0, b.proc_chance / 100.0)
            if chance <= 0:
                continue
            self._fire_proc(t, b, chance, actor, opponent, cid)
            actor.attack.proc_cooldowns[name] = t + b.proc_cooldown

        # Buildup items
        for b in actor.buildup_items:
            self._advance_buildup(t, b, actor, opponent, cid)

    # ── Proc items ────────────────────────────────────────────

    def _fire_proc(
        self, t: float, b: ItemBehavior, chance: float,
        actor: CombatantState, opponent: CombatantState, cid: str,
    ) -> None:
        """Fire a proc item's damage (expected-value scaled by chance)."""
        name = b.item.name
        base = b.proc_damage
        if b.spirit_scale > 0:
            base += b.spirit_scale * actor.attack.spirit_power
        if b.boon_scale > 0:
            base += b.boon_scale * actor.boons

        scaled = base * chance

        if b.damage_type == DamageType.SPIRIT:
            self._apply_spirit_damage(t, name, scaled, actor, opponent, cid)
        else:
            resist = opponent.defense.effective_bullet_resist(t)
            final = scaled * (1.0 - resist)
            if final > 0:
                self._apply_damage(t, name, final, "bullet", cid, actor, opponent)

        actor.procs[name] = actor.procs.get(name, 0) + 1

    # ── Buildup items ─────────────────────────────────────────

    def _advance_buildup(
        self, t: float, b: ItemBehavior,
        actor: CombatantState, opponent: CombatantState, cid: str,
    ) -> None:
        """Add buildup from a bullet hit. Trigger DoT at 100%."""
        name = b.item.name
        current, last_time = actor.attack.buildup_trackers.get(name, (0.0, 0.0))

        if last_time > 0 and (t - last_time) > b.buildup_decay_time:
            current = 0.0

        current += b.buildup_per_shot
        actor.attack.buildup_trackers[name] = (current, t)

        if current >= 100.0:
            actor.attack.buildup_trackers[name] = (0.0, t)
            self._start_dot(t, b, cid)

    def _start_dot(self, t: float, b: ItemBehavior, cid: str) -> None:
        """Start a DoT effect: schedule tick events."""
        if b.dot_tick_rate <= 0 or b.dot_duration <= 0:
            return

        num_ticks = int(b.dot_duration / b.dot_tick_rate)
        dot_id = f"{b.item.name}_{t:.3f}"

        for i in range(num_ticks):
            tick_time = t + b.dot_tick_rate * (i + 1)
            self._push(tick_time, 6, EventType.DOT_TICK, b.item.name,
                       metadata={"dot_id": dot_id, "behavior_name": b.item.name},
                       combatant=cid)

    def _handle_dot_tick(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Process a single DoT tick (from items or abilities)."""
        t = event.time
        cid = event.combatant
        name = event.source
        meta = event.metadata

        # Ability-sourced DoT tick (pre-computed damage in metadata)
        if "ability_damage" in meta:
            self._apply_spirit_damage(t, name, meta["ability_damage"], actor, opponent, cid)
            return

        # Item-sourced DoT tick
        b = self._find_behavior(name, actor)
        if b is None:
            return

        base_dps = b.dot_dps
        if b.dot_spirit_scale > 0:
            base_dps += b.dot_spirit_scale * actor.attack.spirit_power

        if b.dot_is_percent_hp:
            tick_dmg = (base_dps / 100.0) * opponent.defense.max_hp * b.dot_tick_rate
        else:
            tick_dmg = base_dps * b.dot_tick_rate

        self._apply_spirit_damage(t, name, tick_dmg, actor, opponent, cid)

    def _find_behavior(self, item_name: str, actor: CombatantState) -> ItemBehavior | None:
        """Find a behavior by item name in the actor's behaviors."""
        for b in actor.behaviors:
            if b.item.name == item_name:
                return b
        return None

    # ── Damage application & cross-interactions ───────────────

    def _apply_damage(
        self, t: float, source: str, damage: float,
        damage_type: str, cid: str,
        actor: CombatantState, opponent: CombatantState,
        is_headshot: bool = False,
    ) -> None:
        """Record damage, reduce opponent HP (shields first), apply lifesteal."""
        remaining = damage

        # Absorb with shields first
        if damage_type == "bullet" and opponent.defense.bullet_shield > 0:
            absorbed = min(opponent.defense.bullet_shield, remaining)
            opponent.defense.bullet_shield -= absorbed
            remaining -= absorbed
        elif damage_type == "spirit" and opponent.defense.spirit_shield > 0:
            absorbed = min(opponent.defense.spirit_shield, remaining)
            opponent.defense.spirit_shield -= absorbed
            remaining -= absorbed

        opponent.defense.hp -= remaining

        self.timeline.append(DamageEntry(
            time=t, source=source, damage=damage,
            damage_type=damage_type, combatant=cid, is_headshot=is_headshot,
        ))

        # Lifesteal: heal the actor based on damage type
        if damage_type in ("bullet", "melee"):
            ls_rate = actor.attack.bullet_lifesteal
        else:  # spirit
            ls_rate = actor.attack.spirit_lifesteal

        if ls_rate > 0 and remaining > 0:
            heal = remaining * ls_rate
            # Apply heal reduction on actor (debuffs from opponent)
            heal_reduction = actor.defense.effective_heal_reduction(t)
            heal *= (1.0 - heal_reduction)
            if heal > 0:
                actor.defense.hp = min(actor.defense.max_hp, actor.defense.hp + heal)

    def _apply_spirit_damage(
        self, t: float, source: str, raw_damage: float,
        actor: CombatantState, opponent: CombatantState, cid: str,
    ) -> None:
        """Apply spirit damage with all mechanic-based modifiers."""
        target_amp = opponent.defense.effective_spirit_amp(t)
        total_amp = actor.attack.spirit_amp + target_amp

        resist = opponent.defense.effective_spirit_resist(t)
        damage_amp = opponent.defense.effective_damage_amp(t)

        final = raw_damage * (1.0 + total_amp) * (1.0 + damage_amp) * (1.0 - resist)

        if final > 0:
            self._apply_damage(t, source, final, "spirit", cid, actor, opponent)

        # Trigger on-spirit-damage effects
        self._on_spirit_damage(t, actor, opponent)

    def _on_spirit_damage(
        self, t: float, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Called after any spirit damage. Applies all on-spirit-damage debuffs."""
        for b in actor.stack_amplifiers:
            name = b.item.name
            next_avail = actor.attack.proc_cooldowns.get(name, 0.0)
            if t < next_avail:
                continue
            opponent.defense.apply_debuff(
                DebuffType.SPIRIT_AMP_STACK, name, b.stack_value,
                b.debuff_duration, t, max_stacks=b.max_stacks,
            )
            actor.attack.proc_cooldowns[name] = t + b.proc_cooldown

        for b in actor.debuff_items:
            name = b.item.name
            if b.proc_cooldown > 0:
                next_avail = actor.attack.proc_cooldowns.get(name, 0.0)
                if t < next_avail:
                    continue
                actor.attack.proc_cooldowns[name] = t + b.proc_cooldown
            for debuff_type, value, duration in b.on_hit_debuffs:
                max_stk = b.max_stacks if b.max_stacks > 0 else 1
                opponent.defense.apply_debuff(debuff_type, name, value, duration, t, max_stk)

    def _on_bullet_damage(
        self, t: float, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Called after bullet damage. Applies bullet-triggered debuffs."""
        for b in actor.debuff_items:
            if b.behavior_type not in (
                ItemBehaviorType.DEBUFF_APPLIER,
                ItemBehaviorType.BUILDUP,
            ):
                continue
            name = b.item.name
            if b.proc_cooldown > 0:
                next_avail = actor.attack.proc_cooldowns.get(name, 0.0)
                if t < next_avail:
                    continue
                actor.attack.proc_cooldowns[name] = t + b.proc_cooldown
            for debuff_type, value, duration in b.on_hit_debuffs:
                max_stk = b.max_stacks if b.max_stacks > 0 else 1
                opponent.defense.apply_debuff(debuff_type, name, value, duration, t, max_stk)

    # ── Active items ──────────────────────────────────────────

    def _handle_active_use(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Activate an active item (Decay, Alchemical Fire, etc.)."""
        t = event.time
        cid = event.combatant
        name = event.source
        meta = event.metadata

        b = self._find_behavior(name, actor)
        if b is None:
            return

        self._start_dot(t, b, cid)

        cd = b.active_cooldown
        if actor.attack.item_cooldown_reduction > 0:
            cd *= (1.0 - actor.attack.item_cooldown_reduction)
            cd = max(0.5, cd)
        actor.attack.active_cooldowns[name] = t + cd

        if meta.get("use_on_cooldown", False):
            self._push(t + cd, 3, EventType.ACTIVE_USE, name,
                       metadata=meta, combatant=cid)

    # ── Pulse items ───────────────────────────────────────────

    def _handle_pulse_trigger(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Fire a pulse item (Torment Pulse — auto-damage on cooldown)."""
        t = event.time
        cid = event.combatant
        name = event.source

        b = self._find_behavior(name, actor)
        if b is None:
            return

        base = b.pulse_damage
        if b.pulse_spirit_scale > 0:
            base += b.pulse_spirit_scale * actor.attack.spirit_power

        self._apply_spirit_damage(t, name, base, actor, opponent, cid)
        actor.procs[name] = actor.procs.get(name, 0) + 1

        if b.pulse_cooldown > 0:
            self._push(t + b.pulse_cooldown, 5, EventType.PULSE_TRIGGER, name, combatant=cid)

    # ── Hero abilities ────────────────────────────────────────

    def _handle_ability_use(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Cast a hero ability."""
        t = event.time
        cid = event.combatant
        meta = event.metadata
        idx = meta.get("ability_index", 0)

        abilities = actor.hero.abilities
        if idx >= len(abilities):
            return
        ability = abilities[idx]
        if ability.base_damage <= 0:
            return

        next_avail = actor.attack.ability_cooldowns.get(idx, 0.0)
        if t < next_avail:
            if meta.get("use_on_cooldown", False):
                self._push(next_avail, 4, EventType.ABILITY_USE,
                           event.source, metadata=meta, combatant=cid)
            return

        # Apply ability upgrades if configured
        upgrades_map = (self.config.attacker_ability_upgrades if cid == "a"
                        else self.config.defender_ability_upgrades)
        tiers = upgrades_map.get(idx)
        base_damage = ability.base_damage
        cooldown = ability.cooldown
        duration = ability.duration
        spirit_scaling = ability.spirit_scaling
        if tiers:
            base_damage, cooldown, duration, spirit_scaling = apply_ability_upgrades(
                ability, tiers
            )

        spirit = actor.attack.spirit_power
        spirit_contrib = spirit_scaling * spirit
        raw = base_damage + spirit_contrib

        if duration > 0:
            tick_rate = 1.0
            num_ticks = int(duration / tick_rate)
            dmg_per_tick = raw / num_ticks if num_ticks > 0 else raw
            for i in range(num_ticks):
                tick_t = t + tick_rate * (i + 1)
                self._push(tick_t, 6, EventType.DOT_TICK, ability.name,
                           metadata={"ability_damage": dmg_per_tick},
                           combatant=cid)
        else:
            self._apply_spirit_damage(t, ability.name, raw, actor, opponent, cid)

        cd = cooldown
        if actor.attack.cooldown_reduction > 0:
            cd *= (1.0 - actor.attack.cooldown_reduction)
            cd = max(0.1, cd)
        actor.attack.ability_cooldowns[idx] = t + cd

        if meta.get("use_on_cooldown", False):
            self._push(t + cd, 4, EventType.ABILITY_USE, event.source,
                       metadata=meta, combatant=cid)

    # ── Melee ─────────────────────────────────────────────────

    def _handle_melee_hit(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Process a melee hit (light or heavy)."""
        t = event.time
        cid = event.combatant
        source = event.source

        if source == "heavy_melee":
            raw = actor.attack.heavy_melee_damage
        else:
            raw = actor.attack.light_melee_damage

        resist = opponent.defense.effective_bullet_resist(t)
        damage_amp = opponent.defense.effective_damage_amp(t)
        final = raw * (1.0 + damage_amp) * (1.0 - resist)

        if final > 0:
            self._apply_damage(t, source, final, "melee", cid, actor, opponent)

    # ── Regen ─────────────────────────────────────────────────

    def _handle_regen_tick(
        self, event: SimEvent, actor: CombatantState, opponent: CombatantState,
    ) -> None:
        """Heal a combatant by their regen amount."""
        t = event.time
        cid = event.combatant

        # The "actor" for regen is the combatant being healed
        target = actor.defense
        if target.hp <= 0:
            return

        heal_reduction = target.effective_heal_reduction(t)
        heal = target.hp_regen * (1.0 - heal_reduction)
        target.hp = min(target.max_hp, target.hp + heal)
        target.cleanup_expired(t)

        if t + 1.0 <= self.settings.duration:
            self._push(t + 1.0, 20, EventType.REGEN_TICK, "regen", combatant=cid)

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
        """Process all events in the queue until sim ends or a combatant dies."""
        max_events = 100_000  # safety cap (doubled for bidirectional)
        processed = 0

        while self.queue and processed < max_events:
            event = heapq.heappop(self.queue)

            if event.time > self.settings.duration:
                break

            if event.event_type == EventType.SIM_END:
                break

            # Resolve actor / opponent
            if event.combatant == "a":
                actor, opponent = self.a, self.b
            else:
                actor, opponent = self.b, self.a

            # Skip damage events if the opponent is already dead
            # (regen is for the actor, so we check the actor for regen)
            if event.event_type == EventType.REGEN_TICK:
                if actor.defense.hp <= 0:
                    continue
            else:
                if opponent.defense.hp <= 0:
                    continue
                # Also skip if the actor is dead (they can't attack)
                if actor.defense.hp <= 0:
                    continue

            handler_name = self._DISPATCH.get(event.event_type)
            if handler_name:
                handler = getattr(self, handler_name)
                handler(event, actor, opponent)

            processed += 1

    # ── Result builder ────────────────────────────────────────

    def _aggregate_side(
        self, cid: str, actor: CombatantState, opponent: CombatantState,
    ) -> dict:
        """Aggregate timeline entries for one combatant's side."""
        total_damage = 0.0
        bullet_damage = 0.0
        spirit_damage = 0.0
        melee_damage = 0.0
        damage_by_source: dict[str, float] = {}

        for entry in self.timeline:
            if entry.combatant != cid:
                continue
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

        return {
            "total_damage": total_damage,
            "bullet_damage": bullet_damage,
            "spirit_damage": spirit_damage,
            "melee_damage": melee_damage,
            "damage_by_source": damage_by_source,
        }

    def _find_kill_time(self, cid: str, effective_hp: float) -> float | None:
        """Find the time at which a combatant's damage killed the target.

        *effective_hp* should include shields so the kill threshold
        accounts for all damage that must be dealt before HP reaches zero.
        """
        running = 0.0
        for entry in self.timeline:
            if entry.combatant != cid:
                continue
            running += entry.damage
            if running >= effective_hp:
                return entry.time
        return None

    @staticmethod
    def _initial_effective_hp(defense: TargetState) -> float:
        """Return total HP pool including shields at the start of combat."""
        return defense.max_hp + defense.bullet_shield + defense.spirit_shield

    def _build_result(self) -> SimResult:
        """Aggregate timeline into SimResult."""
        bidirectional = self.settings.bidirectional

        # Attacker (A) perspective
        a_data = self._aggregate_side("a", self.a, self.b)
        a_kill_time = self._find_kill_time("a", self._b_effective_hp)

        # Defender (B) perspective (for bidirectional)
        b_data = self._aggregate_side("b", self.b, self.a) if bidirectional else None
        b_kill_time = self._find_kill_time("b", self._a_effective_hp) if bidirectional else None

        # Determine effective duration: min(first_death, configured_duration)
        duration = self.settings.duration
        first_death = duration
        if a_kill_time is not None:
            first_death = min(first_death, a_kill_time)
        if b_kill_time is not None:
            first_death = min(first_death, b_kill_time)
        duration = max(0.01, first_death)

        # Determine winner
        winner = None
        if bidirectional:
            if a_kill_time is not None and (b_kill_time is None or a_kill_time <= b_kill_time):
                winner = "a"
            elif b_kill_time is not None and (a_kill_time is None or b_kill_time < a_kill_time):
                winner = "b"

        # A totals
        a_total = a_data["total_damage"]
        a_dps = a_total / duration if duration > 0 else 0.0
        a_dps_by_source = {
            src: dmg / duration for src, dmg in a_data["damage_by_source"].items()
        } if duration > 0 else {}

        result = SimResult(
            timeline=self.timeline,
            total_damage=a_total,
            total_duration=duration,
            overall_dps=a_dps,
            damage_by_source=a_data["damage_by_source"],
            dps_by_source=a_dps_by_source,
            bullet_damage=a_data["bullet_damage"],
            spirit_damage=a_data["spirit_damage"],
            melee_damage=a_data["melee_damage"],
            bullets_fired=self.a.bullets_fired,
            headshots=self.a.headshots,
            reloads=self.a.reloads,
            procs_triggered=dict(self.a.procs),
            kill_time=a_kill_time,
            target_hp_remaining=max(0.0, self.b.defense.hp),
        )

        # Bidirectional fields
        if bidirectional and b_data is not None:
            b_total = b_data["total_damage"]
            b_dps = b_total / duration if duration > 0 else 0.0
            b_dps_by_source = {
                src: dmg / duration for src, dmg in b_data["damage_by_source"].items()
            } if duration > 0 else {}

            result.defender_total_damage = b_total
            result.defender_dps = b_dps
            result.defender_damage_by_source = b_data["damage_by_source"]
            result.defender_dps_by_source = b_dps_by_source
            result.defender_bullet_damage = b_data["bullet_damage"]
            result.defender_spirit_damage = b_data["spirit_damage"]
            result.defender_melee_damage = b_data["melee_damage"]
            result.defender_bullets_fired = self.b.bullets_fired
            result.defender_headshots = self.b.headshots
            result.defender_reloads = self.b.reloads
            result.defender_procs_triggered = dict(self.b.procs)
            result.defender_kill_time = b_kill_time
            result.attacker_hp_remaining = max(0.0, self.a.defense.hp)
            result.winner = winner

        return result
