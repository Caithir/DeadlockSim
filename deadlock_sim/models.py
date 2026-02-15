"""Data models for Deadlock heroes, items, and combat state."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HeroStats:
    """Base stats for a Deadlock hero, loaded from data."""

    name: str

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

    # Max-level projections
    max_level_hp: float = 0.0
    max_gun_damage: float = 0.0
    max_gun_dps: float = 0.0

    # Hero Labs flag
    hero_labs: bool = False


@dataclass
class CombatConfig:
    """Configurable parameters for a damage/TTK simulation."""

    # Attacker state
    boons: int = 0
    weapon_damage_bonus: float = 0.0  # flat % increase to weapon damage
    fire_rate_bonus: float = 0.0  # flat % increase to fire rate
    ammo_increase: float = 0.0  # multiplier for extra ammo (1 = doubled)

    # Shred sources (up to 5 stacking sources)
    shred: list[float] = field(default_factory=list)

    # Spirit
    current_spirit: int = 0
    spirit_amp: float = 0.0

    # Accuracy model
    accuracy: float = 1.0  # 0-1, fraction of shots that land
    headshot_rate: float = 0.0  # 0-1, fraction of hits that are headshots
    headshot_multiplier: float = 1.5  # default headshot bonus

    # Defender state
    enemy_bullet_resist: float = 0.0  # 0-1
    enemy_spirit_resist: float = 0.0  # 0-1
    enemy_hp: float = 0.0  # override HP (0 = use hero base)
    enemy_bonus_hp: float = 0.0  # from items


@dataclass
class AbilityConfig:
    """Configuration for spirit/ability damage calculation."""

    base_damage: float = 0.0
    spirit_multiplier: float = 0.0
    current_spirit: int = 0

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
    raw_dps: float  # before resist
    final_dps: float  # after resist/shred
    magazine_size: int
    damage_per_magazine: float
    magdump_time: float  # seconds to empty mag
    total_shred: float
    final_resist: float


@dataclass
class SpiritResult:
    """Output of a spirit/ability damage calculation."""

    raw_damage: float  # base + spirit scaling
    modified_damage: float  # after resist/amp
    spirit_contribution: float  # the spirit portion alone
    dps: float  # if DoT, damage / duration
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
class ScalingSnapshot:
    """Hero stats at a specific boon level."""

    boon_level: int
    bullet_damage: float
    hp: float
    spirit: float
    dps: float
    dpm: float
