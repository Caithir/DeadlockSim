"""Boon/level scaling calculations.

Computes how hero stats evolve across boon levels.
"""

from __future__ import annotations

from ..models import HeroStats, ScalingSnapshot
from .damage import DamageCalculator


class ScalingCalculator:
    """Calculate hero stat progression across boon levels."""

    @staticmethod
    def snapshot_at_boon(hero: HeroStats, boon_level: int) -> ScalingSnapshot:
        """Get a hero's stats at a specific boon level."""
        bullet_dmg = DamageCalculator.bullet_damage_at_boon(hero, boon_level)
        hp = hero.base_hp + (hero.hp_gain * boon_level)
        spirit = hero.spirit_gain * boon_level

        # DPS = damage_per_bullet * pellets * fire_rate
        per_bullet = bullet_dmg * hero.pellets
        dps = per_bullet * hero.base_fire_rate

        # DPM = damage_per_bullet * pellets * magazine_size
        dpm = per_bullet * hero.base_ammo

        return ScalingSnapshot(
            boon_level=boon_level,
            bullet_damage=bullet_dmg,
            hp=hp,
            spirit=spirit,
            dps=dps,
            dpm=dpm,
        )

    @classmethod
    def scaling_curve(
        cls,
        hero: HeroStats,
        max_boons: int = 35,
    ) -> list[ScalingSnapshot]:
        """Generate full scaling curve from boon 0 to max_boons."""
        return [cls.snapshot_at_boon(hero, b) for b in range(max_boons + 1)]

    @staticmethod
    def growth_percentage(hero: HeroStats, max_boons: int = 35) -> dict[str, float]:
        """Calculate percentage growth from base to max boons.

        Returns dict with keys: dps_growth, hp_growth, aggregate_growth.
        """
        if hero.base_dps == 0 or hero.base_hp == 0:
            return {"dps_growth": 0.0, "hp_growth": 0.0, "aggregate_growth": 0.0}

        max_bullet = hero.base_bullet_damage + (hero.damage_gain * max_boons)
        max_dps = max_bullet * hero.pellets * hero.base_fire_rate
        max_hp = hero.base_hp + (hero.hp_gain * max_boons)

        dps_growth = (max_dps - hero.base_dps) / hero.base_dps if hero.base_dps else 0
        hp_growth = (max_hp - hero.base_hp) / hero.base_hp if hero.base_hp else 0

        return {
            "dps_growth": dps_growth,
            "hp_growth": hp_growth,
            "aggregate_growth": dps_growth + hp_growth,
        }

    @staticmethod
    def boon_item_scaling(
        base_effect: float,
        boon_bonus: float,
        max_boons: int = 35,
    ) -> list[tuple[int, float]]:
        """Calculate item scaling with boons.

        Used for items like Veilwalker, Headhunter, etc.
        Returns list of (boon_level, modified_value).
        """
        return [
            (b, base_effect + (boon_bonus * b))
            for b in range(max_boons + 1)
        ]
