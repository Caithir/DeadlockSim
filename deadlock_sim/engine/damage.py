"""Bullet and spirit damage calculation engine.

All calculations are pure functions operating on data models.
No UI, no I/O, no side effects.
"""

from __future__ import annotations

import math

from ..models import (
    AbilityConfig,
    BulletResult,
    CombatConfig,
    HeroStats,
    SpiritResult,
)


class DamageCalculator:
    """Stateless calculator for Deadlock damage mechanics."""

    @staticmethod
    def bullet_damage_at_boon(hero: HeroStats, boons: int) -> float:
        """Calculate a hero's per-bullet damage at a given boon count."""
        return hero.base_bullet_damage + (hero.damage_gain * boons)

    @staticmethod
    def fire_rate_with_bonus(hero: HeroStats, fire_rate_bonus: float = 0.0) -> float:
        """Calculate effective fire rate (bullets per second)."""
        return hero.base_fire_rate * (1.0 + fire_rate_bonus)

    @staticmethod
    def effective_magazine(
        hero: HeroStats,
        ammo_increase: float = 0.0,
        ammo_flat: int = 0,
    ) -> int:
        """Calculate magazine size with ammo bonuses.

        ammo_increase is a multiplier: 1.0 = double ammo, 0.5 = +50%.
        ammo_flat is a flat bonus added after the percentage increase.
        Returns 0 if the hero has no ammo data.
        """
        if hero.base_ammo <= 0:
            return 0
        return max(1, math.floor(hero.base_ammo * (1.0 + ammo_increase)) + ammo_flat)

    @staticmethod
    def total_shred(shred_sources: list[float]) -> float:
        """Calculate combined shred from multiple sources.

        Shred stacks additively. Result is clamped to [0, 1].
        """
        return min(1.0, max(0.0, sum(shred_sources)))

    @staticmethod
    def final_resist(base_resist: float, total_shred: float) -> float:
        """Calculate effective resist after shred is applied.

        resist_after_shred = base_resist * (1 - total_shred)
        Clamped to [0, 1].
        """
        return max(0.0, min(1.0, base_resist * (1.0 - total_shred)))

    @classmethod
    def calculate_bullet(
        cls,
        hero: HeroStats,
        config: CombatConfig,
    ) -> BulletResult:
        """Full bullet damage calculation.

        Follows the spreadsheet's damage calculator logic:
        1. Damage per bullet = (base + boon_scaling) * pellets * (1 + weapon_damage_bonus)
        2. Bullets per second = fire_rate * (1 + fire_rate_bonus)
        3. Raw DPS = damage_per_bullet * bullets_per_second
        4. Shred reduces enemy resist
        5. Final DPS = Raw DPS * (1 - final_resist)
        """
        # Per-bullet damage
        scaled_dmg = cls.bullet_damage_at_boon(hero, config.boons)
        dmg_per_bullet = scaled_dmg * hero.pellets * (1.0 + config.weapon_damage_bonus)

        # Fire rate
        bps = cls.fire_rate_with_bonus(hero, config.fire_rate_bonus)

        # Raw DPS
        raw_dps = dmg_per_bullet * bps

        # Magazine
        mag_size = cls.effective_magazine(hero, config.ammo_increase, config.ammo_flat)
        dmg_per_mag = dmg_per_bullet * mag_size
        magdump_time = mag_size / bps if bps > 0 and mag_size > 0 else 0.0

        # Resist calculation
        t_shred = cls.total_shred(config.shred)
        f_resist = cls.final_resist(config.enemy_bullet_resist, t_shred)

        # Final DPS after resist
        final_dps = raw_dps * (1.0 - f_resist)

        return BulletResult(
            damage_per_bullet=dmg_per_bullet,
            bullets_per_second=bps,
            raw_dps=raw_dps,
            final_dps=final_dps,
            magazine_size=mag_size,
            damage_per_magazine=dmg_per_mag,
            magdump_time=magdump_time,
            total_shred=t_shred,
            final_resist=f_resist,
        )

    @staticmethod
    def calculate_spirit(ability: AbilityConfig) -> SpiritResult:
        """Spirit/ability damage calculation.

        Follows the spreadsheet's spirit damage logic:
        1. spirit_contribution = spirit_multiplier * current_spirit
        2. raw_damage = base_damage + spirit_contribution
        3. Apply resist shred, mystic vuln, spirit amp
        4. modified_damage = raw_damage * damage_multiplier * (1 - effective_resist)
        """
        # Spirit scaling
        spirit_contribution = ability.spirit_multiplier * ability.current_spirit
        raw_damage = ability.base_damage + spirit_contribution

        # Spirit amplification (additive modifiers that scale spirit portion)
        amp_modifier = 1.0 + ability.spirit_amp

        # Item-based damage modifiers
        ee_bonus = ability.escalating_exposure_stacks * 0.06  # 6% per EE stack
        item_modifier = 1.0 + ee_bonus + ability.crippling + ability.soulshredder

        # Apply amplification to the spirit contribution specifically,
        # then combine with base
        amplified_damage = ability.base_damage + (spirit_contribution * amp_modifier)
        modified_raw = amplified_damage * item_modifier

        # Resist
        effective_shred = min(1.0, ability.resist_shred + ability.mystic_vuln)
        effective_resist = max(
            0.0, ability.enemy_spirit_resist * (1.0 - effective_shred)
        )
        modified_damage = modified_raw * (1.0 - effective_resist)

        # DoT calculations
        total_duration = ability.ability_duration + ability.bonus_duration
        if total_duration > 0:
            total_dot = modified_damage  # total damage over duration is the modified damage
            dps = modified_damage / total_duration
        else:
            total_dot = modified_damage
            dps = modified_damage  # instant damage treated as single-hit

        return SpiritResult(
            raw_damage=raw_damage,
            modified_damage=modified_damage,
            spirit_contribution=spirit_contribution,
            dps=dps,
            total_dot_damage=total_dot,
        )

    @classmethod
    def dps_with_accuracy(
        cls,
        hero: HeroStats,
        config: CombatConfig,
    ) -> float:
        """Calculate realistic DPS factoring accuracy and headshots.

        realistic_dps = final_dps * accuracy
                      + final_dps * headshot_rate * (headshot_multiplier - 1)
        """
        result = cls.calculate_bullet(hero, config)
        base_hit_dps = result.final_dps * config.accuracy
        headshot_bonus = (
            result.final_dps
            * config.accuracy
            * config.headshot_rate
            * (config.headshot_multiplier - 1.0)
        )
        return base_hit_dps + headshot_bonus
