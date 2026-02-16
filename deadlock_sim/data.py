"""Data loading from YAML files.

Heroes are stored as individual YAML files in data/heroes/.
Item shop tiers are stored in data/items/{weapon,vitality,spirit}.yaml.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import HeroStats, Item, ShopTier

# Default paths relative to project root
_DATA_DIR = Path(__file__).parent.parent / "data"
_HEROES_DIR = _DATA_DIR / "heroes"
_ITEMS_DIR = _DATA_DIR / "items"


def _hero_from_yaml(data: dict) -> HeroStats:
    """Convert a parsed YAML dict into a HeroStats instance."""
    gun = data.get("gun", {})
    surv = data.get("survivability", {})
    scale = data.get("scaling", {})

    base_dmg = gun.get("base_bullet_damage", 0.0)
    pellets = gun.get("pellets", 1) or 1
    fire_rate = gun.get("base_fire_rate", 0.0)
    base_ammo = gun.get("base_ammo", 0)

    # Compute derived stats from raw values
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
        max_level_hp=0.0,   # computed on the fly from scaling if needed
        max_gun_damage=0.0,
        max_gun_dps=0.0,
    )


def load_heroes(heroes_dir: Path | str | None = None) -> dict[str, HeroStats]:
    """Load all hero YAML files from the heroes directory.

    Returns a dict mapping hero name -> HeroStats.
    """
    heroes_path = Path(heroes_dir) if heroes_dir else _HEROES_DIR

    if not heroes_path.is_dir():
        raise FileNotFoundError(
            f"Heroes data directory not found: {heroes_path}\n"
            f"Expected YAML files in data/heroes/"
        )

    heroes: dict[str, HeroStats] = {}

    for yaml_file in sorted(heroes_path.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        if not data or "name" not in data:
            continue

        hero = _hero_from_yaml(data)
        heroes[hero.name] = hero

    return heroes


def load_shop_tiers(items_dir: Path | str | None = None) -> list[ShopTier]:
    """Load shop tiers from the three item YAML files.

    Combines weapon, vitality, and spirit tiers by matching cost levels.
    """
    items_path = Path(items_dir) if items_dir else _ITEMS_DIR

    weapon = _load_item_yaml(items_path / "weapon.yaml")
    vitality = _load_item_yaml(items_path / "vitality.yaml")
    spirit = _load_item_yaml(items_path / "spirit.yaml")

    # Build lookup by cost
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


def _load_item_yaml(filepath: Path) -> list[dict]:
    """Load tiers from a single item category YAML file."""
    if not filepath.exists():
        return []
    with open(filepath) as f:
        data = yaml.safe_load(f)
    return data.get("tiers", []) if data else []


def load_items(items_dir: Path | str | None = None) -> dict[str, Item]:
    """Load the item catalog from catalog.yaml.

    Returns a dict mapping item name -> Item.
    """
    items_path = Path(items_dir) if items_dir else _ITEMS_DIR
    catalog_file = items_path / "catalog.yaml"

    if not catalog_file.exists():
        raise FileNotFoundError(
            f"Item catalog not found: {catalog_file}\n"
            f"Expected data/items/catalog.yaml"
        )

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


def get_hero_names(heroes_dir: Path | str | None = None) -> list[str]:
    """Quick helper to get sorted hero names."""
    heroes = load_heroes(heroes_dir)
    return sorted(heroes.keys())
