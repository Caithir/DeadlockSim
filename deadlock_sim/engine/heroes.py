"""Combined hero metrics: scaling and time-to-kill analysis.

Merges TTKCalculator and ScalingCalculator into a single module.
Both analyse individual hero stats across boon levels and depend
only on DamageCalculator.
"""

from __future__ import annotations

import math

from ..models import CombatConfig, HeroStats, ScalingSnapshot, TTKResult
from .damage import DamageCalculator
from .primitives import falloff_multiplier


class HeroMetrics:
    """Combined scaling and TTK analysis for individual heroes."""

    # ── Scaling ───────────────────────────────────────────────────

    @staticmethod
    def snapshot(hero: HeroStats, boon_level: int) -> ScalingSnapshot:
        """Get a hero's stats at a specific boon level."""
        bullet_dmg = DamageCalculator.bullet_damage_at_boon(hero, boon_level)
        hp = hero.base_hp + (hero.hp_gain * boon_level)
        spirit = hero.spirit_gain * boon_level

        per_bullet = bullet_dmg * hero.pellets
        dps = per_bullet * hero.base_fire_rate
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
        return [cls.snapshot(hero, b) for b in range(max_boons + 1)]

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
    def item_boon_scaling(
        base_effect: float,
        boon_bonus: float,
        max_boons: int = 35,
    ) -> list[tuple[int, float]]:
        """Calculate item scaling with boons.

        Returns list of (boon_level, modified_value).
        """
        return [
            (b, base_effect + (boon_bonus * b))
            for b in range(max_boons + 1)
        ]

    # ── TTK ───────────────────────────────────────────────────────

    @classmethod
    def ttk(
        cls,
        attacker: HeroStats,
        defender: HeroStats,
        config: CombatConfig,
    ) -> TTKResult:
        """Calculate time-to-kill for attacker vs defender.

        Uses step-by-step magazine simulation for realistic TTK:
        walks through fire→reload cycles to find exact kill time.
        """
        bullet = DamageCalculator.calculate_bullet(attacker, config)

        defender_base_hp = defender.base_hp + (defender.hp_gain * config.boons)
        target_hp = config.enemy_hp if config.enemy_hp > 0 else defender_base_hp
        target_hp += config.enemy_bonus_hp

        ideal_ttk = target_hp / bullet.final_dps if bullet.final_dps > 0 else 0.0
        realistic_dps = DamageCalculator.dps_with_accuracy(attacker, config)

        # Distance falloff (damage_per_bullet/magazine don't include it)
        falloff = falloff_multiplier(
            config.distance, attacker.falloff_range_min, attacker.falloff_range_max,
        )

        effective_dmg_per_mag = bullet.damage_per_magazine * falloff * (1.0 - bullet.final_resist)
        effective_dmg_per_mag_acc = effective_dmg_per_mag * config.accuracy
        hs_bonus_per_mag = (
            effective_dmg_per_mag
            * config.accuracy
            * config.headshot_rate
            * (config.headshot_multiplier - 1.0)
        )
        realistic_dmg_per_mag = effective_dmg_per_mag_acc + hs_bonus_per_mag

        can_one_mag = realistic_dmg_per_mag >= target_hp if realistic_dmg_per_mag > 0 else False
        if realistic_dmg_per_mag > 0:
            mags_needed = 1 if can_one_mag else math.ceil(target_hp / realistic_dmg_per_mag)
        else:
            mags_needed = 0

        # Step-by-step TTK: walk through magazine/reload cycles
        if realistic_dmg_per_mag > 0 and bullet.bullets_per_second > 0:
            remaining_hp = target_hp
            elapsed = 0.0
            # Damage per bullet accounting for falloff, accuracy and headshots
            dmg_per_bullet_eff = (
                bullet.damage_per_bullet * falloff * (1.0 - bullet.final_resist)
                * config.accuracy
            )
            hs_bonus_per_bullet = (
                bullet.damage_per_bullet * falloff * (1.0 - bullet.final_resist)
                * config.accuracy * config.headshot_rate
                * (config.headshot_multiplier - 1.0)
            )
            dmg_per_bullet_total = dmg_per_bullet_eff + hs_bonus_per_bullet
            time_per_bullet = 1.0 / bullet.bullets_per_second

            mags_used = 0
            max_mags = 200  # safety cap
            while remaining_hp > 0 and mags_used < max_mags:
                mags_used += 1
                # Fire bullets one at a time within this magazine
                for _ in range(bullet.magazine_size):
                    remaining_hp -= dmg_per_bullet_total
                    elapsed += time_per_bullet
                    if remaining_hp <= 0:
                        break
                if remaining_hp > 0:
                    # Add reload time
                    elapsed += bullet.reload_time

            realistic_ttk = max(0.0, elapsed)
            mags_needed = mags_used
            can_one_mag = mags_needed <= 1
        elif realistic_dps > 0:
            realistic_ttk = target_hp / realistic_dps
        else:
            realistic_ttk = 0.0

        return TTKResult(
            ttk_seconds=ideal_ttk,
            realistic_ttk=realistic_ttk,
            magazines_needed=mags_needed,
            can_one_mag=can_one_mag,
            effective_dps=bullet.final_dps,
            realistic_dps=realistic_dps,
            target_hp=target_hp,
            damage_per_magazine=bullet.damage_per_magazine,
        )

    @classmethod
    def ttk_curve(
        cls,
        attacker: HeroStats,
        defender: HeroStats,
        base_config: CombatConfig,
        max_boons: int = 35,
    ) -> list[tuple[int, TTKResult]]:
        """Calculate TTK at each boon level."""
        results = []
        for boon in range(max_boons + 1):
            config = CombatConfig(
                boons=boon,
                weapon_damage_bonus=base_config.weapon_damage_bonus,
                fire_rate_bonus=base_config.fire_rate_bonus,
                ammo_increase=base_config.ammo_increase,
                shred=base_config.shred,
                current_spirit=base_config.current_spirit,
                spirit_amp=base_config.spirit_amp,
                accuracy=base_config.accuracy,
                headshot_rate=base_config.headshot_rate,
                headshot_multiplier=base_config.headshot_multiplier,
                enemy_bullet_resist=base_config.enemy_bullet_resist,
                enemy_spirit_resist=base_config.enemy_spirit_resist,
                enemy_hp=0,
                enemy_bonus_hp=base_config.enemy_bonus_hp,
            )
            result = cls.ttk(attacker, defender, config)
            results.append((boon, result))
        return results
