"""Time-to-Kill calculation engine.

Computes how long it takes one hero to kill another,
factoring in accuracy, headshots, magazine reloads, and resist.
"""

from __future__ import annotations

import math

from ..models import CombatConfig, HeroStats, TTKResult
from .damage import DamageCalculator


class TTKCalculator:
    """Stateless TTK calculator."""

    @classmethod
    def calculate(
        cls,
        attacker: HeroStats,
        defender: HeroStats,
        config: CombatConfig,
    ) -> TTKResult:
        """Calculate time-to-kill for attacker vs defender.

        Follows the spreadsheet TTK logic:
        1. Get attacker's bullet DPS against defender's resist
        2. Calculate defender's effective HP (base + boons + items)
        3. Ideal TTK = HP / DPS
        4. Realistic TTK factors in accuracy, headshots, mag dumps
        """
        # Attacker damage output
        bullet = DamageCalculator.calculate_bullet(attacker, config)

        # Defender HP
        defender_base_hp = defender.base_hp + (defender.hp_gain * config.boons)
        target_hp = config.enemy_hp if config.enemy_hp > 0 else defender_base_hp
        target_hp += config.enemy_bonus_hp

        # Ideal TTK (100% accuracy, no reloads considered)
        ideal_ttk = target_hp / bullet.final_dps if bullet.final_dps > 0 else 0.0

        # Realistic DPS with accuracy and headshots
        realistic_dps = DamageCalculator.dps_with_accuracy(attacker, config)

        # Magazine-aware TTK
        effective_dmg_per_mag = bullet.damage_per_magazine * (1.0 - bullet.final_resist)
        effective_dmg_per_mag_acc = effective_dmg_per_mag * config.accuracy
        # Add headshot bonus to magazine damage
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

        # Realistic TTK = time to deal enough damage through mags
        if realistic_dps > 0:
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
        """Calculate TTK at each boon level.

        Both attacker and defender scale with boons together.
        Returns list of (boon_level, TTKResult).
        """
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
                enemy_hp=0,  # use defender's boon-scaled HP
                enemy_bonus_hp=base_config.enemy_bonus_hp,
            )
            result = cls.calculate(attacker, defender, config)
            results.append((boon, result))
        return results
