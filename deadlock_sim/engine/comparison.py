"""Hero comparison engine.

Compare heroes across multiple dimensions: DPS, HP, TTK, scaling, etc.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import CombatConfig, HeroStats
from .damage import DamageCalculator
from .heroes import HeroMetrics


@dataclass
class HeroComparison:
    """Side-by-side comparison of two heroes at a given boon level."""

    boon_level: int

    hero_a_name: str
    hero_a_dps: float
    hero_a_hp: float
    hero_a_dpm: float

    hero_b_name: str
    hero_b_dps: float
    hero_b_hp: float
    hero_b_dpm: float

    dps_ratio: float  # a / b
    hp_ratio: float
    dpm_ratio: float


@dataclass
class RankEntry:
    """A hero's rank in a specific stat category."""

    hero_name: str
    value: float
    rank: int


class ComparisonEngine:
    """Compare heroes and produce rankings."""

    @staticmethod
    def compare_two(
        hero_a: HeroStats,
        hero_b: HeroStats,
        boon_level: int = 0,
    ) -> HeroComparison:
        """Direct comparison of two heroes at a boon level."""
        snap_a = HeroMetrics.snapshot(hero_a, boon_level)
        snap_b = HeroMetrics.snapshot(hero_b, boon_level)

        return HeroComparison(
            boon_level=boon_level,
            hero_a_name=hero_a.name,
            hero_a_dps=snap_a.dps,
            hero_a_hp=snap_a.hp,
            hero_a_dpm=snap_a.dpm,
            hero_b_name=hero_b.name,
            hero_b_dps=snap_b.dps,
            hero_b_hp=snap_b.hp,
            hero_b_dpm=snap_b.dpm,
            dps_ratio=snap_a.dps / snap_b.dps if snap_b.dps else 0.0,
            hp_ratio=snap_a.hp / snap_b.hp if snap_b.hp else 0.0,
            dpm_ratio=snap_a.dpm / snap_b.dpm if snap_b.dpm else 0.0,
        )

    @classmethod
    def compare_curve(
        cls,
        hero_a: HeroStats,
        hero_b: HeroStats,
        max_boons: int = 35,
    ) -> list[HeroComparison]:
        """Compare two heroes across all boon levels."""
        return [
            cls.compare_two(hero_a, hero_b, b)
            for b in range(max_boons + 1)
        ]

    @staticmethod
    def rank_heroes(
        heroes: dict[str, HeroStats],
        stat: str,
        boon_level: int = 0,
        ascending: bool = False,
    ) -> list[RankEntry]:
        """Rank all heroes by a given stat at a specific boon level.

        stat can be: "dps", "hp", "dpm", "bullet_damage", "fire_rate",
                     "dps_growth", "hp_growth"
        """
        entries: list[tuple[str, float]] = []

        for name, hero in heroes.items():
            snap = HeroMetrics.snapshot(hero, boon_level)

            if stat == "dps":
                value = snap.dps
            elif stat == "hp":
                value = snap.hp
            elif stat == "dpm":
                value = snap.dpm
            elif stat == "bullet_damage":
                value = snap.bullet_damage
            elif stat == "fire_rate":
                value = hero.base_fire_rate
            elif stat == "dps_growth":
                growth = HeroMetrics.growth_percentage(hero)
                value = growth["dps_growth"]
            elif stat == "hp_growth":
                growth = HeroMetrics.growth_percentage(hero)
                value = growth["hp_growth"]
            else:
                continue

            entries.append((name, value))

        entries.sort(key=lambda x: x[1], reverse=not ascending)

        return [
            RankEntry(hero_name=name, value=value, rank=i + 1)
            for i, (name, value) in enumerate(entries)
        ]

    @staticmethod
    def cross_ttk_matrix(
        heroes: dict[str, HeroStats],
        config: CombatConfig,
        hero_names: list[str] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Build an NxN TTK matrix for a set of heroes.

        Returns nested dict: matrix[attacker][defender] = ttk_seconds.
        """
        names = hero_names or sorted(heroes.keys())
        matrix: dict[str, dict[str, float]] = {}

        for atk_name in names:
            if atk_name not in heroes:
                continue
            matrix[atk_name] = {}
            for def_name in names:
                if def_name not in heroes:
                    continue
                result = HeroMetrics.ttk(
                    heroes[atk_name], heroes[def_name], config
                )
                matrix[atk_name][def_name] = result.ttk_seconds

        return matrix
