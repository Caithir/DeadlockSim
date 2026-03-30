"""Bullet and spirit damage calculation engine.

All calculations are pure functions operating on data models.
No UI, no I/O, no side effects.
"""

from __future__ import annotations

import math

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
    ) -> SpiritResult:
        """Calculate spirit DPS for a specific hero ability.

        Uses the ability's base damage, spirit scaling, cooldown, and duration
        to compute DPS including spirit power contributions.
        """
        # Effective cooldown with CDR
        effective_cooldown = ability.cooldown * (1.0 - cooldown_reduction)
        if effective_cooldown < 0.1:
            effective_cooldown = 0.1

        config = AbilityConfig(
            base_damage=ability.base_damage,
            spirit_multiplier=ability.spirit_scaling,
            current_spirit=current_spirit,
            cooldown=effective_cooldown,
            ability_duration=ability.duration,
            enemy_spirit_resist=enemy_spirit_resist,
            resist_shred=resist_shred,
            spirit_amp=spirit_amp,
        )
        result = cls.calculate_spirit(config)

        # If the ability has a cooldown and is instant (no DoT duration),
        # DPS = damage / cooldown
        if ability.cooldown > 0 and ability.duration == 0:
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
    ) -> float:
        """Calculate total spirit DPS from all of a hero's damaging abilities.

        Sums the DPS contributions of all abilities that deal damage,
        accounting for cooldowns, spirit scaling, and resist.
        """
        total_dps = 0.0
        for ability in hero.abilities:
            if ability.base_damage <= 0:
                continue
            result = cls.calculate_ability_spirit_dps(
                ability,
                current_spirit=current_spirit,
                cooldown_reduction=cooldown_reduction,
                spirit_amp=spirit_amp,
                enemy_spirit_resist=enemy_spirit_resist,
                resist_shred=resist_shred,
            )
            total_dps += result.dps
        return total_dps

    # ── Melee damage ──────────────────────────────────────────────

    # Melee cycle times (seconds per swing) — game constants
    LIGHT_MELEE_CYCLE: float = 0.6
    HEAVY_MELEE_CYCLE: float = 1.1

    @classmethod
    def calculate_melee(
        cls,
        hero: HeroStats,
        boons: int = 0,
        weapon_damage_bonus: float = 0.0,
        enemy_bullet_resist: float = 0.0,
        shred_sources: list[float] | None = None,
    ) -> MeleeResult:
        """Calculate melee damage.

        Melee damage scales with weapon damage bonus (same as gun damage).
        Both light and heavy melee inherit the weapon damage multiplier.
        Melee damage is reduced by bullet resist.
        """
        # Melee base values scale with boons via the same damage_gain as bullets
        melee_boon_scaling = hero.damage_gain * boons

        light_base = hero.light_melee_damage + melee_boon_scaling
        heavy_base = hero.heavy_melee_damage + melee_boon_scaling

        # Weapon damage bonus applies to melee
        light_dmg = light_base * (1.0 + weapon_damage_bonus)
        heavy_dmg = heavy_base * (1.0 + weapon_damage_bonus)

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

        Returns (base_damage, scale_type, stat_scale, is_dps, proc_cooldown, proc_chance)
        or None if the item has no damage properties.
        """
        # Property keys that indicate damage output (ordered by priority)
        _DAMAGE_KEYS = [
            "DPS",  # already expressed as DPS
            "DPSMax",
            "ProcBonusMagicDamage",
            "DamagePerChain",
            "AbilityDamage",
            "TechDamage",
            "DotHealthPercent",
            "BulletDamage",
            "HeadShotBonusDamage",
            "BonusDamage",
            "Damage",
        ]

        base_damage = 0.0
        scale_type = ""
        stat_scale = 0.0
        is_dps = False
        damage_key_found = ""

        for key in _DAMAGE_KEYS:
            prop = props.get(key)
            if not isinstance(prop, dict):
                continue
            val = prop.get("value")
            if val is None:
                continue
            try:
                base_damage = float(val)
            except (ValueError, TypeError):
                continue

            damage_key_found = key
            is_dps = key in ("DPS", "DPSMax", "DotHealthPercent")

            scale_fn = prop.get("scale_function")
            if isinstance(scale_fn, dict):
                scale_type = scale_fn.get("specific_stat_scale_type", "")
                try:
                    stat_scale = float(scale_fn.get("stat_scale", 0.0))
                except (ValueError, TypeError):
                    stat_scale = 0.0
            break

        if not damage_key_found:
            return None

        # Extract proc timing
        proc_cooldown = 0.0
        proc_chance = 100.0

        cd_prop = props.get("ProcCooldown") or props.get("AbilityCooldown")
        if isinstance(cd_prop, dict):
            try:
                proc_cooldown = float(cd_prop.get("value", 0))
            except (ValueError, TypeError):
                pass

        chance_prop = props.get("ProcChance")
        if isinstance(chance_prop, dict):
            try:
                proc_chance = float(chance_prop.get("value", 100))
            except (ValueError, TypeError):
                proc_chance = 100.0

        return (base_damage, scale_type, stat_scale, is_dps, proc_cooldown, proc_chance)

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
