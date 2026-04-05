"""Bullet and spirit damage calculation engine.

All calculations are pure functions operating on data models.
No UI, no I/O, no side effects.
"""

from __future__ import annotations

import math

from .primitives import extract_item_damage as _extract_item_damage_impl
from .primitives import falloff_multiplier
from .primitives import resist_after_shred
from ..models import (
    AbilityConfig,
    AbilityDamageResult,
    BulletResult,
    CombatConfig,
    HeroAbility,
    HeroStats,
    Item,
    ItemDamageResult,
    MeleeResult,
    SpiritResult,
)

# Property names from upgrade data that add flat damage
_DAMAGE_UPGRADE_KEYS = {
    "Damage", "AbilityDamage", "ExplodeDamage", "StompDamage",
    "TechDamage", "BulletDamage", "BonusDamage", "DamagePerProjectile",
    "DamagePerRocket", "ImpactDamage", "ProcDamage", "PulseDamage",
    "ExplosionDamage", "FullChargeDamage", "BaseDamage", "PerfectDamage",
    "BarrelDamage", "BuffDamage", "CartDamage", "LateCheckoutDamage",
    "PetrifyDamage", "DamageHeavyMelee", "HeavyMeleeDamage", "MeleeDamage",
    "MaxDamage", "MagicDamagePerBullet", "BonusDamagePerBullet",
    "DamageBonus",
}

# Property names from upgrade data that represent DPS values
_DPS_UPGRADE_KEYS = {"DPS", "DamagePerSecond", "PulseDPS", "TurretDPS", "MinDps", "MaxDPS"}


def apply_ability_upgrades(
    ability: HeroAbility,
    active_tiers: list[int],
) -> tuple[float, float, float, float]:
    """Return (base_damage, cooldown, duration, spirit_scaling) after applying upgrade bonuses.

    Only tiers present in *active_tiers* are applied.

    For DPS abilities (``ability.is_dps``), when duration changes the total
    damage and spirit scaling are rescaled proportionally (same per-second
    rate over the new duration).  ``EAddToScale`` upgrades modify
    ``spirit_scaling`` rather than adding flat damage.
    """
    base_damage = ability.base_damage
    cooldown = ability.cooldown
    duration = ability.duration
    spirit_scaling = ability.spirit_scaling

    for tier in sorted(active_tiers):
        upgrade = next((u for u in ability.upgrades if u.tier == tier), None)
        if not upgrade:
            continue
        for pu in upgrade.property_upgrades:
            name = pu.get("name", "")
            raw = pu.get("bonus", 0)
            try:
                bonus = float(raw)
            except (ValueError, TypeError):
                continue

            upgrade_type = pu.get("upgrade_type", "")

            # EAddToScale on DPS keys → spirit scaling modification
            if upgrade_type == "EAddToScale" and name in _DPS_UPGRADE_KEYS:
                if ability.is_dps and duration > 0:
                    spirit_scaling += bonus * duration
                else:
                    spirit_scaling += bonus
                continue

            if name in _DAMAGE_UPGRADE_KEYS:
                base_damage += bonus
            elif name in _DPS_UPGRADE_KEYS:
                if duration > 0:
                    base_damage += bonus * duration
                else:
                    base_damage += bonus
            elif name == "AbilityCooldown":
                cooldown += bonus  # bonus is negative (e.g. -12)
            elif name in ("AbilityDuration", "AbilityChannelTime"):
                old_duration = duration
                duration += bonus
                # For DPS abilities, rescale total damage and spirit scaling
                # when duration changes (same DPS rate over longer/shorter time)
                if ability.is_dps and old_duration > 0 and duration > 0:
                    scale = duration / old_duration
                    base_damage *= scale
                    spirit_scaling *= scale

    return max(0.0, base_damage), max(0.1, cooldown), max(0.0, duration), spirit_scaling


class DamageCalculator:
    """Stateless calculator for Deadlock damage mechanics."""

    @staticmethod
    def effective_pellets(hero: HeroStats) -> int:
        """Return the number of pellets that hit a single target per shot.

        Most heroes land all pellets on one target. Drifter spreads
        pellets across targets (max 1 per target).
        """
        if hero.max_pellets_per_target > 0:
            return min(hero.pellets, hero.max_pellets_per_target)
        return hero.pellets

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
        return max(1, math.ceil(hero.base_ammo * (1.0 + ammo_increase)) + ammo_flat)

    @staticmethod
    def total_shred(shred_sources: list[float]) -> float:
        """Calculate combined shred from multiple sources.

        Shred stacks additively. Result is clamped to [0, 1].
        """
        return min(1.0, max(0.0, sum(shred_sources)))

    @staticmethod
    def final_resist(base_resist: float, total_shred: float) -> float:
        """Calculate effective resist after shred is applied.

        Delegates to primitives.resist_after_shred.
        """
        return resist_after_shred(base_resist, total_shred)

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
        5. Falloff reduces damage at range
        6. Bullet damage amp from target debuffs
        7. Final DPS = Raw DPS * falloff * (1 + bullet_amp) * (1 - final_resist)
        """
        # Effective weapon damage bonus including golden statues and conditionals
        weapon_bonus = config.weapon_damage_bonus

        # Golden statue weapon bonus
        if config.golden_weapon_total > 0:
            weapon_bonus += config.golden_weapon_total
        elif config.golden_buffs_count > 0:
            weapon_bonus += config.golden_buffs_count / 3.0 * 0.05  # ~5% per buff, split 3 ways

        # Conditional item bonuses
        if config.berserker_stacks > 0:
            weapon_bonus += config.berserker_stacks * 0.07
        if config.intensifying_mag_pct > 0:
            weapon_bonus += config.intensifying_mag_pct
        if config.opening_rounds_active:
            weapon_bonus += 0.45
        if config.close_range_active:
            weapon_bonus += 0.50  # Point Blank (strongest close-range item)
        if config.long_range_active:
            weapon_bonus += 0.70  # Sharpshooter (strongest long-range item)

        # Per-bullet damage: base scaled by weapon %, then add flat bonus
        scaled_dmg = cls.bullet_damage_at_boon(hero, config.boons)
        eff_pellets = cls.effective_pellets(hero)
        dmg_per_bullet = (
            scaled_dmg * (1.0 + weapon_bonus) + config.flat_weapon_bonus
        ) * eff_pellets

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

        # Distance falloff
        falloff = falloff_multiplier(
            config.distance, hero.falloff_range_min, hero.falloff_range_max,
        )

        # Bullet damage amp from target debuffs
        bullet_amp = 1.0 + config.target_bullet_damage_amp

        # Final DPS after resist (burst — ignores reload)
        final_dps = raw_dps * falloff * bullet_amp * (1.0 - f_resist)

        # Sustained DPS including reload downtime
        reload_time = hero.reload_duration if hero.reload_duration > 0 else 0.0
        cycle_time = magdump_time + reload_time
        if cycle_time > 0 and mag_size > 0:
            final_dmg_per_mag = dmg_per_mag * falloff * bullet_amp * (1.0 - f_resist)
            sustained_dps = final_dmg_per_mag / cycle_time
        else:
            sustained_dps = final_dps

        return BulletResult(
            damage_per_bullet=dmg_per_bullet,
            bullets_per_second=bps,
            raw_dps=raw_dps,
            final_dps=final_dps,
            sustained_dps=sustained_dps,
            magazine_size=mag_size,
            damage_per_magazine=dmg_per_mag,
            magdump_time=magdump_time,
            reload_time=reload_time,
            total_shred=t_shred,
            final_resist=f_resist,
        )

    @staticmethod
    def calculate_spirit(ability: AbilityConfig) -> SpiritResult:
        """Spirit/ability damage calculation.

        Follows the game's spirit damage logic (consistent with simulation engine):
        1. spirit_contribution = spirit_multiplier * current_spirit
        2. raw_damage = base_damage + spirit_contribution
        3. Spirit amp (including EE stacks) applies to ALL of raw_damage
        4. Damage amp (crippling/soulshredder) is a separate multiplier
        5. modified_damage = raw * (1 + spirit_amp) * (1 + damage_amp) * (1 - resist)
        """
        # Spirit scaling
        spirit_contribution = ability.spirit_multiplier * ability.current_spirit
        raw_damage = ability.base_damage + spirit_contribution

        # Spirit amplification: attacker spirit_amp + EE stacks on target
        # EE stacks use the per-stack value from the ability config (not hardcoded)
        ee_amp = ability.escalating_exposure_stacks * ability.ee_per_stack
        total_spirit_amp = 1.0 + ability.spirit_amp + ee_amp

        # Damage amp: crippling / soulshredder (separate multiplier)
        damage_amp = 1.0 + ability.crippling + ability.soulshredder

        # Apply spirit amp and damage amp as separate multipliers
        modified_raw = raw_damage * total_spirit_amp * damage_amp

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

    @classmethod
    def calculate_ability_spirit_dps(
        cls,
        ability: HeroAbility,
        current_spirit: int = 0,
        cooldown_reduction: float = 0.0,
        spirit_amp: float = 0.0,
        enemy_spirit_resist: float = 0.0,
        resist_shred: float = 0.0,
        upgrade_tiers: list[int] | None = None,
    ) -> SpiritResult:
        """Calculate spirit DPS for a specific hero ability.

        Uses the ability's base damage, spirit scaling, cooldown, and duration
        to compute DPS including spirit power contributions.
        If *upgrade_tiers* is provided, the listed tiers are applied first.
        """
        base_damage = ability.base_damage
        cooldown = ability.cooldown
        duration = ability.duration
        spirit_multiplier = ability.spirit_scaling

        if upgrade_tiers:
            base_damage, cooldown, duration, spirit_multiplier = apply_ability_upgrades(
                ability, upgrade_tiers
            )

        # Effective cooldown with CDR
        effective_cooldown = cooldown * (1.0 - cooldown_reduction)
        if effective_cooldown < 0.1:
            effective_cooldown = 0.1

        config = AbilityConfig(
            base_damage=base_damage,
            spirit_multiplier=spirit_multiplier,
            current_spirit=current_spirit,
            cooldown=effective_cooldown,
            ability_duration=duration,
            enemy_spirit_resist=enemy_spirit_resist,
            resist_shred=resist_shred,
            spirit_amp=spirit_amp,
        )
        result = cls.calculate_spirit(config)

        # If the ability has a cooldown and is instant (no DoT duration),
        # DPS = damage / cooldown
        if cooldown > 0 and duration == 0:
            cd_dps = result.modified_damage / effective_cooldown
            return SpiritResult(
                raw_damage=result.raw_damage,
                modified_damage=result.modified_damage,
                spirit_contribution=result.spirit_contribution,
                dps=cd_dps,
                total_dot_damage=result.total_dot_damage,
            )

        return result

    @classmethod
    def hero_total_spirit_dps(
        cls,
        hero: HeroStats,
        current_spirit: int = 0,
        cooldown_reduction: float = 0.0,
        spirit_amp: float = 0.0,
        enemy_spirit_resist: float = 0.0,
        resist_shred: float = 0.0,
        ability_upgrades: dict[int, list[int]] | None = None,
        boons: int = 0,
        weapon_damage_bonus: float = 0.0,
        melee_damage_pct: float = 0.0,
    ) -> float:
        """Calculate total spirit DPS from all of a hero's damaging abilities.

        *ability_upgrades* maps ability index → list of active tier numbers
        (e.g. ``{0: [1, 2], 2: [1]}``).  Tiers modify base damage / cooldown.

        For melee-scaled abilities (melee_scale > 0), the base damage is derived
        from the hero's light melee damage instead of spirit damage.
        """
        total_dps = 0.0
        for i, ability in enumerate(hero.abilities):
            if ability.base_damage <= 0 and ability.melee_scale <= 0:
                continue
            tiers = (ability_upgrades or {}).get(i)

            # For melee-scaled abilities, compute melee-based damage
            if ability.melee_scale > 0:
                melee_boon = hero.damage_gain * boons
                melee_weapon = weapon_damage_bonus * cls.MELEE_WEAPON_SCALE
                light_melee_dmg = (hero.light_melee_damage + melee_boon) * (1.0 + melee_weapon + melee_damage_pct)
                melee_base = light_melee_dmg * ability.melee_scale

                cooldown = ability.cooldown
                duration = ability.duration
                spirit_multiplier = ability.spirit_scaling
                base_damage = ability.base_damage + melee_base
                if tiers:
                    base_damage_upg, cooldown, duration, spirit_multiplier = apply_ability_upgrades(ability, tiers)
                    base_damage = base_damage_upg + melee_base

                effective_cooldown = cooldown * (1.0 - cooldown_reduction)
                if effective_cooldown < 0.1:
                    effective_cooldown = 0.1

                config = AbilityConfig(
                    base_damage=base_damage,
                    spirit_multiplier=spirit_multiplier,
                    current_spirit=current_spirit,
                    cooldown=effective_cooldown,
                    ability_duration=duration,
                    enemy_spirit_resist=enemy_spirit_resist,
                    resist_shred=resist_shred,
                    spirit_amp=spirit_amp,
                )
                result = cls.calculate_spirit(config)
                if cooldown > 0 and duration == 0:
                    total_dps += result.modified_damage / effective_cooldown
                else:
                    total_dps += result.dps
            else:
                result = cls.calculate_ability_spirit_dps(
                    ability,
                    current_spirit=current_spirit,
                    cooldown_reduction=cooldown_reduction,
                    spirit_amp=spirit_amp,
                    enemy_spirit_resist=enemy_spirit_resist,
                    resist_shred=resist_shred,
                    upgrade_tiers=tiers,
                )
                total_dps += result.dps
        return total_dps

    # ── Melee damage ──────────────────────────────────────────────

    # Melee cycle times (seconds per swing) — game constants
    LIGHT_MELEE_CYCLE: float = 0.6
    HEAVY_MELEE_CYCLE: float = 1.0

    # Weapon damage scales melee at 50% (wiki-documented rate)
    MELEE_WEAPON_SCALE: float = 0.5

    @classmethod
    def calculate_melee(
        cls,
        hero: HeroStats,
        boons: int = 0,
        weapon_damage_bonus: float = 0.0,
        enemy_bullet_resist: float = 0.0,
        shred_sources: list[float] | None = None,
        melee_damage_pct: float = 0.0,
        heavy_melee_damage_pct: float = 0.0,
    ) -> MeleeResult:
        """Calculate melee damage.

        Melee damage scales with weapon damage bonus (same as gun damage).
        Both light and heavy melee inherit the weapon damage multiplier.
        Bonus melee damage % from items applies additively on top.
        Heavy melee also gets heavy_melee_damage_pct.
        Melee damage is reduced by bullet resist.
        """
        # Melee base values scale with boons via the same damage_gain as bullets
        melee_boon_scaling = hero.damage_gain * boons

        light_base = hero.light_melee_damage + melee_boon_scaling
        heavy_base = hero.heavy_melee_damage + melee_boon_scaling

        # Weapon damage bonus applies to melee at 50% rate (wiki-documented)
        melee_weapon_bonus = weapon_damage_bonus * cls.MELEE_WEAPON_SCALE
        light_dmg = light_base * (1.0 + melee_weapon_bonus + melee_damage_pct)
        heavy_dmg = heavy_base * (1.0 + melee_weapon_bonus + melee_damage_pct + heavy_melee_damage_pct)

        # Apply resist (melee uses bullet resist)
        t_shred = cls.total_shred(shred_sources or [])
        f_resist = cls.final_resist(enemy_bullet_resist, t_shred)
        resist_mult = 1.0 - f_resist

        light_dmg *= resist_mult
        heavy_dmg *= resist_mult

        light_dps = light_dmg / cls.LIGHT_MELEE_CYCLE if cls.LIGHT_MELEE_CYCLE > 0 else 0.0
        heavy_dps = heavy_dmg / cls.HEAVY_MELEE_CYCLE if cls.HEAVY_MELEE_CYCLE > 0 else 0.0

        return MeleeResult(
            light_damage=light_dmg,
            heavy_damage=heavy_dmg,
            light_dps=light_dps,
            heavy_dps=heavy_dps,
        )

    # ── Item damage ───────────────────────────────────────────────

    @classmethod
    def calculate_item_damage(
        cls,
        item: Item,
        current_spirit: float = 0.0,
        boons: int = 0,
        weapon_damage_bonus: float = 0.0,
        enemy_spirit_resist: float = 0.0,
        enemy_bullet_resist: float = 0.0,
        spirit_resist_shred: float = 0.0,
        bullet_resist_shred: float = 0.0,
        spirit_amp: float = 0.0,
    ) -> ItemDamageResult | None:
        """Calculate DPS for an individual damage-dealing item.

        Parses the item's raw_properties to find damage values and their
        scale_function, then applies the appropriate scaling:
        - ETechPower: scales with current_spirit (spirit investment)
        - ELevelUpBoons: scales with boon count
        - Bullet damage items: scale with weapon_damage_bonus

        Returns None if the item has no damage-dealing properties.
        """
        props = item.raw_properties
        if not props:
            return None

        damage_info = cls._extract_item_damage(props)
        if damage_info is None:
            return None

        base_damage, scale_type, stat_scale, is_dps, proc_cooldown, proc_chance = damage_info

        # Determine scaling source and compute contribution
        spirit_contribution = 0.0
        boon_contribution = 0.0
        damage_type = "spirit"
        scaled_from = "spirit"

        if scale_type == "ETechPower":
            spirit_contribution = stat_scale * current_spirit
            scaled_damage = base_damage + spirit_contribution
            # Spirit amp applies to spirit-scaled item damage
            scaled_damage *= (1.0 + spirit_amp)
            damage_type = "spirit"
            scaled_from = "spirit"
        elif scale_type == "ELevelUpBoons":
            boon_contribution = stat_scale * boons
            scaled_damage = base_damage + boon_contribution
            damage_type = "bullet"
            scaled_from = "boons"
        elif scale_type == "EBaseWeaponDamage":
            # Scales with weapon damage bonus (like melee)
            scaled_damage = base_damage * (1.0 + weapon_damage_bonus)
            damage_type = "bullet"
            scaled_from = "weapon"
        else:
            # Unknown or no scaling — use base value
            scaled_damage = base_damage
            scaled_from = "none"

        # Apply resist based on damage type
        if damage_type == "spirit":
            effective_shred = min(1.0, spirit_resist_shred)
            effective_resist = max(0.0, enemy_spirit_resist * (1.0 - effective_shred))
        else:
            effective_shred = min(1.0, bullet_resist_shred)
            effective_resist = max(0.0, enemy_bullet_resist * (1.0 - effective_shred))

        final_damage = scaled_damage * (1.0 - effective_resist)

        # Calculate DPS
        if is_dps:
            # Value is already expressed as DPS (e.g. Alchemical Fire)
            dps = final_damage
            damage_per_hit = final_damage
        elif proc_cooldown > 0:
            # Proc-based item: DPS = damage * (proc_chance / 100) / proc_cooldown
            # But if proc_chance is 100%, it's just damage / cooldown
            effective_chance = min(1.0, proc_chance / 100.0) if proc_chance > 0 else 1.0
            dps = final_damage * effective_chance / proc_cooldown
            damage_per_hit = final_damage
        else:
            # Single-hit or unknown timing — report damage, DPS = damage
            dps = final_damage
            damage_per_hit = final_damage

        return ItemDamageResult(
            item_name=item.name,
            damage_per_hit=damage_per_hit,
            dps=dps,
            damage_type=damage_type,
            scaled_from=scaled_from,
            spirit_contribution=spirit_contribution,
            boon_contribution=boon_contribution,
        )

    @staticmethod
    def _extract_item_damage(
        props: dict,
    ) -> tuple[float, str, float, bool, float, float] | None:
        """Extract damage info from item raw_properties.

        Delegates to primitives.extract_item_damage.
        """
        return _extract_item_damage_impl(props)

    # ── Ability damage with boon context ──────────────────────────

    @classmethod
    def calculate_ability_damage(
        cls,
        ability: HeroAbility,
        hero: HeroStats,
        boons: int = 0,
        bonus_spirit: float = 0.0,
        cooldown_reduction: float = 0.0,
        spirit_amp: float = 0.0,
        enemy_spirit_resist: float = 0.0,
        resist_shred: float = 0.0,
    ) -> AbilityDamageResult:
        """Calculate ability damage using boon-derived spirit power.

        Spirit power at a given boon count = hero.spirit_gain * boons + bonus_spirit.
        This feeds into the standard spirit damage pipeline.
        """
        current_spirit = (hero.spirit_gain * boons) + bonus_spirit

        result = cls.calculate_ability_spirit_dps(
            ability,
            current_spirit=int(current_spirit),
            cooldown_reduction=cooldown_reduction,
            spirit_amp=spirit_amp,
            enemy_spirit_resist=enemy_spirit_resist,
            resist_shred=resist_shred,
        )

        effective_cooldown = ability.cooldown * (1.0 - cooldown_reduction)
        if effective_cooldown < 0.1:
            effective_cooldown = 0.1

        return AbilityDamageResult(
            ability_name=ability.name,
            raw_damage=result.raw_damage,
            modified_damage=result.modified_damage,
            spirit_contribution=result.spirit_contribution,
            dps=result.dps,
            effective_cooldown=effective_cooldown,
            boons=boons,
            current_spirit=current_spirit,
        )

    @classmethod
    def hero_ability_breakdown(
        cls,
        hero: HeroStats,
        boons: int = 0,
        bonus_spirit: float = 0.0,
        cooldown_reduction: float = 0.0,
        spirit_amp: float = 0.0,
        enemy_spirit_resist: float = 0.0,
        resist_shred: float = 0.0,
    ) -> list[AbilityDamageResult]:
        """Calculate damage for all of a hero's damaging abilities at a boon level.

        Returns a list of AbilityDamageResult, one per damaging ability.
        """
        results = []
        for ability in hero.abilities:
            if ability.base_damage <= 0:
                continue
            results.append(
                cls.calculate_ability_damage(
                    ability,
                    hero,
                    boons=boons,
                    bonus_spirit=bonus_spirit,
                    cooldown_reduction=cooldown_reduction,
                    spirit_amp=spirit_amp,
                    enemy_spirit_resist=enemy_spirit_resist,
                    resist_shred=resist_shred,
                )
            )
        return results
