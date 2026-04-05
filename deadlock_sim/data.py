"""Data loading from the API cache.

Hero and item data comes exclusively from the Deadlock Assets API
(assets.deadlock-api.com), cached locally under data/api_cache/.

Run ``api_client.refresh_all_data()`` (or click Refresh in the GUI) to
populate or update the local cache.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .api_client import is_cache_available, load_cache
from .models import (
    AbilityUpgrade,
    HeroAbility,
    HeroStats,
    Item,
    ShopTier,
)

log = logging.getLogger(__name__)


# ── Structured parse warnings ─────────────────────────────────────


@dataclass
class ParseWarning:
    """A recoverable issue encountered while parsing API data."""

    entity: str = ""       # e.g. "hero:Haze" or "item:Toxic Bullets"
    field: str = ""        # e.g. "base_bullet_damage"
    message: str = ""      # human-readable description


@dataclass
class ParseResult:
    """Container for parsed data with warnings."""

    heroes: dict[str, HeroStats] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    warnings: list[ParseWarning] = field(default_factory=list)

# ── Property name mapping from API to our stat fields ──────────────

_UPGRADE_PROP_MAP = {
    # Weapon
    "BonusWeaponPower": "weapon_damage_pct",
    "BaseAttackDamagePercent": "weapon_damage_pct",
    "BonusFireRate": "fire_rate_pct",
    # Ammo
    "BonusClipSize": "ammo_flat",
    "BonusClipSizePercent": "ammo_pct",
    # Resist
    "BulletResist": "bullet_resist_pct",
    "BonusBulletArmorDamageReduction": "bullet_resist_pct",
    "TechResist": "spirit_resist_pct",
    "BonusTechArmorDamageReduction": "spirit_resist_pct",
    # Health
    "BonusHealth": "bonus_hp",
    # Spirit
    "TechPower": "spirit_power",
    "SpiritPower": "spirit_power",
    "BonusSpirit": "spirit_power",
    "BonusTechPower": "spirit_power",
    # Spirit Power % (multiplier on total spirit)
    "TechPowerPercent": "spirit_power_pct",
    # Lifesteal
    "BulletLifestealPercent": "bullet_lifesteal",
    "BonusBulletLifesteal": "bullet_lifesteal",
    "AbilityLifestealPercentHero": "spirit_lifesteal",
    "AbilityLifestealPercentHeroPassive": "spirit_lifesteal",
    "BonusTechLifesteal": "spirit_lifesteal",
    # Regen
    "BonusHealthRegen": "hp_regen",
    # Movement
    "BonusMoveSpeed": "move_speed",
    "BonusSprintSpeed": "sprint_speed",
    # Shields/barriers
    "BonusBulletShieldHealth": "bullet_shield",
    "CombatBarrier": "bullet_shield",
    "BonusTechShieldHealth": "spirit_shield",
    # Headshot
    "HeadShotBonusDamage": "headshot_bonus",
    # Shred (API values are negative; negated during parsing)
    "BulletArmorReduction": "bullet_resist_shred",
    "BonusBulletArmorReduction": "bullet_resist_shred",
    "BulletResistReduction": "bullet_resist_shred",
    "BonusTechArmorReduction": "spirit_resist_shred",
    "MagicResistReduction": "spirit_resist_shred",
    "TechArmorDamageReduction": "spirit_resist_shred",
    # Cooldown
    "CooldownReduction": "cooldown_reduction",
    "AbilityCooldownReduction": "cooldown_reduction",
    "TechCooldownReduction": "cooldown_reduction",
    "ItemCooldownReduction": "item_cooldown_reduction",
    # Spirit Amp
    "BonusSpiritAmp": "spirit_amp_pct",
    # Melee
    "BonusMeleeDamagePercent": "melee_damage_pct",
    "BonusHeavyMeleeDamage": "heavy_melee_damage_pct",
}

# Fields that are percentages in the API (whole numbers) but stored as fractions
_PCT_FIELDS = {
    "weapon_damage_pct", "fire_rate_pct", "ammo_pct",
    "bullet_resist_pct", "spirit_resist_pct",
    "bullet_lifesteal", "spirit_lifesteal",
    "cooldown_reduction", "item_cooldown_reduction", "spirit_amp_pct",
    "bullet_resist_shred", "spirit_resist_shred", "spirit_power_pct",
    "melee_damage_pct", "heavy_melee_damage_pct",
}

# API properties whose values must be negated (shred stored as negative in API)
_NEGATE_PROPS = {
    "BulletArmorReduction", "BonusBulletArmorReduction", "BulletResistReduction",
    "BonusTechArmorReduction", "MagicResistReduction", "TechArmorDamageReduction",
}

# Slot type from API -> our category name
_SLOT_TYPE_MAP = {
    "weapon": "weapon",
    "spirit": "spirit",
    "vitality": "vitality",
}

# ── Shop tier bonuses ──────────────────────────────────────────────
# Bonus stats granted for total spend in each category.
# Source: in-game shop tier system (game constants).

_SHOP_TIER_DATA: list[tuple[int, int, int, int]] = [
    # (cost, weapon_bonus, vitality_bonus, spirit_bonus)
    (800,   7,   8,  7),
    (1600,  9,  10, 11),
    (2400, 13,  13, 15),
    (3200, 20,  17, 19),
    (4800, 49,  34, 38),
    (7200, 60,  39, 48),
    (9600, 80,  44, 57),
    (16000, 95, 48, 66),
    (22400, 115, 52, 75),
    (28800, 135, 56, 100),
]

# ── Soul level thresholds ──────────────────────────────────────────
# Maps total gathered souls to (cumulative_boons, cumulative_ability_points).
# Source: https://deadlock.wiki/Leveling_Up

_SOUL_LEVEL_TABLE: list[tuple[int, int, int]] = [
    # (threshold_souls, cumulative_boons, cumulative_ability_points)
    (600,   0,  0),   # Level 0 — ability unlock only
    (900,   1,  1),
    (1200,  2,  1),   # ability unlock
    (1500,  3,  2),
    (2100,  4,  2),   # ability unlock
    (2800,  5,  3),
    (3600,  6,  3),   # ability unlock (ultimate)
    (4400,  7,  4),
    (5200,  8,  5),
    (6000,  9,  6),
    (6800, 10,  7),
    (7700, 11,  8),
    (8600, 12,  9),
    (9600, 13, 10),
    (10600, 14, 11),
    (11600, 15, 12),
    (12600, 16, 13),
    (13800, 17, 14),
    (15600, 18, 15),
    (17600, 19, 16),
    (19600, 20, 17),
    (21600, 21, 18),
    (23600, 22, 19),
    (25600, 23, 20),
    (27600, 24, 21),
    (29600, 25, 22),
    (31600, 26, 23),
    (33600, 27, 24),
    (35600, 28, 25),
    (37600, 29, 26),
    (39600, 30, 27),
    (41600, 31, 28),
    (43600, 32, 29),
    (45600, 33, 30),
    (47600, 34, 31),
    (49600, 35, 32),
]

# Ability point costs per upgrade tier
ABILITY_TIER_COSTS: list[int] = [1, 2, 5]  # T1, T2, T3


def souls_to_boons(total_souls: int) -> int:
    """Return cumulative boon count for a given soul total."""
    result = 0
    for threshold, boons, _ap in _SOUL_LEVEL_TABLE:
        if total_souls >= threshold:
            result = boons
        else:
            break
    return result


def souls_to_ability_points(total_souls: int) -> int:
    """Return cumulative ability points for a given soul total."""
    result = 0
    for threshold, _boons, ap in _SOUL_LEVEL_TABLE:
        if total_souls >= threshold:
            result = ap
        else:
            break
    return result


# ── Per-hero crit bonus scale overrides ────────────────────────────
# Wiki-documented crit bonus scale reductions. Default is 1.65x.
# Formula: Crit Multiplier = 1 + 0.65 × Crit Bonus Scale
# Heroes listed here have reduced scale; Graves cannot crit (1.0x = no bonus).
# Source: https://deadlock.wiki/Weapon_Damage#Crit_Multiplier
_CRIT_BONUS_OVERRIDES: dict[str, float] = {
    "Billy":        1.0 + 0.65 * 0.80,   # -20% → 1.52
    "Celeste":      1.0 + 0.65 * 0.75,   # -25% → 1.4875
    "The Doorman":  1.0 + 0.65 * 0.75,   # -25% → 1.4875
    "Drifter":      1.0 + 0.65 * 0.55,   # -45% → 1.3575
    "Kelvin":       1.0 + 0.65 * 0.75,   # -25% → 1.4875
    "Rem":          1.0 + 0.65 * 0.80,   # -20% → 1.52
    "Vyper":        1.0 + 0.65 * 0.70,   # -30% → 1.455
    "Graves":       1.0,                  # cannot crit
}

# Per-target pellet cap overrides. Most multi-pellet heroes land all pellets
# on a single target. Heroes listed here spread pellets across targets.
_PELLET_CAP_OVERRIDES: dict[str, int] = {
    "Drifter": 1,  # 3 pellets but max 1 per target
}


# ── API parsing ────────────────────────────────────────────────────


def _parse_hero_from_api(
    hero_data: dict,
    hero_items: dict | None = None,
    weapons_list: list | None = None,
) -> HeroStats:
    """Parse a hero from the API JSON into HeroStats."""
    name = hero_data.get("name", "Unknown")

    # Images
    images = hero_data.get("images", {})
    icon_url = images.get("icon_hero_card_webp") or images.get("icon_hero_card", "")
    hero_card_url = images.get("top_bar_vertical_image_webp") or images.get("top_bar_vertical_image", "")
    minimap_url = images.get("minimap_image_webp") or images.get("minimap_image", "")

    # Description
    desc = hero_data.get("description", {})

    # Starting stats
    starting = hero_data.get("starting_stats", {})

    def _stat_val(key: str, default=0.0):
        s = starting.get(key, {})
        if isinstance(s, dict):
            return s.get("value", default)
        return default

    base_hp = _stat_val("max_health")
    base_regen = _stat_val("base_health_regen")
    base_move_speed = _stat_val("max_move_speed")
    base_sprint = _stat_val("sprint_speed")
    base_stamina = int(_stat_val("stamina", 0))
    light_melee = _stat_val("light_melee_damage")
    heavy_melee = _stat_val("heavy_melee_damage")

    # Primary weapon class reference
    items_map = hero_data.get("items", {})
    weapon_class = items_map.get("weapon_primary", "") if items_map else ""

    # Weapon stats from per-hero items
    base_bullet_damage = 0.0
    pellets = 1
    base_ammo = 0
    fire_rate = 0.0
    falloff_start = 0.0
    falloff_end = 0.0
    reload_dur = 0.0
    cycle_time = 0.0
    can_zoom = False
    crit_bonus_start = 1.65

    # Look for weapon in hero_items first, then weapons_list
    weapon_sources: list[dict] = []
    if hero_items:
        hero_id_str = str(hero_data.get("id", ""))
        h_items = hero_items.get(hero_id_str, [])
        weapon_sources.extend(
            item for item in h_items
            if item.get("type") == "weapon" and item.get("class_name") == weapon_class
        )
    if not weapon_sources and weapons_list and weapon_class:
        weapon_sources.extend(
            w for w in weapons_list
            if w.get("class_name") == weapon_class
        )
    for item in weapon_sources:
        wi = item.get("weapon_info", {})
        if wi:
            base_bullet_damage = wi.get("bullet_damage", 0.0) or 0.0
            pellets = wi.get("bullets", 1) or 1
            base_ammo = wi.get("clip_size", 0) or 0
            cycle_time = wi.get("cycle_time", 0.0) or 0.0
            if cycle_time > 0:
                fire_rate = 1.0 / cycle_time
            falloff_start = wi.get("damage_falloff_start_range", 0.0) or 0.0
            falloff_end = wi.get("damage_falloff_end_range", 0.0) or 0.0
            reload_dur = wi.get("reload_duration", 0.0) or 0.0
            can_zoom = wi.get("can_zoom", False) or False
            crit_bonus_start = wi.get("crit_bonus_start", 1.65) or 1.65
        break

    base_dps = base_bullet_damage * pellets * fire_rate
    base_dpm = base_bullet_damage * pellets * base_ammo

    # Per-boon scaling
    level_ups = hero_data.get("standard_level_up_upgrades", {})
    # Try both short and long key formats
    damage_gain = (
        level_ups.get("EBulletDamage", 0.0)
        or level_ups.get("MODIFIER_VALUE_BASE_BULLET_DAMAGE_FROM_LEVEL", 0.0)
        or 0.0
    )
    hp_gain = (
        level_ups.get("EMaxHealth", 0.0)
        or level_ups.get("MODIFIER_VALUE_BASE_HEALTH_FROM_LEVEL", 0.0)
        or 0.0
    )
    spirit_gain = (
        level_ups.get("EAbilityPoint", 0.0)
        or level_ups.get("MODIFIER_VALUE_TECH_POWER", 0.0)
        or 0.0
    )

    # Max-level projections (assuming ~48 boons at max level)
    max_boons = 48
    max_level_hp = base_hp + hp_gain * max_boons
    max_gun_damage = base_bullet_damage * (1 + damage_gain * max_boons)
    max_gun_dps = max_gun_damage * pellets * fire_rate

    # Abilities from per-hero items
    abilities = []
    if hero_items:
        hero_id_str = str(hero_data.get("id", ""))
        h_items = hero_items.get(hero_id_str, [])
        for item in h_items:
            if item.get("type") == "ability":
                abilities.append(_parse_ability(item))

    return HeroStats(
        name=name,
        hero_id=hero_data.get("id", 0),
        class_name=hero_data.get("class_name", ""),
        base_bullet_damage=base_bullet_damage,
        pellets=pellets,
        base_ammo=base_ammo,
        base_fire_rate=fire_rate,
        base_dps=base_dps,
        base_dpm=base_dpm,
        falloff_range_min=falloff_start,
        falloff_range_max=falloff_end,
        alt_fire_type="zoom" if can_zoom else "",
        alt_fire_pellets=1,
        light_melee_damage=light_melee,
        heavy_melee_damage=heavy_melee,
        hero_labs=hero_data.get("in_development", False) or hero_data.get("needs_testing", False),
        base_hp=base_hp,
        base_regen=base_regen,
        base_move_speed=base_move_speed,
        base_sprint=base_sprint,
        base_stamina=base_stamina,
        damage_gain=damage_gain,
        hp_gain=hp_gain,
        spirit_gain=spirit_gain,
        max_level_hp=max_level_hp,
        max_gun_damage=max_gun_damage,
        max_gun_dps=max_gun_dps,
        icon_url=icon_url,
        hero_card_url=hero_card_url,
        minimap_url=minimap_url,
        lore=desc.get("lore", "") or "" if isinstance(desc, dict) else "",
        role=desc.get("role", "") or "" if isinstance(desc, dict) else "",
        playstyle=desc.get("playstyle", "") or "" if isinstance(desc, dict) else "",
        abilities=abilities,
        weapon_class_name=weapon_class,
        reload_duration=reload_dur,
        crit_bonus_start=_CRIT_BONUS_OVERRIDES.get(name, crit_bonus_start),
        cycle_time=cycle_time,
        max_pellets_per_target=_PELLET_CAP_OVERRIDES.get(name, 0),
    )


def _parse_melee_scale(props: dict) -> float:
    """Extract melee damage scale factor from ability properties.

    Returns the fraction of light melee damage this ability uses as its base.
    0.0 means normal (non-melee-scaled) ability.
    """
    # LightMeleeScalePct: e.g. 40 → 0.4
    scale_pct = props.get("LightMeleeScalePct")
    if isinstance(scale_pct, dict):
        val = scale_pct.get("value")
        if val is not None:
            try:
                return float(val) / 100.0
            except (ValueError, TypeError):
                pass

    # LightMeleeScale: e.g. 70 → 0.7
    scale = props.get("LightMeleeScale")
    if isinstance(scale, dict):
        val = scale.get("value")
        if val is not None:
            try:
                return float(val) / 100.0
            except (ValueError, TypeError):
                pass

    # CountsAsLightMelee: 1 means the ability deals 1.0× light melee damage
    counts = props.get("CountsAsLightMelee")
    if isinstance(counts, dict):
        val = counts.get("value")
        if val is not None:
            try:
                if float(val) >= 1:
                    return 1.0
            except (ValueError, TypeError):
                pass

    return 0.0


def _parse_ability(item_data: dict) -> HeroAbility:
    """Parse an ability from the API item data."""
    desc = item_data.get("description", {})
    desc_text = ""
    if isinstance(desc, dict):
        desc_text = desc.get("desc", "") or desc.get("active", "") or desc.get("passive", "") or ""

    image_url = item_data.get("image_webp") or item_data.get("image", "")

    props = item_data.get("properties", {}) or {}
    base_damage = 0.0
    cooldown = 0.0
    duration = 0.0
    spirit_scaling = 0.0
    is_dps = False

    # Priority-ordered keys that indicate ability damage output
    _ABILITY_DAMAGE_KEYS = [
        "AbilityDamage",
        "Damage",
        "DPS",
        "DamagePerSecond",
        "DamagePerProjectile",
        "DamagePerRocket",
        "ExplodeDamage",
        "StompDamage",
        "TurretDPS",
        "SummonDPS",
        "SummonMeleeDamage",
        "BleedDPSPerStack",
        "TechDamage",
        "BulletDamage",
        "BonusDamage",
        "CurrentHealthDamage",
        "MaxHealthDamage",
    ]

    for key, prop in props.items():
        if not isinstance(prop, dict):
            continue
        val = prop.get("value")
        if val is None:
            continue
        try:
            fval = float(val)
        except (ValueError, TypeError):
            continue

        key_lower = key.lower()
        if "cooldown" in key_lower and cooldown == 0:
            cooldown = fval
        elif key in ("AbilityDuration", "AbilityChannelTime") and fval > 0 and duration == 0:
            # Primary duration sources — the ability's own effect window
            duration = fval

        scale_fn = prop.get("scale_function")
        if scale_fn and isinstance(scale_fn, dict):
            stat_scale = scale_fn.get("stat_scale")
            if stat_scale is not None:
                try:
                    spirit_scaling = float(stat_scale)
                except (ValueError, TypeError):
                    pass

    # Extract damage using priority-ordered key list, then fall back to
    # any property containing "damage" in its name
    for dkey in _ABILITY_DAMAGE_KEYS:
        prop = props.get(dkey)
        if isinstance(prop, dict):
            val = prop.get("value")
            if val is not None:
                try:
                    base_damage = float(val)
                    # If this is a DPS property and we have a duration,
                    # convert DPS to total damage. Spirit scaling on DPS
                    # properties also applies per-second, so scale it too.
                    # Example: Flame Dash DPS=30, duration=3, scale=1.0
                    #   base_damage = 30 × 3 = 90
                    #   spirit_scaling = 1.0 × 3 = 3.0
                    # Then: total = 90 + 3.0 × spirit = correct DPS scaling
                    is_dps = "DPS" in dkey
                    if is_dps and duration > 0:
                        base_damage = base_damage * duration
                        if spirit_scaling > 0:
                            spirit_scaling = spirit_scaling * duration
                    break
                except (ValueError, TypeError):
                    pass

    if base_damage == 0:
        # Fallback: scan for any property with "damage" in the name
        for key, prop in props.items():
            if not isinstance(prop, dict):
                continue
            key_lower = key.lower()
            if "damage" in key_lower and "reduction" not in key_lower:
                val = prop.get("value")
                if val is not None:
                    try:
                        base_damage = float(val)
                        break
                    except (ValueError, TypeError):
                        pass

    upgrades = []
    raw_upgrades = item_data.get("upgrades", []) or []

    # Collect human-readable tier descriptions from the description dict
    tier_descs: dict[int, str] = {}
    if isinstance(desc, dict):
        for tier, key in [(1, "t1_desc"), (2, "t2_desc"), (3, "t3_desc")]:
            t_desc = desc.get(key, "")
            if t_desc:
                tier_descs[tier] = t_desc

    for i, upg in enumerate(raw_upgrades):
        if not isinstance(upg, dict):
            continue
        tier = i + 1
        prop_upgrades = upg.get("property_upgrades", []) or []
        # Prefer human-readable description from the description dict
        upg_desc = tier_descs.get(tier, "")
        # Fall back to the upgrade's own description field
        if not upg_desc:
            upg_desc = upg.get("description", "") or ""
        # Last resort: build from property_upgrades
        if not upg_desc:
            parts = []
            for pu in prop_upgrades:
                pname = pu.get("name", "")
                bonus = pu.get("bonus", "")
                if pname and bonus != "":
                    parts.append(f"{pname}: {bonus}")
            upg_desc = ", ".join(parts)
        if upg_desc:
            upgrades.append(AbilityUpgrade(tier=tier, description=upg_desc,
                                           property_upgrades=list(prop_upgrades)))

    # If no upgrades from the array, still try tier descriptions
    if not upgrades:
        for tier in (1, 2, 3):
            if tier in tier_descs:
                upgrades.append(AbilityUpgrade(tier=tier, description=tier_descs[tier]))

    return HeroAbility(
        name=item_data.get("name", ""),
        class_name=item_data.get("class_name", ""),
        ability_type=item_data.get("ability_type", "") or "",
        description=desc_text,
        image_url=image_url,
        cooldown=cooldown,
        duration=duration,
        base_damage=base_damage,
        spirit_scaling=spirit_scaling,
        melee_scale=_parse_melee_scale(props),
        is_dps=is_dps,
        upgrades=upgrades,
        properties=props,
    )


def _parse_upgrade_item(item_data: dict) -> Item | None:
    """Parse a shop upgrade item from API data."""
    if item_data.get("type") != "upgrade":
        return None

    name = item_data.get("name", "")
    slot = item_data.get("item_slot_type", "weapon")
    category = _SLOT_TYPE_MAP.get(slot, "weapon")
    tier = item_data.get("item_tier", 1)
    if isinstance(tier, str):
        try:
            tier = int(tier)
        except ValueError:
            tier = 1

    cost = item_data.get("cost", 0) or 0
    if cost == 0:
        return None

    desc_data = item_data.get("description", {})
    description = ""
    if isinstance(desc_data, dict):
        description = desc_data.get("desc", "") or desc_data.get("active", "") or desc_data.get("passive", "") or ""

    is_active = item_data.get("is_active_item", False)

    image_url = (
        item_data.get("shop_image_small_webp")
        or item_data.get("shop_image_webp")
        or item_data.get("image_webp")
        or item_data.get("image", "")
    )

    props = item_data.get("properties", {}) or {}
    stats: dict[str, float] = {}
    conditional = ""
    raw_properties = {}
    conditional_stats: dict[str, float] = {}

    for key, prop in props.items():
        if not isinstance(prop, dict):
            continue
        val = prop.get("value")
        if val is None:
            continue

        raw_properties[key] = prop

        cond = prop.get("conditional")
        if cond:
            conditional = cond

        mapped = _UPGRADE_PROP_MAP.get(key)
        if mapped:
            is_conditional = "ConditionallyApplied" in (prop.get("usage_flags") or [])
            # For AbilityLifestealPercentHero, skip if the item also has
            # AbilityLifestealPercentHeroPassive (means Hero variant is the active boost)
            if key == "AbilityLifestealPercentHero" and "AbilityLifestealPercentHeroPassive" in props:
                continue
            try:
                fval = float(val)
                if mapped == "ammo_flat":
                    fval = int(fval)
                # Negate shred values (API stores as negative)
                if key in _NEGATE_PROPS:
                    fval = -fval
                # Convert percentage fields from whole numbers to fractions
                if mapped in _PCT_FIELDS:
                    fval /= 100.0
                if is_conditional:
                    conditional_stats[mapped] = conditional_stats.get(mapped, 0) + fval
                else:
                    stats[mapped] = stats.get(mapped, 0) + fval
            except (ValueError, TypeError):
                pass

    activation = item_data.get("activation", "") or ""
    tooltip_sections = item_data.get("tooltip_sections", []) or []

    return Item(
        name=name,
        category=category,
        tier=tier,
        cost=cost,
        item_id=item_data.get("id", 0),
        class_name=item_data.get("class_name", ""),
        image_url=image_url,
        description=description,
        is_active=is_active,
        weapon_damage_pct=stats.get("weapon_damage_pct", 0.0),
        fire_rate_pct=stats.get("fire_rate_pct", 0.0),
        ammo_flat=int(stats.get("ammo_flat", 0)),
        ammo_pct=stats.get("ammo_pct", 0.0),
        bullet_resist_pct=stats.get("bullet_resist_pct", 0.0),
        spirit_resist_pct=stats.get("spirit_resist_pct", 0.0),
        bonus_hp=stats.get("bonus_hp", 0.0),
        spirit_power=stats.get("spirit_power", 0.0),
        bullet_lifesteal=stats.get("bullet_lifesteal", 0.0),
        spirit_lifesteal=stats.get("spirit_lifesteal", 0.0),
        hp_regen=stats.get("hp_regen", 0.0),
        move_speed=stats.get("move_speed", 0.0),
        sprint_speed=stats.get("sprint_speed", 0.0),
        bullet_shield=stats.get("bullet_shield", 0.0),
        spirit_shield=stats.get("spirit_shield", 0.0),
        headshot_bonus=stats.get("headshot_bonus", 0.0),
        bullet_resist_shred=stats.get("bullet_resist_shred", 0.0),
        spirit_resist_shred=stats.get("spirit_resist_shred", 0.0),
        cooldown_reduction=stats.get("cooldown_reduction", 0.0),
        item_cooldown_reduction=stats.get("item_cooldown_reduction", 0.0),
        spirit_amp_pct=stats.get("spirit_amp_pct", 0.0),
        spirit_power_pct=stats.get("spirit_power_pct", 0.0),
        melee_damage_pct=stats.get("melee_damage_pct", 0.0),
        heavy_melee_damage_pct=stats.get("heavy_melee_damage_pct", 0.0),
        condition=conditional,
        conditional_stats=conditional_stats,
        raw_properties=raw_properties,
        activation=activation,
        tooltip_sections=tooltip_sections,
    )


# ── Public API ─────────────────────────────────────────────────────


def load_heroes(
    *,
    heroes_data: list | None = None,
    hero_items_data: dict | None = None,
    weapons_data: list | None = None,
) -> dict[str, HeroStats]:
    """Load heroes from the API cache or from caller-supplied data.

    When any of the ``*_data`` arguments are provided they are used
    directly, skipping the disk cache.  This makes the function fully
    testable without a live API cache.

    Raises RuntimeError if no cache is available *and* no data was
    passed in.
    """
    if heroes_data is None:
        if not is_cache_available():
            raise RuntimeError(
                "No API cache found. Run api_client.refresh_all_data() to fetch data."
            )
        heroes_data = load_cache("heroes")
        hero_items_data = load_cache("hero_items") if hero_items_data is None else hero_items_data
        weapons_data = load_cache("weapons") if weapons_data is None else weapons_data

    if not heroes_data:
        raise RuntimeError("heroes cache is empty or corrupt.")

    weapons_list = weapons_data if isinstance(weapons_data, list) else []

    heroes: dict[str, HeroStats] = {}
    for h in heroes_data:
        if not h.get("player_selectable", True):
            continue
        if h.get("disabled", False) or h.get("in_development", False):
            continue
        hero = _parse_hero_from_api(h, hero_items_data, weapons_list)
        heroes[hero.name] = hero

    log.info("Loaded %d heroes from cache", len(heroes))
    return heroes


def load_items(*, items_data: list | None = None) -> dict[str, Item]:
    """Load shop upgrade items from the API cache or caller-supplied data.

    When ``items_data`` is provided the disk cache is skipped.

    Raises RuntimeError if no cache is available *and* no data was
    passed in.
    """
    if items_data is None:
        if not is_cache_available():
            raise RuntimeError(
                "No API cache found. Run api_client.refresh_all_data() to fetch data."
            )
        items_data = load_cache("items")

    if not items_data:
        raise RuntimeError("items cache is empty or corrupt.")

    items: dict[str, Item] = {}
    for i in items_data:
        if i.get("type") != "upgrade":
            continue
        if not i.get("shopable", False):
            continue
        item = _parse_upgrade_item(i)
        if item and item.cost > 0:
            items[item.name] = item

    # Build upgrades_to reverse index: class_name -> item that uses it as component
    # When multiple items use the same component, pick the lowest-tier upgrade
    class_to_name = {item.class_name: item.name for item in items.values()}
    upgrades_map: dict[str, list[tuple[int, str]]] = {}  # source_name -> [(tier, target_name)]
    for i in items_data:
        if i.get("type") != "upgrade" or not i.get("shopable", False):
            continue
        comp_items = i.get("component_items", []) or []
        target_name = i.get("name", "")
        target_tier = i.get("item_tier", 99)
        if isinstance(target_tier, str):
            try:
                target_tier = int(target_tier)
            except ValueError:
                target_tier = 99
        for comp_class in comp_items:
            source_name = class_to_name.get(comp_class)
            if source_name and source_name in items and target_name in items:
                upgrades_map.setdefault(source_name, []).append((target_tier, target_name))
    for source_name, targets in upgrades_map.items():
        # Pick the lowest-tier target (closest upgrade)
        targets.sort(key=lambda t: t[0])
        items[source_name].upgrades_to = targets[0][1]

    # Build component_names: for each item, resolve its component class_names to item names
    for i in items_data:
        if i.get("type") != "upgrade" or not i.get("shopable", False):
            continue
        target_name = i.get("name", "")
        if target_name not in items:
            continue
        comp_items = i.get("component_items", []) or []
        resolved = [class_to_name[c] for c in comp_items if c in class_to_name and class_to_name[c] in items]
        if resolved:
            items[target_name].component_names = resolved

    log.info("Loaded %d shop items from cache", len(items))
    return items


def load_shop_tiers() -> list[ShopTier]:
    """Return shop bonus tiers (hardcoded game constants)."""
    return [
        ShopTier(cost=cost, weapon_bonus=w, vitality_bonus=v, spirit_bonus=s)
        for cost, w, v, s in _SHOP_TIER_DATA
    ]


def get_hero_names() -> list[str]:
    """Sorted list of hero names from the API cache."""
    return sorted(load_heroes().keys())


def load_all(
    *,
    heroes_data: list | None = None,
    hero_items_data: dict | None = None,
    weapons_data: list | None = None,
    items_data: list | None = None,
) -> ParseResult:
    """Load heroes *and* items in one call, collecting warnings.

    Accepts the same optional data-injection parameters as
    ``load_heroes`` / ``load_items``. Returns a :class:`ParseResult`
    with ``heroes``, ``items``, and any ``warnings`` accumulated during
    parsing.
    """
    warnings: list[ParseWarning] = []
    heroes: dict[str, HeroStats] = {}
    items: dict[str, Item] = {}

    try:
        heroes = load_heroes(
            heroes_data=heroes_data,
            hero_items_data=hero_items_data,
            weapons_data=weapons_data,
        )
    except RuntimeError as exc:
        warnings.append(ParseWarning(entity="heroes", field="", message=str(exc)))

    # Flag heroes with suspicious data
    for name, hero in heroes.items():
        if hero.base_bullet_damage == 0 and hero.base_fire_rate == 0:
            warnings.append(
                ParseWarning(
                    entity=f"hero:{name}",
                    field="weapon",
                    message="Hero has zero bullet damage and fire rate — weapon data may be missing",
                )
            )
        if hero.base_hp == 0:
            warnings.append(
                ParseWarning(
                    entity=f"hero:{name}",
                    field="base_hp",
                    message="Hero has zero base HP",
                )
            )

    try:
        items = load_items(items_data=items_data)
    except RuntimeError as exc:
        warnings.append(ParseWarning(entity="items", field="", message=str(exc)))

    for w in warnings:
        log.warning("Parse: [%s.%s] %s", w.entity, w.field, w.message)

    return ParseResult(heroes=heroes, items=items, warnings=warnings)
