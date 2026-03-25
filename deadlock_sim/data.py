"""Data loading from the API cache.

Hero and item data comes exclusively from the Deadlock Assets API
(assets.deadlock-api.com), cached locally under data/api_cache/.

Run ``api_client.refresh_all_data()`` (or click Refresh in the GUI) to
populate or update the local cache.
"""

from __future__ import annotations

from pathlib import Path

from .api_client import is_cache_available, load_cache
from .models import (
    AbilityUpgrade,
    HeroAbility,
    HeroStats,
    Item,
    ShopTier,
)

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

# ── Shop tier bonuses ──────────────────────────────────────────────
# Bonus stats granted for total spend in each category.
# Source: in-game shop tier system (game constants).

_SHOP_TIER_DATA: list[tuple[int, int, int, int]] = [
    # (cost, weapon_bonus, vitality_bonus, spirit_bonus)
    (800,   7,   8,  7),
    (1600,  9,  10, 11),
    (2400, 13,  13, 15),
    (3200, 20,  17, 19),
    (4800, 29,  22, 25),
    (7200, 40,  27, 32),
    (9600, 60,  32, 44),
    (16000, 75, 36, 56),
    (22400, 95, 40, 69),
    (28800, 115, 44, 81),
]


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
        cycle_time=cycle_time,
    )


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

        scale_fn = prop.get("scale_function")
        if scale_fn and isinstance(scale_fn, dict):
            stat_scale = scale_fn.get("stat_scale")
            if stat_scale is not None:
                try:
                    spirit_scaling = float(stat_scale)
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
        # Prefer human-readable description from the description dict
        upg_desc = tier_descs.get(tier, "")
        # Fall back to the upgrade's own description field
        if not upg_desc:
            upg_desc = upg.get("description", "") or ""
        # Last resort: build from property_upgrades
        if not upg_desc:
            parts = []
            for pu in upg.get("property_upgrades", []):
                pname = pu.get("name", "")
                bonus = pu.get("bonus", "")
                if pname and bonus != "":
                    parts.append(f"{pname}: {bonus}")
            upg_desc = ", ".join(parts)
        if upg_desc:
            upgrades.append(AbilityUpgrade(tier=tier, description=upg_desc))

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
            try:
                fval = float(val)
                if mapped == "ammo_flat":
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


# ── Public API ─────────────────────────────────────────────────────


def load_heroes() -> dict[str, HeroStats]:
    """Load heroes from the API cache.

    Raises RuntimeError if no cache is available. Run
    ``api_client.refresh_all_data()`` first, or use
    ``api_client.ensure_data_available()`` to auto-fetch.
    """
    if not is_cache_available():
        raise RuntimeError(
            "No API cache found. Run api_client.refresh_all_data() to fetch data."
        )

    heroes_data = load_cache("heroes")
    hero_items_data = load_cache("hero_items")
    weapons_data = load_cache("weapons")

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

    return heroes


def load_items() -> dict[str, Item]:
    """Load shop upgrade items from the API cache.

    Raises RuntimeError if no cache is available.
    """
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
