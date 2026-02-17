"""Data loading from API cache or YAML files.

Prefers data from the API cache (data/api_cache/).
Falls back to YAML files in data/heroes/ and data/items/.
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from .api_client import is_cache_available, load_cache
from .models import (
    AbilityUpgrade,
    HeroAbility,
    HeroStats,
    Item,
    ShopTier,
)

# Default paths relative to project root
_DATA_DIR = Path(__file__).parent.parent / "data"
_HEROES_DIR = _DATA_DIR / "heroes"
_ITEMS_DIR = _DATA_DIR / "items"

# ── Property name mapping from API to our stat fields ──────────────


_UPGRADE_PROP_MAP = {
    "BonusWeaponPower": "weapon_damage_pct",
    "BonusFireRate": "fire_rate_pct",
    "BonusClipSize": "ammo_flat",
    "BonusClipSizePercent": "ammo_pct",
    "BonusBulletArmorDamageReduction": "bullet_resist_pct",
    "BonusTechArmorDamageReduction": "spirit_resist_pct",
    "BonusHealth": "bonus_hp",
    "BonusTechPower": "spirit_power",
    "BonusBulletLifesteal": "bullet_lifesteal",
    "BonusTechLifesteal": "spirit_lifesteal",
    "BonusHealthRegen": "hp_regen",
    "BonusMoveSpeed": "move_speed",
    "BonusSprintSpeed": "sprint_speed",
    "BonusBulletShieldHealth": "bullet_shield",
    "BonusTechShieldHealth": "spirit_shield",
    "BonusBulletArmorReduction": "bullet_resist_shred",
    "BonusTechArmorReduction": "spirit_resist_shred",
    "AbilityCooldownReduction": "cooldown_reduction",
    "TechCooldownReduction": "cooldown_reduction",
    "BonusSpiritAmp": "spirit_amp_pct",
}

# Slot type from API -> our category name
_SLOT_TYPE_MAP = {
    "weapon": "weapon",
    "spirit": "spirit",
    "vitality": "vitality",
}


# ── API cache loading ──────────────────────────────────────────────


def _parse_hero_from_api(hero_data: dict, hero_items: dict | None = None) -> HeroStats:
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

    # Weapon info - find the primary weapon from items
    weapon_class = ""
    items_map = hero_data.get("items", {})
    if items_map:
        weapon_class = items_map.get("weapon_primary", "")

    # Get weapon data from hero_items
    base_bullet_damage = 0.0
    pellets = 1
    base_ammo = 0
    fire_rate = 0.0
    falloff_start = 0.0
    falloff_end = 0.0
    reload_dur = 0.0
    cycle_time = 0.0
    can_zoom = False

    if hero_items:
        hero_id_str = str(hero_data.get("id", ""))
        h_items = hero_items.get(hero_id_str, [])
        for item in h_items:
            if item.get("type") == "weapon" and item.get("class_name") == weapon_class:
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
                break

    base_dps = base_bullet_damage * pellets * fire_rate
    base_dpm = base_bullet_damage * pellets * base_ammo

    # Scaling stats
    scaling = hero_data.get("scaling_stats", {})

    def _scale_val(key: str) -> float:
        s = scaling.get(key, {})
        if isinstance(s, dict):
            return s.get("value", 0.0) or 0.0
        return 0.0

    # Standard level up upgrades for scaling
    level_ups = hero_data.get("standard_level_up_upgrades", {})
    damage_gain = level_ups.get("EBulletDamage", 0.0) or 0.0
    hp_gain = level_ups.get("EMaxHealth", 0.0) or 0.0

    # Parse abilities
    abilities = []
    if hero_items:
        hero_id_str = str(hero_data.get("id", ""))
        h_items = hero_items.get(hero_id_str, [])
        for item in h_items:
            if item.get("type") == "ability":
                ability = _parse_ability(item)
                abilities.append(ability)

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
        hero_labs=hero_data.get("in_development", False) or hero_data.get("needs_testing", False),
        base_hp=base_hp,
        base_regen=base_regen,
        base_move_speed=base_move_speed,
        base_sprint=base_sprint,
        base_stamina=base_stamina,
        damage_gain=damage_gain,
        hp_gain=hp_gain,
        spirit_gain=0.0,
        icon_url=icon_url,
        hero_card_url=hero_card_url,
        minimap_url=minimap_url,
        lore=desc.get("lore", "") or "",
        role=desc.get("role", "") or "",
        playstyle=desc.get("playstyle", "") or "",
        abilities=abilities,
        weapon_class_name=weapon_class,
        reload_duration=reload_dur,
        cycle_time=cycle_time,
    )


def _parse_ability(item_data: dict) -> HeroAbility:
    """Parse an ability from the API item data."""
    desc = item_data.get("description", {})
    desc_text = ""
    if isinstance(desc, dict):
        desc_text = desc.get("desc", "") or desc.get("active", "") or desc.get("passive", "") or ""

    image_url = item_data.get("image_webp") or item_data.get("image", "")

    # Parse properties for damage/cooldown/duration
    props = item_data.get("properties", {}) or {}
    base_damage = 0.0
    cooldown = 0.0
    duration = 0.0
    spirit_scaling = 0.0

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
        if "damage" in key_lower and "reduction" not in key_lower and base_damage == 0:
            base_damage = fval
        elif "cooldown" in key_lower and cooldown == 0:
            cooldown = fval
        elif "duration" in key_lower and duration == 0:
            duration = fval

        # Check for spirit scaling via scale_function
        scale_fn = prop.get("scale_function")
        if scale_fn and isinstance(scale_fn, dict):
            stat_scale = scale_fn.get("stat_scale")
            if stat_scale is not None:
                try:
                    spirit_scaling = float(stat_scale)
                except (ValueError, TypeError):
                    pass

    # Parse upgrades
    upgrades = []
    raw_upgrades = item_data.get("upgrades", []) or []
    for i, upg in enumerate(raw_upgrades):
        if isinstance(upg, dict):
            upg_desc = upg.get("description", "") or ""
            upgrades.append(AbilityUpgrade(tier=i + 1, description=upg_desc))

    # Fallback: get T1/T2/T3 from description
    if not upgrades and isinstance(desc, dict):
        for tier, key in [(1, "t1_desc"), (2, "t2_desc"), (3, "t3_desc")]:
            t_desc = desc.get(key, "")
            if t_desc:
                upgrades.append(AbilityUpgrade(tier=tier, description=t_desc))

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
        upgrades=upgrades,
        properties=props,
    )


def _parse_upgrade_item(item_data: dict) -> Item | None:
    """Parse a shop upgrade from API data into our Item model."""
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

    # Parse properties into stat fields
    props = item_data.get("properties", {}) or {}
    stats = {}
    conditional = ""
    raw_properties = {}

    for key, prop in props.items():
        if not isinstance(prop, dict):
            continue
        val = prop.get("value")
        if val is None:
            continue

        raw_properties[key] = prop

        # Check for conditional
        cond = prop.get("conditional")
        if cond:
            conditional = cond

        mapped = _UPGRADE_PROP_MAP.get(key)
        if mapped:
            try:
                fval = float(val)
                # API values: some are percentages stored as whole numbers (e.g. 20 for 20%)
                # Detect and convert: if the value looks like a percentage > 1, convert to decimal
                if mapped in (
                    "weapon_damage_pct", "fire_rate_pct", "ammo_pct",
                    "bullet_resist_pct", "spirit_resist_pct",
                    "bullet_lifesteal", "spirit_lifesteal",
                    "bullet_resist_shred", "spirit_resist_shred",
                    "cooldown_reduction", "spirit_amp_pct",
                ):
                    # API stores these as decimals already (e.g., 0.2 for 20%)
                    pass
                elif mapped == "ammo_flat":
                    fval = int(fval)
                stats[mapped] = stats.get(mapped, 0) + fval
            except (ValueError, TypeError):
                pass

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
        spirit_amp_pct=stats.get("spirit_amp_pct", 0.0),
        condition=conditional,
        raw_properties=raw_properties,
    )


def _load_from_api_cache() -> tuple[dict[str, HeroStats], dict[str, Item]] | None:
    """Try to load data from the API cache. Returns None if unavailable."""
    if not is_cache_available():
        return None

    heroes_data = load_cache("heroes")
    items_data = load_cache("items")
    hero_items_data = load_cache("hero_items")

    if not heroes_data or not items_data:
        return None

    heroes = {}
    for h in heroes_data:
        if not h.get("player_selectable", True):
            continue
        hero = _parse_hero_from_api(h, hero_items_data)
        heroes[hero.name] = hero

    items = {}
    for i in items_data:
        if i.get("type") != "upgrade":
            continue
        item = _parse_upgrade_item(i)
        if item and item.cost > 0:
            items[item.name] = item

    return heroes, items


# ── YAML fallback loading ──────────────────────────────────────────


def _hero_from_yaml(data: dict) -> HeroStats:
    """Convert a parsed YAML dict into a HeroStats instance."""
    gun = data.get("gun", {})
    surv = data.get("survivability", {})
    scale = data.get("scaling", {})

    base_dmg = gun.get("base_bullet_damage", 0.0)
    pellets = gun.get("pellets", 1) or 1
    fire_rate = gun.get("base_fire_rate", 0.0)
    base_ammo = gun.get("base_ammo", 0)

    base_dps = base_dmg * pellets * fire_rate
    base_dpm = base_dmg * pellets * base_ammo

    return HeroStats(
        name=data["name"],
        base_bullet_damage=base_dmg,
        pellets=pellets,
        alt_fire_type=str(gun.get("alt_fire_type", "")),
        alt_fire_pellets=gun.get("alt_fire_pellets", 1) or 1,
        base_ammo=base_ammo,
        base_fire_rate=fire_rate,
        base_dps=base_dps,
        base_dpm=base_dpm,
        falloff_range_min=gun.get("falloff_range_min", 0.0),
        falloff_range_max=gun.get("falloff_range_max", 0.0),
        hero_labs=data.get("hero_labs", False),
        base_hp=surv.get("base_hp", 0.0),
        base_regen=surv.get("base_regen", 0.0),
        base_move_speed=surv.get("base_move_speed", 0.0),
        base_sprint=surv.get("base_sprint", 0.0),
        base_stamina=surv.get("base_stamina", 0),
        damage_gain=scale.get("damage_gain", 0.0),
        hp_gain=scale.get("hp_gain", 0.0),
        spirit_gain=scale.get("spirit_gain", 0.0),
    )


def _load_heroes_yaml(heroes_dir: Path | str | None = None) -> dict[str, HeroStats]:
    heroes_path = Path(heroes_dir) if heroes_dir else _HEROES_DIR
    if not heroes_path.is_dir():
        return {}

    heroes: dict[str, HeroStats] = {}
    for yaml_file in sorted(heroes_path.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if not data or "name" not in data:
            continue
        hero = _hero_from_yaml(data)
        heroes[hero.name] = hero
    return heroes


def _load_items_yaml(items_dir: Path | str | None = None) -> dict[str, Item]:
    items_path = Path(items_dir) if items_dir else _ITEMS_DIR
    catalog_file = items_path / "catalog.yaml"
    if not catalog_file.exists():
        return {}

    with open(catalog_file) as f:
        data = yaml.safe_load(f)

    if not data or "items" not in data:
        return {}

    items: dict[str, Item] = {}
    for entry in data["items"]:
        stats = entry.get("stats", {})
        item = Item(
            name=entry["name"],
            category=entry["category"],
            tier=entry["tier"],
            cost=entry["cost"],
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
            spirit_amp_pct=stats.get("spirit_amp_pct", 0.0),
            condition=entry.get("condition", ""),
        )
        items[item.name] = item
    return items


# ── Public API ─────────────────────────────────────────────────────


def load_heroes(heroes_dir: Path | str | None = None) -> dict[str, HeroStats]:
    """Load heroes. Prefers API cache, falls back to YAML."""
    result = _load_from_api_cache()
    if result is not None:
        heroes, _ = result
        if heroes:
            return heroes
    return _load_heroes_yaml(heroes_dir)


def load_items(items_dir: Path | str | None = None) -> dict[str, Item]:
    """Load items. Prefers API cache, falls back to YAML."""
    result = _load_from_api_cache()
    if result is not None:
        _, items = result
        if items:
            return items
    return _load_items_yaml(items_dir)


def load_shop_tiers(items_dir: Path | str | None = None) -> list[ShopTier]:
    """Load shop tiers from YAML (fallback only)."""
    items_path = Path(items_dir) if items_dir else _ITEMS_DIR

    weapon = _load_tier_yaml(items_path / "weapon.yaml")
    vitality = _load_tier_yaml(items_path / "vitality.yaml")
    spirit = _load_tier_yaml(items_path / "spirit.yaml")

    vit_by_cost = {t["cost"]: t["bonus"] for t in vitality}
    spr_by_cost = {t["cost"]: t["bonus"] for t in spirit}

    tiers = []
    for w in weapon:
        cost = w["cost"]
        tiers.append(ShopTier(
            cost=cost,
            weapon_bonus=w["bonus"],
            vitality_bonus=vit_by_cost.get(cost, 0),
            spirit_bonus=spr_by_cost.get(cost, 0),
        ))
    return tiers


def _load_tier_yaml(filepath: Path) -> list[dict]:
    if not filepath.exists():
        return []
    with open(filepath) as f:
        data = yaml.safe_load(f)
    return data.get("tiers", []) if data else []


def get_hero_names(heroes_dir: Path | str | None = None) -> list[str]:
    """Quick helper to get sorted hero names."""
    heroes = load_heroes(heroes_dir)
    return sorted(heroes.keys())
