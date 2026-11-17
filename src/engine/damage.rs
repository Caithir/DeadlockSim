//! Bullet, spirit, melee and item damage calculations.
//!
//! All calculations are pure functions operating on data models.

use std::collections::BTreeMap;

use crate::models::{
    num, AbilityConfig, AbilityDamageResult, BulletResult, CombatConfig, HeroAbility, HeroStats, Item,
    ItemDamageResult, MeleeResult, SpiritResult,
};

use super::primitives::{extract_item_damage, falloff_multiplier, resist_after_shred};

/// Ability upgrades: ability index → purchased tier numbers.
pub type AbilityUpgrades = BTreeMap<usize, Vec<i64>>;

/// Upgrade property names that add flat damage.
const DAMAGE_UPGRADE_KEYS: &[&str] = &[
    "Damage",
    "AbilityDamage",
    "ExplodeDamage",
    "StompDamage",
    "TechDamage",
    "BulletDamage",
    "BonusDamage",
    "DamagePerProjectile",
    "DamagePerRocket",
    "ImpactDamage",
    "ProcDamage",
    "PulseDamage",
    "ExplosionDamage",
    "FullChargeDamage",
    "BaseDamage",
    "PerfectDamage",
    "BarrelDamage",
    "BuffDamage",
    "CartDamage",
    "LateCheckoutDamage",
    "PetrifyDamage",
    "DamageHeavyMelee",
    "HeavyMeleeDamage",
    "MeleeDamage",
    "MaxDamage",
    "MagicDamagePerBullet",
    "BonusDamagePerBullet",
    "DamageBonus",
];

/// Upgrade property names that represent DPS values.
const DPS_UPGRADE_KEYS: &[&str] = &["DPS", "DamagePerSecond", "PulseDPS", "TurretDPS", "MinDps", "MaxDPS"];

/// Melee cycle times (seconds per swing) — game constants.
pub const LIGHT_MELEE_CYCLE: f64 = 0.6;
pub const HEAVY_MELEE_CYCLE: f64 = 1.0;
/// Weapon damage scales melee at 50%.
pub const MELEE_WEAPON_SCALE: f64 = 0.5;

/// Lowest ability cooldown reachable through cooldown reduction.
const MIN_COOLDOWN: f64 = 0.1;

/// An ability's numbers after upgrades.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct UpgradedAbility {
    pub base_damage: f64,
    pub cooldown: f64,
    pub duration: f64,
    pub spirit_scaling: f64,
}

impl UpgradedAbility {
    fn base(ability: &HeroAbility) -> Self {
        UpgradedAbility {
            base_damage: ability.base_damage,
            cooldown: ability.cooldown,
            duration: ability.duration,
            spirit_scaling: ability.spirit_scaling,
        }
    }

    /// The ability with the given tiers applied, or its base numbers when no tiers are given.
    pub fn of(ability: &HeroAbility, tiers: Option<&Vec<i64>>) -> Self {
        match tiers {
            Some(t) if !t.is_empty() => apply_ability_upgrades(ability, t),
            _ => Self::base(ability),
        }
    }
}

/// Apply upgrade bonuses for the tiers in `active_tiers`.
///
/// For DPS abilities, a duration change rescales total damage and spirit scaling
/// proportionally (same per-second rate over the new duration). `EAddToScale`
/// upgrades modify spirit scaling rather than adding flat damage.
pub fn apply_ability_upgrades(ability: &HeroAbility, active_tiers: &[i64]) -> UpgradedAbility {
    let mut u = UpgradedAbility::base(ability);
    let mut tiers = active_tiers.to_vec();
    tiers.sort();

    for tier in tiers {
        let Some(upgrade) = ability.upgrades.iter().find(|x| x.tier == tier) else { continue };
        for pu in &upgrade.property_upgrades {
            let name = crate::models::str_of(pu, "name");
            let Some(bonus) = pu.get("bonus").map_or(Some(0.0), num) else { continue };
            let upgrade_type = crate::models::str_of(pu, "upgrade_type");

            // EAddToScale on DPS keys → spirit scaling modification.
            if upgrade_type == "EAddToScale" && DPS_UPGRADE_KEYS.contains(&name) {
                if ability.is_dps && u.duration > 0.0 {
                    u.spirit_scaling += bonus * u.duration;
                } else {
                    u.spirit_scaling += bonus;
                }
                continue;
            }

            if DAMAGE_UPGRADE_KEYS.contains(&name) {
                u.base_damage += bonus;
            } else if DPS_UPGRADE_KEYS.contains(&name) {
                if u.duration > 0.0 {
                    u.base_damage += bonus * u.duration;
                } else {
                    u.base_damage += bonus;
                }
            } else if name == "AbilityCooldown" {
                u.cooldown += bonus; // bonus is negative (e.g. -12)
            } else if name == "AbilityDuration" || name == "AbilityChannelTime" {
                let old_duration = u.duration;
                u.duration += bonus;
                if ability.is_dps && old_duration > 0.0 && u.duration > 0.0 {
                    let scale = u.duration / old_duration;
                    u.base_damage *= scale;
                    u.spirit_scaling *= scale;
                }
            }
        }
    }

    UpgradedAbility {
        base_damage: u.base_damage.max(0.0),
        cooldown: u.cooldown.max(MIN_COOLDOWN),
        duration: u.duration.max(0.0),
        spirit_scaling: u.spirit_scaling,
    }
}

/// Pellets that hit a single target per shot.
pub fn effective_pellets(hero: &HeroStats) -> i64 {
    if hero.max_pellets_per_target > 0 {
        hero.pellets.min(hero.max_pellets_per_target)
    } else {
        hero.pellets
    }
}

/// Per-bullet damage at a boon count.
pub fn bullet_damage_at_boon(hero: &HeroStats, boons: i64) -> f64 {
    hero.base_bullet_damage + hero.damage_gain * boons as f64
}

/// Effective fire rate (bullets per second).
pub fn fire_rate_with_bonus(hero: &HeroStats, fire_rate_bonus: f64) -> f64 {
    hero.base_fire_rate * (1.0 + fire_rate_bonus)
}

/// Magazine size with ammo bonuses. `ammo_increase` is a multiplier (1.0 = double).
pub fn effective_magazine(hero: &HeroStats, ammo_increase: f64, ammo_flat: i64) -> i64 {
    if hero.base_ammo <= 0 {
        return 0;
    }
    ((hero.base_ammo as f64 * (1.0 + ammo_increase)).ceil() as i64 + ammo_flat).max(1)
}

/// Combined shred from multiple sources: additive, clamped to [0, 1].
pub fn total_shred(shred_sources: &[f64]) -> f64 {
    shred_sources.iter().sum::<f64>().clamp(0.0, 1.0)
}

/// Total weapon damage bonus including golden statues and conditional assumptions.
fn total_weapon_bonus(config: &CombatConfig) -> f64 {
    let mut weapon_bonus = config.weapon_damage_bonus;
    if config.golden_weapon_total > 0.0 {
        weapon_bonus += config.golden_weapon_total;
    } else if config.golden_buffs_count > 0 {
        // ~5% per buff, split three ways.
        weapon_bonus += config.golden_buffs_count as f64 / 3.0 * 0.05;
    }
    if config.berserker_stacks > 0 {
        weapon_bonus += config.berserker_stacks as f64 * 0.07;
    }
    if config.intensifying_mag_pct > 0.0 {
        weapon_bonus += config.intensifying_mag_pct;
    }
    if config.opening_rounds_active {
        weapon_bonus += 0.45;
    }
    if config.close_range_active {
        weapon_bonus += 0.50; // Point Blank (strongest close-range item)
    }
    if config.long_range_active {
        weapon_bonus += 0.70; // Sharpshooter (strongest long-range item)
    }
    weapon_bonus
}

/// Full bullet damage calculation.
///
/// 1. damage per shot = ((base + boon scaling) × (1 + weapon bonus) + flat) × pellets
/// 2. bullets per second = fire rate × (1 + fire rate bonus)
/// 3. final DPS = raw DPS × falloff × (1 + bullet amp) × (1 − resist after shred)
/// 4. sustained DPS additionally accounts for reload downtime
pub fn calculate_bullet(hero: &HeroStats, config: &CombatConfig) -> BulletResult {
    let weapon_bonus = total_weapon_bonus(config);
    let scaled_dmg = bullet_damage_at_boon(hero, config.boons);
    let dmg_per_bullet =
        (scaled_dmg * (1.0 + weapon_bonus) + config.flat_weapon_bonus) * effective_pellets(hero) as f64;

    let bps = fire_rate_with_bonus(hero, config.fire_rate_bonus);
    let raw_dps = dmg_per_bullet * bps;

    let mag_size = effective_magazine(hero, config.ammo_increase, config.ammo_flat);
    let dmg_per_mag = dmg_per_bullet * mag_size as f64;
    let magdump_time = if bps > 0.0 && mag_size > 0 { mag_size as f64 / bps } else { 0.0 };

    let t_shred = total_shred(&config.shred);
    let f_resist = resist_after_shred(config.enemy_bullet_resist, t_shred);
    let falloff = falloff_multiplier(config.distance, hero.falloff_range_min, hero.falloff_range_max);
    let bullet_amp = 1.0 + config.target_bullet_damage_amp;

    let final_dps = raw_dps * falloff * bullet_amp * (1.0 - f_resist);

    let reload_time = hero.reload_duration.max(0.0);
    let cycle_time = magdump_time + reload_time;
    let sustained_dps = if cycle_time > 0.0 && mag_size > 0 {
        dmg_per_mag * falloff * bullet_amp * (1.0 - f_resist) / cycle_time
    } else {
        final_dps
    };

    BulletResult {
        damage_per_bullet: dmg_per_bullet,
        bullets_per_second: bps,
        raw_dps,
        final_dps,
        sustained_dps,
        magazine_size: mag_size,
        damage_per_magazine: dmg_per_mag,
        magdump_time,
        reload_time,
        total_shred: t_shred,
        final_resist: f_resist,
    }
}

/// Spirit/ability damage calculation.
///
/// raw = base + spirit multiplier × spirit; spirit amp (including Escalating
/// Exposure stacks) and damage amp are separate multipliers; resist applies last.
pub fn calculate_spirit(ability: &AbilityConfig) -> SpiritResult {
    let spirit_contribution = ability.spirit_multiplier * ability.current_spirit;
    let raw_damage = ability.base_damage + spirit_contribution;

    let ee_amp = ability.escalating_exposure_stacks as f64 * ability.ee_per_stack;
    let total_spirit_amp = 1.0 + ability.spirit_amp + ee_amp;
    let damage_amp = 1.0 + ability.crippling + ability.soulshredder;
    let modified_raw = raw_damage * total_spirit_amp * damage_amp;

    let effective_shred = (ability.resist_shred + ability.mystic_vuln).min(1.0);
    let effective_resist = (ability.enemy_spirit_resist * (1.0 - effective_shred)).max(0.0);
    let modified_damage = modified_raw * (1.0 - effective_resist);

    let total_duration = ability.ability_duration + ability.bonus_duration;
    // Instant damage is treated as a single hit.
    let dps = if total_duration > 0.0 { modified_damage / total_duration } else { modified_damage };

    SpiritResult { raw_damage, modified_damage, spirit_contribution, dps, total_dot_damage: modified_damage }
}

/// Realistic DPS factoring accuracy and headshots.
pub fn dps_with_accuracy(hero: &HeroStats, config: &CombatConfig) -> f64 {
    let result = calculate_bullet(hero, config);
    let base_hit_dps = result.final_dps * config.accuracy;
    let headshot_bonus =
        result.final_dps * config.accuracy * config.headshot_rate * (config.headshot_multiplier - 1.0);
    base_hit_dps + headshot_bonus
}

/// Attacker/defender spirit context shared by the ability calculations.
#[derive(Debug, Clone, Default)]
pub struct SpiritContext {
    pub current_spirit: f64,
    pub cooldown_reduction: f64,
    pub spirit_amp: f64,
    pub enemy_spirit_resist: f64,
    pub resist_shred: f64,
}

fn effective_cooldown(cooldown: f64, cooldown_reduction: f64) -> f64 {
    (cooldown * (1.0 - cooldown_reduction)).max(MIN_COOLDOWN)
}

/// Spirit result for an ability whose numbers are already resolved; `extra_base`
/// is added on top of the (possibly upgraded) base damage.
fn ability_result(u: UpgradedAbility, extra_base: f64, ctx: &SpiritContext) -> SpiritResult {
    let eff_cd = effective_cooldown(u.cooldown, ctx.cooldown_reduction);
    let mut result = calculate_spirit(&AbilityConfig {
        base_damage: u.base_damage + extra_base,
        spirit_multiplier: u.spirit_scaling,
        current_spirit: ctx.current_spirit,
        cooldown: eff_cd,
        ability_duration: u.duration,
        enemy_spirit_resist: ctx.enemy_spirit_resist,
        resist_shred: ctx.resist_shred,
        spirit_amp: ctx.spirit_amp,
        ..Default::default()
    });
    // An instant ability with a cooldown deals its damage once per cooldown.
    if u.cooldown > 0.0 && u.duration == 0.0 {
        result.dps = result.modified_damage / eff_cd;
    }
    result
}

/// Spirit DPS for a specific hero ability, with optional upgrade tiers applied.
pub fn calculate_ability_spirit_dps(
    ability: &HeroAbility,
    ctx: &SpiritContext,
    upgrade_tiers: Option<&Vec<i64>>,
) -> SpiritResult {
    ability_result(UpgradedAbility::of(ability, upgrade_tiers), 0.0, ctx)
}

/// Weapon-side context needed for melee-scaled abilities.
#[derive(Debug, Clone, Default)]
pub struct MeleeContext {
    pub boons: i64,
    pub weapon_damage_bonus: f64,
    pub melee_damage_pct: f64,
}

/// DPS of one ability inside the hero total, or `None` if it deals no damage.
pub fn ability_dps_in_total(
    hero: &HeroStats,
    index: usize,
    ctx: &SpiritContext,
    ability_upgrades: Option<&AbilityUpgrades>,
    melee: &MeleeContext,
) -> Option<SpiritResult> {
    let ability = hero.abilities.get(index)?;
    if ability.base_damage <= 0.0 && ability.melee_scale <= 0.0 {
        return None;
    }
    let tiers = ability_upgrades.and_then(|m| m.get(&index));
    let u = UpgradedAbility::of(ability, tiers);
    // Melee-scaled abilities add a share of the hero's light melee damage to their base.
    let melee_base = if ability.melee_scale > 0.0 {
        let melee_boon = hero.damage_gain * melee.boons as f64;
        let melee_weapon = melee.weapon_damage_bonus * MELEE_WEAPON_SCALE;
        (hero.light_melee_damage + melee_boon) * (1.0 + melee_weapon + melee.melee_damage_pct) * ability.melee_scale
    } else {
        0.0
    };
    Some(ability_result(u, melee_base, ctx))
}

/// Total spirit DPS from all of a hero's damaging abilities.
pub fn hero_total_spirit_dps(
    hero: &HeroStats,
    ctx: &SpiritContext,
    ability_upgrades: Option<&AbilityUpgrades>,
    melee: &MeleeContext,
) -> f64 {
    (0..hero.abilities.len())
        .filter_map(|i| ability_dps_in_total(hero, i, ctx, ability_upgrades, melee))
        .map(|r| r.dps)
        .sum()
}

/// Inputs for a melee calculation.
#[derive(Debug, Clone, Default)]
pub struct MeleeParams {
    pub boons: i64,
    pub weapon_damage_bonus: f64,
    pub enemy_bullet_resist: f64,
    pub shred_sources: Vec<f64>,
    pub melee_damage_pct: f64,
    pub heavy_melee_damage_pct: f64,
}

/// Unresisted (light, heavy) melee damage per hit.
pub fn melee_damage_raw(
    hero: &HeroStats,
    boons: i64,
    weapon_damage_bonus: f64,
    melee_damage_pct: f64,
    heavy_melee_damage_pct: f64,
) -> (f64, f64) {
    // Melee base values scale with boons via the same damage_gain as bullets.
    let boon_scaling = hero.damage_gain * boons as f64;
    let weapon = weapon_damage_bonus * MELEE_WEAPON_SCALE;
    (
        (hero.light_melee_damage + boon_scaling) * (1.0 + weapon + melee_damage_pct),
        (hero.heavy_melee_damage + boon_scaling) * (1.0 + weapon + melee_damage_pct + heavy_melee_damage_pct),
    )
}

/// Melee damage: scales with weapon damage at 50% and is reduced by bullet resist.
pub fn calculate_melee(hero: &HeroStats, p: &MeleeParams) -> MeleeResult {
    let (light, heavy) =
        melee_damage_raw(hero, p.boons, p.weapon_damage_bonus, p.melee_damage_pct, p.heavy_melee_damage_pct);
    let resist_mult = 1.0 - resist_after_shred(p.enemy_bullet_resist, total_shred(&p.shred_sources));
    let (light, heavy) = (light * resist_mult, heavy * resist_mult);
    MeleeResult {
        light_damage: light,
        heavy_damage: heavy,
        light_dps: light / LIGHT_MELEE_CYCLE,
        heavy_dps: heavy / HEAVY_MELEE_CYCLE,
    }
}

/// Inputs for an individual item's damage calculation.
#[derive(Debug, Clone, Default)]
pub struct ItemDamageParams {
    pub current_spirit: f64,
    pub boons: i64,
    pub weapon_damage_bonus: f64,
    pub enemy_spirit_resist: f64,
    pub enemy_bullet_resist: f64,
    pub spirit_resist_shred: f64,
    pub bullet_resist_shred: f64,
    pub spirit_amp: f64,
}

/// DPS for an individual damage-dealing item, or `None` if it deals no damage.
///
/// Scaling follows the property's scale function: `ETechPower` scales with
/// spirit, `ELevelUpBoons` with boons, `EBaseWeaponDamage` with weapon damage.
pub fn calculate_item_damage(item: &Item, p: &ItemDamageParams) -> Option<ItemDamageResult> {
    if item.raw_properties.is_empty() {
        return None;
    }
    let info = extract_item_damage(&item.raw_properties)?;

    let mut spirit_contribution = 0.0;
    let mut boon_contribution = 0.0;
    let (scaled_damage, damage_type, scaled_from) = match info.scale_type.as_str() {
        "ETechPower" => {
            spirit_contribution = info.stat_scale * p.current_spirit;
            ((info.base_damage + spirit_contribution) * (1.0 + p.spirit_amp), "spirit", "spirit")
        }
        "ELevelUpBoons" => {
            boon_contribution = info.stat_scale * p.boons as f64;
            (info.base_damage + boon_contribution, "bullet", "boons")
        }
        "EBaseWeaponDamage" => (info.base_damage * (1.0 + p.weapon_damage_bonus), "bullet", "weapon"),
        _ => (info.base_damage, "spirit", "none"),
    };

    let (resist, shred) = if damage_type == "spirit" {
        (p.enemy_spirit_resist, p.spirit_resist_shred)
    } else {
        (p.enemy_bullet_resist, p.bullet_resist_shred)
    };
    let effective_resist = (resist * (1.0 - shred.min(1.0))).max(0.0);
    let final_damage = scaled_damage * (1.0 - effective_resist);

    let dps = if !info.is_dps && info.proc_cooldown > 0.0 {
        let chance = if info.proc_chance > 0.0 { (info.proc_chance / 100.0).min(1.0) } else { 1.0 };
        final_damage * chance / info.proc_cooldown
    } else {
        // Already expressed as DPS, or single-hit / unknown timing.
        final_damage
    };

    Some(ItemDamageResult {
        item_name: item.name.clone(),
        damage_per_hit: final_damage,
        dps,
        damage_type: damage_type.to_string(),
        scaled_from: scaled_from.to_string(),
        spirit_contribution,
        boon_contribution,
    })
}

/// Ability damage using boon-derived spirit power (`spirit_gain × boons + bonus_spirit`).
pub fn calculate_ability_damage(
    ability: &HeroAbility,
    hero: &HeroStats,
    boons: i64,
    bonus_spirit: f64,
    ctx: &SpiritContext,
) -> AbilityDamageResult {
    let current_spirit = hero.spirit_gain * boons as f64 + bonus_spirit;
    let ctx = SpiritContext { current_spirit: current_spirit.trunc(), ..ctx.clone() };
    let result = calculate_ability_spirit_dps(ability, &ctx, None);
    AbilityDamageResult {
        ability_name: ability.name.clone(),
        raw_damage: result.raw_damage,
        modified_damage: result.modified_damage,
        spirit_contribution: result.spirit_contribution,
        dps: result.dps,
        effective_cooldown: effective_cooldown(ability.cooldown, ctx.cooldown_reduction),
        boons,
        current_spirit,
    }
}

/// Damage for all of a hero's damaging abilities at a boon level.
pub fn hero_ability_breakdown(
    hero: &HeroStats,
    boons: i64,
    bonus_spirit: f64,
    ctx: &SpiritContext,
) -> Vec<AbilityDamageResult> {
    hero.abilities
        .iter()
        .filter(|a| a.base_damage > 0.0)
        .map(|a| calculate_ability_damage(a, hero, boons, bonus_spirit, ctx))
        .collect()
}
