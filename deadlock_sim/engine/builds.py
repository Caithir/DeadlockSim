"""Build engine: aggregate item stats and evaluate builds.

Pure functions for combining item effects into CombatConfig parameters
and evaluating build effectiveness.
"""

from __future__ import annotations

from ..models import (
    Build,
    BuildResult,
    BuildStats,
    BulletResult,
    CombatConfig,
    HeroStats,
    Item,
)
from .damage import DamageCalculator
from .ttk import TTKCalculator


class BuildEngine:
    """Aggregate item stats and convert builds to combat configurations."""

    @staticmethod
    def aggregate_stats(build: Build) -> BuildStats:
        """Sum all item stats in a build into a single BuildStats."""
        bs = BuildStats()
        for item in build.items:
            bs.weapon_damage_pct += item.weapon_damage_pct
            bs.fire_rate_pct += item.fire_rate_pct
            bs.ammo_flat += item.ammo_flat
            bs.ammo_pct += item.ammo_pct
            bs.bullet_resist_pct += item.bullet_resist_pct
            bs.spirit_resist_pct += item.spirit_resist_pct
            bs.bonus_hp += item.bonus_hp
            bs.spirit_power += item.spirit_power
            bs.bullet_lifesteal += item.bullet_lifesteal
            bs.spirit_lifesteal += item.spirit_lifesteal
            bs.hp_regen += item.hp_regen
            bs.bullet_shield += item.bullet_shield
            bs.spirit_shield += item.spirit_shield
            bs.headshot_bonus += item.headshot_bonus
            bs.bullet_resist_shred += item.bullet_resist_shred
            bs.spirit_resist_shred += item.spirit_resist_shred
            bs.cooldown_reduction += item.cooldown_reduction
            bs.spirit_amp_pct += item.spirit_amp_pct
        bs.total_cost = build.total_cost
        return bs

    @staticmethod
    def build_to_attacker_config(
        build_stats: BuildStats,
        boons: int = 0,
        accuracy: float = 1.0,
        headshot_rate: float = 0.0,
        enemy_bullet_resist: float = 0.0,
        enemy_hp: float = 0.0,
        enemy_bonus_hp: float = 0.0,
    ) -> CombatConfig:
        """Create a CombatConfig from aggregated build stats (attacker perspective).

        The build provides weapon damage, fire rate, ammo, and shred bonuses.
        The enemy's resist/HP are set separately.
        """
        shred = []
        if build_stats.bullet_resist_shred > 0:
            shred.append(build_stats.bullet_resist_shred)

        return CombatConfig(
            boons=boons,
            weapon_damage_bonus=build_stats.weapon_damage_pct,
            fire_rate_bonus=build_stats.fire_rate_pct,
            ammo_increase=build_stats.ammo_pct,
            ammo_flat=build_stats.ammo_flat,
            shred=shred,
            current_spirit=int(build_stats.spirit_power),
            spirit_amp=build_stats.spirit_amp_pct,
            accuracy=accuracy,
            headshot_rate=headshot_rate,
            enemy_bullet_resist=enemy_bullet_resist,
            enemy_hp=enemy_hp,
            enemy_bonus_hp=enemy_bonus_hp,
        )

    @staticmethod
    def defender_effective_hp(
        defender: HeroStats,
        defender_build_stats: BuildStats,
        boons: int = 0,
    ) -> float:
        """Calculate defender's effective HP including build bonuses."""
        base_hp = defender.base_hp + (defender.hp_gain * boons)
        return base_hp + defender_build_stats.bonus_hp + defender_build_stats.bullet_shield

    @classmethod
    def evaluate_build(
        cls,
        hero: HeroStats,
        build: Build,
        boons: int = 0,
        accuracy: float = 1.0,
        headshot_rate: float = 0.0,
        defender: HeroStats | None = None,
        defender_build: Build | None = None,
    ) -> BuildResult:
        """Evaluate a build for a hero, computing DPS and optional TTK."""
        build_stats = cls.aggregate_stats(build)

        # Defender setup
        enemy_resist = 0.0
        enemy_hp = 0.0
        defender_bs = BuildStats()
        if defender:
            if defender_build:
                defender_bs = cls.aggregate_stats(defender_build)
            enemy_resist = defender_bs.bullet_resist_pct
            enemy_hp = cls.defender_effective_hp(defender, defender_bs, boons)

        config = cls.build_to_attacker_config(
            build_stats,
            boons=boons,
            accuracy=accuracy,
            headshot_rate=headshot_rate,
            enemy_bullet_resist=enemy_resist,
            enemy_hp=enemy_hp,
        )

        bullet_result = DamageCalculator.calculate_bullet(hero, config)

        ttk_result = None
        if defender and enemy_hp > 0:
            ttk_result = TTKCalculator.calculate(hero, defender, config)

        effective_hp = (
            hero.base_hp
            + (hero.hp_gain * boons)
            + build_stats.bonus_hp
            + build_stats.bullet_shield
        )

        return BuildResult(
            hero_name=hero.name,
            build=build,
            build_stats=build_stats,
            bullet_result=bullet_result,
            ttk_result=ttk_result,
            effective_hp=effective_hp,
        )


class BuildOptimizer:
    """Find optimal item combinations for a given budget and goal."""

    @staticmethod
    def best_dps_items(
        items: dict[str, Item],
        hero: HeroStats,
        budget: int,
        boons: int = 0,
        max_items: int = 12,
        exclude_conditional: bool = True,
    ) -> Build:
        """Find the build that maximizes raw DPS within a budget.

        Uses a greedy approach: repeatedly add the item with the best
        DPS-per-soul ratio until the budget is exhausted or max_items reached.
        """
        # Filter to items we can evaluate for DPS impact
        candidates = []
        for item in items.values():
            if exclude_conditional and item.condition:
                continue
            if item.cost > budget:
                continue
            # Must contribute to DPS somehow
            if (item.weapon_damage_pct > 0 or item.fire_rate_pct > 0
                    or item.ammo_flat > 0 or item.ammo_pct > 0
                    or item.bullet_resist_shred > 0):
                candidates.append(item)

        selected: list[Item] = []
        remaining_budget = budget
        used_names: set[str] = set()

        while len(selected) < max_items and candidates:
            best_item = None
            best_dps_gain = 0.0

            current_build = Build(items=list(selected))
            current_stats = BuildEngine.aggregate_stats(current_build)
            current_config = BuildEngine.build_to_attacker_config(current_stats, boons=boons)
            current_dps = DamageCalculator.calculate_bullet(hero, current_config).raw_dps

            for item in candidates:
                if item.name in used_names:
                    continue
                if item.cost > remaining_budget:
                    continue

                test_build = Build(items=list(selected) + [item])
                test_stats = BuildEngine.aggregate_stats(test_build)
                test_config = BuildEngine.build_to_attacker_config(test_stats, boons=boons)
                test_dps = DamageCalculator.calculate_bullet(hero, test_config).raw_dps
                dps_gain = test_dps - current_dps

                if dps_gain > best_dps_gain:
                    best_dps_gain = dps_gain
                    best_item = item

            if best_item is None:
                break

            selected.append(best_item)
            used_names.add(best_item.name)
            remaining_budget -= best_item.cost

        return Build(items=selected)

    @staticmethod
    def best_ttk_items(
        items: dict[str, Item],
        hero: HeroStats,
        defender: HeroStats,
        budget: int,
        boons: int = 0,
        accuracy: float = 0.5,
        headshot_rate: float = 0.15,
        max_items: int = 12,
        exclude_conditional: bool = True,
    ) -> Build:
        """Find the build that minimizes TTK within a budget.

        Greedy approach: pick the item that reduces TTK most per iteration.
        """
        candidates = []
        for item in items.values():
            if exclude_conditional and item.condition:
                continue
            if item.cost > budget:
                continue
            # Must contribute to offense
            if (item.weapon_damage_pct > 0 or item.fire_rate_pct > 0
                    or item.ammo_flat > 0 or item.ammo_pct > 0
                    or item.bullet_resist_shred > 0):
                candidates.append(item)

        selected: list[Item] = []
        remaining_budget = budget
        used_names: set[str] = set()

        while len(selected) < max_items and candidates:
            best_item = None
            best_ttk = float('inf')

            for item in candidates:
                if item.name in used_names:
                    continue
                if item.cost > remaining_budget:
                    continue

                test_build = Build(items=list(selected) + [item])
                result = BuildEngine.evaluate_build(
                    hero, test_build,
                    boons=boons,
                    accuracy=accuracy,
                    headshot_rate=headshot_rate,
                    defender=defender,
                )
                if result.ttk_result and result.ttk_result.realistic_ttk > 0:
                    if result.ttk_result.realistic_ttk < best_ttk:
                        best_ttk = result.ttk_result.realistic_ttk
                        best_item = item

            if best_item is None:
                break

            selected.append(best_item)
            used_names.add(best_item.name)
            remaining_budget -= best_item.cost

        return Build(items=selected)
