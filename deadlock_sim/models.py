"""Data models for Deadlock heroes, items, and combat state."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AbilityUpgrade:
    """An upgrade tier for a hero ability (T1/T2/T3)."""

    tier: int = 0
    description: str = ""
    property_upgrades: list[dict] = field(default_factory=list)


@dataclass
class HeroAbility:
    """A hero ability with its properties and upgrades."""

    name: str = ""
    class_name: str = ""
    ability_type: str = ""  # innate, signature, ultimate, weapon
    description: str = ""
    image_url: str = ""
    cooldown: float = 0.0
    duration: float = 0.0
    base_damage: float = 0.0
    spirit_scaling: float = 0.0  # spirit power coefficient
    melee_scale: float = 0.0  # fraction of light melee damage used as base (0 = normal ability)
    is_dps: bool = False  # True when base_damage was derived from a DPS property (pre-multiplied by duration)

    # Upgrades (T1, T2, T3 descriptions)
    upgrades: list[AbilityUpgrade] = field(default_factory=list)

    # All raw properties from the API
    properties: dict = field(default_factory=dict)


@dataclass
class HeroScalingStat:
    """A hero-specific stat that scales from another stat (typically spirit power).

    Example: Haze's clip size scales from spirit at 0.5 per point.
    """

    target_stat: str  # human-readable name, e.g. "Clip Size"
    source_stat: str  # human-readable source, e.g. "Spirit Power"
    scale: float  # coefficient, e.g. 0.5


@dataclass
class HeroStats:
    """Base stats for a Deadlock hero, loaded from data."""

    name: str

    # API identifiers
    hero_id: int = 0
    class_name: str = ""

    # Gun stats
    base_bullet_damage: float = 0.0
    pellets: int = 1
    base_ammo: int = 0
    base_fire_rate: float = 0.0
    base_dps: float = 0.0
    base_dpm: float = 0.0
    falloff_range_min: float = 0.0
    falloff_range_max: float = 0.0

    # Alt fire
    alt_fire_type: str = ""
    alt_fire_pellets: int = 1

    # Per-target pellet cap: max pellets that can hit a single target per shot.
    # Most heroes = pellets (all hit one target). Drifter = 1 (spread across targets).
    max_pellets_per_target: int = 0  # 0 = use pellets (no cap)

    # Melee
    light_melee_damage: float = 0.0
    heavy_melee_damage: float = 0.0

    # Survivability
    base_hp: float = 0.0
    base_regen: float = 0.0
    base_move_speed: float = 0.0
    base_sprint: float = 0.0
    base_stamina: int = 0

    # Per-boon scaling
    damage_gain: float = 0.0  # bullet damage gained per boon
    hp_gain: float = 0.0  # HP gained per boon
    spirit_gain: float = 0.0  # spirit gained per boon
    melee_gain: float = 0.0  # melee damage gained per boon
    bullet_resist_gain: float = 0.0  # bullet resist % gained per boon
    spirit_resist_gain: float = 0.0  # spirit resist % gained per boon
    attack_range_gain: float = 0.0  # attack range gained per boon
    alt_fire_damage_gain: float = 0.0  # alt fire damage gained per boon

    # Hero-specific spirit scaling (stats that scale from another stat)
    scaling_stats: list[HeroScalingStat] = field(default_factory=list)

    # Max-level projections
    max_level_hp: float = 0.0
    max_gun_damage: float = 0.0
    max_gun_dps: float = 0.0

    # Hero Labs flag
    hero_labs: bool = False

    # Images from the API
    icon_url: str = ""
    hero_card_url: str = ""
    minimap_url: str = ""

    # Hero description/lore
    lore: str = ""
    role: str = ""
    playstyle: str = ""

    # Abilities
    abilities: list[HeroAbility] = field(default_factory=list)

    # Weapon class name reference
    weapon_class_name: str = ""

    # Reload duration
    reload_duration: float = 0.0

    # Crit bonus scale (derived from weapon crit_bonus_start)
    # Default 1.65 = base headshot multiplier. Heroes with reduced crit
    # have lower values (e.g., Drifter). Graves = 1.0 (cannot crit).
    crit_bonus_start: float = 1.65

    # Cycle time (for DPS calculations)
    cycle_time: float = 0.0


@dataclass
class CombatConfig:
    """Configurable parameters for a damage/TTK simulation."""

    # Attacker state
    boons: int = 0
    weapon_damage_bonus: float = 0.0  # flat % increase to weapon damage
    flat_weapon_bonus: float = 0.0  # flat bonus damage added after % multiplier
    fire_rate_bonus: float = 0.0  # flat % increase to fire rate
    ammo_increase: float = 0.0  # multiplier for extra ammo (1 = doubled)
    ammo_flat: int = 0  # flat bonus ammo from items

    # Shred sources (up to 5 stacking sources)
    shred: list[float] = field(default_factory=list)

    # Spirit
    current_spirit: int = 0
    spirit_amp: float = 0.0

    # Accuracy model
    accuracy: float = 1.0  # 0-1, fraction of shots that land
    headshot_rate: float = 0.0  # 0-1, fraction of hits that are headshots
    headshot_multiplier: float = 1.65  # base weakpoint multiplier (from hero weapon)

    # Defender state
    enemy_bullet_resist: float = 0.0  # 0-1
    enemy_spirit_resist: float = 0.0  # 0-1
    enemy_hp: float = 0.0  # override HP (0 = use hero base)
    enemy_bonus_hp: float = 0.0  # from items

    # Engagement range (meters) — used for damage falloff
    distance: float = 20.0  # 0 = point-blank (no falloff)

    # Target debuffs
    target_bullet_damage_amp: float = 0.0  # e.g. Bebop Grapple +0.20

    # Golden statue bonuses
    golden_buffs_count: int = 0  # total buffs acquired; split evenly by default
    golden_weapon_total: float = 0.0  # override: total weapon % from statues
    golden_spirit_total: float = 0.0  # override: total spirit flat from statues
    golden_vitality_total: float = 0.0  # override: total vitality % from statues

    # Conditional item assumptions (for static what-if analysis)
    berserker_stacks: int = 0  # 0-10, each stack = +7% weapon damage
    intensifying_mag_pct: float = 0.0  # 0.0-0.45, assumed weapon damage bonus
    opening_rounds_active: bool = False  # True = target above 50% HP threshold
    close_range_active: bool = False  # True = within close-range threshold
    long_range_active: bool = False  # True = beyond long-range threshold


@dataclass
class AbilityConfig:
    """Configuration for spirit/ability damage calculation."""

    base_damage: float = 0.0
    spirit_multiplier: float = 0.0
    current_spirit: int = 0

    # Cooldown
    cooldown: float = 0.0

    # Duration for DoT abilities
    ability_duration: float = 0.0
    bonus_duration: float = 0.0

    # Resist/shred applied to spirit damage
    enemy_spirit_resist: float = 0.0
    resist_shred: float = 0.0
    mystic_vuln: float = 0.0
    spirit_amp: float = 0.0

    # Item effects
    escalating_exposure_stacks: int = 0
    ee_per_stack: float = 0.06  # per-stack spirit amp from EE (default 6%)
    crippling: float = 0.0
    soulshredder: float = 0.0


@dataclass
class ShopTier:
    """Shop bonus at a given cost threshold."""

    cost: int
    weapon_bonus: int
    vitality_bonus: int
    spirit_bonus: int


@dataclass
class BulletResult:
    """Output of a bullet damage calculation."""

    damage_per_bullet: float  # single bullet raw damage
    bullets_per_second: float
    raw_dps: float  # before resist (burst, no reload)
    final_dps: float  # after resist/shred (burst, no reload)
    sustained_dps: float  # after resist, including reload downtime
    magazine_size: int
    damage_per_magazine: float
    magdump_time: float  # seconds to empty mag
    reload_time: float  # seconds to reload
    total_shred: float
    final_resist: float


@dataclass
class SpiritResult:
    """Output of a spirit/ability damage calculation."""

    raw_damage: float  # base + spirit scaling
    modified_damage: float  # after resist/amp
    spirit_contribution: float  # the spirit portion alone
    dps: float  # if DoT, damage / duration; if instant, damage / cooldown
    total_dot_damage: float  # if DoT, over full duration


@dataclass
class TTKResult:
    """Output of a time-to-kill calculation."""

    ttk_seconds: float  # ideal TTK
    realistic_ttk: float  # with accuracy factored in
    magazines_needed: int
    can_one_mag: bool
    effective_dps: float  # DPS after resist
    realistic_dps: float  # DPS after accuracy + headshots
    target_hp: float
    damage_per_magazine: float


@dataclass
class MeleeResult:
    """Output of a melee damage calculation."""

    light_damage: float  # per-hit light melee damage after bonuses
    heavy_damage: float  # per-hit heavy melee damage after bonuses
    light_dps: float  # light melee DPS (damage / cycle time)
    heavy_dps: float  # heavy melee DPS (damage / cycle time)


@dataclass
class ItemDamageResult:
    """Output of an individual item's damage calculation."""

    item_name: str
    damage_per_hit: float  # damage per proc/hit/tick
    dps: float  # effective DPS accounting for proc rate / cooldown
    damage_type: str  # "spirit", "bullet", or "melee"
    scaled_from: str  # what stat it scales from: "spirit", "boons", "weapon"
    spirit_contribution: float = 0.0  # portion from spirit scaling
    boon_contribution: float = 0.0  # portion from boon scaling


@dataclass
class AbilityDamageResult:
    """Output of a hero ability damage calculation with boon context."""

    ability_name: str
    raw_damage: float  # base + spirit contribution
    modified_damage: float  # after amp, items, resist
    spirit_contribution: float
    dps: float  # damage / cooldown or damage / duration
    effective_cooldown: float
    boons: int
    current_spirit: float


@dataclass
class ScalingSnapshot:
    """Hero stats at a specific boon level."""

    boon_level: int
    bullet_damage: float
    hp: float
    spirit: float
    dps: float
    dpm: float


@dataclass
class Item:
    """A purchasable Deadlock item with combat-relevant stats."""

    name: str
    category: str  # "weapon", "vitality", "spirit"
    tier: int  # 1-4
    cost: int

    # API identifiers
    item_id: int = 0
    class_name: str = ""
    image_url: str = ""
    description: str = ""
    is_active: bool = False

    # Combat stats (all default to 0 if not present on the item)
    weapon_damage_pct: float = 0.0
    fire_rate_pct: float = 0.0
    ammo_flat: int = 0
    ammo_pct: float = 0.0
    bullet_resist_pct: float = 0.0
    spirit_resist_pct: float = 0.0
    bonus_hp: float = 0.0
    spirit_power: float = 0.0
    bullet_lifesteal: float = 0.0
    spirit_lifesteal: float = 0.0
    hp_regen: float = 0.0
    move_speed: float = 0.0
    sprint_speed: float = 0.0
    bullet_shield: float = 0.0
    spirit_shield: float = 0.0
    headshot_bonus: float = 0.0
    bullet_resist_shred: float = 0.0
    spirit_resist_shred: float = 0.0
    cooldown_reduction: float = 0.0
    item_cooldown_reduction: float = 0.0
    spirit_amp_pct: float = 0.0
    spirit_power_pct: float = 0.0  # % multiplier on total spirit power (e.g. Boundless Spirit)
    melee_damage_pct: float = 0.0
    heavy_melee_damage_pct: float = 0.0

    # Optional condition describing when the stat applies
    condition: str = ""

    # Conditional stats — only active under specific triggers (e.g. on-hit, active use).
    # Keys match the same stat field names (e.g. "spirit_power", "bullet_resist_shred").
    conditional_stats: dict[str, float] = field(default_factory=dict)

    # All raw properties from the API
    raw_properties: dict = field(default_factory=dict)

    # Rich tooltip data from API
    activation: str = ""  # "passive", "press", "toggle", etc.
    tooltip_sections: list = field(default_factory=list)
    upgrades_to: str = ""  # name of the item this upgrades into
    component_names: list[str] = field(default_factory=list)  # names of items this is built from


@dataclass
class Build:
    """A set of items constituting a hero build."""

    items: list[Item] = field(default_factory=list)

    @property
    def total_cost(self) -> int:
        return sum(item.cost for item in self.items)

    @property
    def item_names(self) -> list[str]:
        return [item.name for item in self.items]


@dataclass
class BuildStats:
    """Aggregated combat stats from a build's items."""

    weapon_damage_pct: float = 0.0
    fire_rate_pct: float = 0.0
    ammo_flat: int = 0
    ammo_pct: float = 0.0
    bullet_resist_pct: float = 0.0
    spirit_resist_pct: float = 0.0
    bonus_hp: float = 0.0
    base_hp_pct: float = 0.0  # Vitality shop tier bonus (% multiplier on base+boon HP)
    spirit_power: float = 0.0
    bullet_lifesteal: float = 0.0
    spirit_lifesteal: float = 0.0
    hp_regen: float = 0.0
    bullet_shield: float = 0.0
    spirit_shield: float = 0.0
    headshot_bonus: float = 0.0
    bullet_resist_shred: float = 0.0
    spirit_resist_shred: float = 0.0
    cooldown_reduction: float = 0.0
    item_cooldown_reduction: float = 0.0
    spirit_amp_pct: float = 0.0
    spirit_power_pct: float = 0.0  # % multiplier on total spirit power
    melee_damage_pct: float = 0.0
    heavy_melee_damage_pct: float = 0.0
    total_cost: int = 0
    weapon_cost: int = 0
    vitality_cost: int = 0
    spirit_cost: int = 0


@dataclass
class BuildResult:
    """Result of evaluating a build for a hero."""

    hero_name: str
    build: Build
    build_stats: BuildStats
    bullet_result: BulletResult | None = None
    ttk_result: TTKResult | None = None
    spirit_dps: float = 0.0
    combined_dps: float = 0.0
    effective_hp: float = 0.0
