"""Data loading from the Deadlock Stats Excel spreadsheet."""

from __future__ import annotations

import math
from pathlib import Path

from .models import HeroStats, ShopTier

# Default path relative to project root
DEFAULT_DATA_PATH = Path(__file__).parent.parent / "data" / "Copy of Deadlock Stats.xlsx"

# Column indices in the Heroes sheet (row 4 is the header, 0-indexed in raw data)
_COL = {
    "name": 0,
    "base_bullet_damage": 1,
    "pellets": 2,
    "alt_fire_type": 3,
    "alt_fire_pellets": 4,
    "base_ammo": 5,
    "base_fire_rate": 6,
    "base_dps": 7,
    "base_dpm": 8,
    "falloff_range_min": 9,
    "falloff_range_max": 10,
    "hero_labs": 11,
    "base_hp": 12,
    "base_regen": 13,
    "base_move_speed": 14,
    "base_sprint": 15,
    "base_stamina": 16,
    # 17 = separator "|||"
    "damage_gain": 18,
    "hp_gain": 19,
    "spirit_gain": 20,
    # 21 = separator "|||||||"
    "max_level_hp": 22,
    "max_gun_damage": 23,
    "max_gun_dps": 24,
}

# Shop bonus tiers from the shopBonuses sheet
_SHOP_TIERS = [
    (800, 7, 8, 7),
    (1600, 9, 10, 11),
    (2400, 13, 13, 15),
    (3200, 20, 17, 19),
    (4800, 29, 22, 25),
    (7200, 40, 27, 32),
    (9600, 60, 32, 44),
    (16000, 75, 36, 56),
    (22400, 95, 40, 69),
    (28800, 115, 44, 81),
]


def _safe_float(val, default: float = 0.0) -> float:
    """Convert a value to float, returning default if NaN or non-numeric."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) else f
    except (ValueError, TypeError):
        return default


def _safe_int(val, default: int = 0) -> int:
    """Convert a value to int, returning default if NaN or non-numeric."""
    f = _safe_float(val, float(default))
    return int(f)


def load_heroes(filepath: Path | str | None = None) -> dict[str, HeroStats]:
    """Load hero data from the Excel spreadsheet.

    Returns a dict mapping hero name -> HeroStats.
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError(
            "pandas and openpyxl are required for Excel loading. "
            "Install with: pip install pandas openpyxl"
        )

    filepath = Path(filepath) if filepath else DEFAULT_DATA_PATH
    df = pd.read_excel(filepath, sheet_name="Heroes", header=None)

    heroes: dict[str, HeroStats] = {}

    # Hero data starts at row index 7 (0-indexed) in the raw DataFrame
    # Row 4 (index 4) is the header row with column names
    # Rows 5-6 are Celeste/Apollo (incomplete data, hero labs)
    # Rows 7+ are the full hero entries
    for i in range(5, len(df)):
        row = df.iloc[i].tolist()
        name = row[_COL["name"]]

        if not isinstance(name, str) or not name.strip():
            continue

        name = name.strip()
        base_dmg = _safe_float(row[_COL["base_bullet_damage"]])
        pellets = _safe_int(row[_COL["pellets"]], 1)
        fire_rate = _safe_float(row[_COL["base_fire_rate"]])

        hero = HeroStats(
            name=name,
            base_bullet_damage=base_dmg,
            pellets=pellets if pellets > 0 else 1,
            alt_fire_type=str(row[_COL["alt_fire_type"]]) if not isinstance(row[_COL["alt_fire_type"]], float) or not math.isnan(row[_COL["alt_fire_type"]]) else "",
            alt_fire_pellets=_safe_int(row[_COL["alt_fire_pellets"]], 1),
            base_ammo=_safe_int(row[_COL["base_ammo"]]),
            base_fire_rate=fire_rate,
            base_dps=_safe_float(row[_COL["base_dps"]]),
            base_dpm=_safe_float(row[_COL["base_dpm"]]),
            falloff_range_min=_safe_float(row[_COL["falloff_range_min"]]),
            falloff_range_max=_safe_float(row[_COL["falloff_range_max"]]),
            hero_labs=str(row[_COL["hero_labs"]]).strip().lower() in ("x", "e"),
            base_hp=_safe_float(row[_COL["base_hp"]]),
            base_regen=_safe_float(row[_COL["base_regen"]]),
            base_move_speed=_safe_float(row[_COL["base_move_speed"]]),
            base_sprint=_safe_float(row[_COL["base_sprint"]]),
            base_stamina=_safe_int(row[_COL["base_stamina"]]),
            damage_gain=_safe_float(row[_COL["damage_gain"]]),
            hp_gain=_safe_float(row[_COL["hp_gain"]]),
            spirit_gain=_safe_float(row[_COL["spirit_gain"]]),
            max_level_hp=_safe_float(row[_COL["max_level_hp"]]),
            max_gun_damage=_safe_float(row[_COL["max_gun_damage"]]),
            max_gun_dps=_safe_float(row[_COL["max_gun_dps"]]),
        )

        heroes[name] = hero

    return heroes


def load_shop_tiers() -> list[ShopTier]:
    """Return the hardcoded shop bonus tiers."""
    return [
        ShopTier(cost=c, weapon_bonus=w, vitality_bonus=v, spirit_bonus=s)
        for c, w, v, s in _SHOP_TIERS
    ]


def get_hero_names(filepath: Path | str | None = None) -> list[str]:
    """Quick helper to get sorted hero names."""
    heroes = load_heroes(filepath)
    return sorted(heroes.keys())
