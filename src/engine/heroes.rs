//! Hero metrics: boon scaling and time-to-kill analysis.

use serde::Serialize;

use crate::models::{CombatConfig, HeroStats, ScalingSnapshot, TtkResult};

use super::damage::{bullet_damage_at_boon, calculate_bullet, dps_with_accuracy};
use super::primitives::falloff_multiplier;

/// A hero's stats at a specific boon level.
pub fn snapshot(hero: &HeroStats, boon_level: i64) -> ScalingSnapshot {
    let bullet_dmg = bullet_damage_at_boon(hero, boon_level);
    let per_bullet = bullet_dmg * hero.pellets as f64;
    ScalingSnapshot {
        boon_level,
        bullet_damage: bullet_dmg,
        hp: hero.hp_at(boon_level),
        spirit: hero.spirit_gain * boon_level as f64,
        dps: per_bullet * hero.base_fire_rate,
        dpm: per_bullet * hero.base_ammo as f64,
    }
}

/// Full scaling curve from boon 0 to `max_boons`.
pub fn scaling_curve(hero: &HeroStats, max_boons: i64) -> Vec<ScalingSnapshot> {
    (0..=max_boons).map(|b| snapshot(hero, b)).collect()
}

/// Percentage growth from base to max boons.
#[derive(Debug, Clone, Copy, Default, Serialize)]
pub struct Growth {
    pub dps_growth: f64,
    pub hp_growth: f64,
    pub aggregate_growth: f64,
}

pub fn growth_percentage(hero: &HeroStats, max_boons: i64) -> Growth {
    if hero.base_dps == 0.0 || hero.base_hp == 0.0 {
        return Growth::default();
    }
    let max_bullet = hero.base_bullet_damage + hero.damage_gain * max_boons as f64;
    let max_dps = max_bullet * hero.pellets as f64 * hero.base_fire_rate;
    let dps_growth = (max_dps - hero.base_dps) / hero.base_dps;
    let hp_growth = (hero.hp_at(max_boons) - hero.base_hp) / hero.base_hp;
    Growth { dps_growth, hp_growth, aggregate_growth: dps_growth + hp_growth }
}

/// Item scaling with boons: `(boon_level, base_effect + boon_bonus × boon_level)`.
pub fn item_boon_scaling(base_effect: f64, boon_bonus: f64, max_boons: i64) -> Vec<(i64, f64)> {
    (0..=max_boons).map(|b| (b, base_effect + boon_bonus * b as f64)).collect()
}

/// Safety cap on magazines walked by the step-by-step TTK.
const MAX_MAGS: i64 = 200;

/// Time-to-kill for attacker vs defender.
///
/// The realistic TTK walks through fire→reload cycles bullet by bullet, with
/// accuracy and headshots applied as expected values.
pub fn ttk(attacker: &HeroStats, defender: &HeroStats, config: &CombatConfig) -> TtkResult {
    let bullet = calculate_bullet(attacker, config);

    let mut target_hp = if config.enemy_hp > 0.0 { config.enemy_hp } else { defender.hp_at(config.boons) };
    target_hp += config.enemy_bonus_hp;

    let ideal_ttk = if bullet.final_dps > 0.0 { target_hp / bullet.final_dps } else { 0.0 };
    let realistic_dps = dps_with_accuracy(attacker, config);

    // damage_per_bullet / damage_per_magazine don't include falloff.
    let falloff = falloff_multiplier(config.distance, attacker.falloff_range_min, attacker.falloff_range_max);
    let (acc, hs_rate, hs_mult) = (config.accuracy, config.headshot_rate, config.headshot_multiplier);
    let resist_mult = 1.0 - bullet.final_resist;

    let effective_dmg_per_mag = bullet.damage_per_magazine * falloff * resist_mult;
    let realistic_dmg_per_mag =
        effective_dmg_per_mag * acc + effective_dmg_per_mag * acc * hs_rate * (hs_mult - 1.0);

    let mut can_one_mag = realistic_dmg_per_mag > 0.0 && realistic_dmg_per_mag >= target_hp;
    let mut mags_needed = if realistic_dmg_per_mag > 0.0 {
        if can_one_mag {
            1
        } else {
            (target_hp / realistic_dmg_per_mag).ceil() as i64
        }
    } else {
        0
    };

    let realistic_ttk = if realistic_dmg_per_mag > 0.0 && bullet.bullets_per_second > 0.0 {
        // Expected damage per bullet after falloff, resist, accuracy and headshots.
        let dmg_per_bullet = bullet.damage_per_bullet * falloff * resist_mult * acc
            + bullet.damage_per_bullet * falloff * resist_mult * acc * hs_rate * (hs_mult - 1.0);
        let time_per_bullet = 1.0 / bullet.bullets_per_second;
        let mut remaining_hp = target_hp;
        let mut elapsed = 0.0;
        let mut mags_used = 0;
        while remaining_hp > 0.0 && mags_used < MAX_MAGS {
            mags_used += 1;
            for _ in 0..bullet.magazine_size {
                remaining_hp -= dmg_per_bullet;
                elapsed += time_per_bullet;
                if remaining_hp <= 0.0 {
                    break;
                }
            }
            if remaining_hp > 0.0 {
                elapsed += bullet.reload_time;
            }
        }
        mags_needed = mags_used;
        can_one_mag = mags_needed <= 1;
        elapsed.max(0.0)
    } else if realistic_dps > 0.0 {
        target_hp / realistic_dps
    } else {
        0.0
    };

    TtkResult {
        ttk_seconds: ideal_ttk,
        realistic_ttk,
        magazines_needed: mags_needed,
        can_one_mag,
        effective_dps: bullet.final_dps,
        realistic_dps,
        target_hp,
        damage_per_magazine: bullet.damage_per_magazine,
    }
}

/// TTK at each boon level (both combatants at the same boon count).
pub fn ttk_curve(
    attacker: &HeroStats,
    defender: &HeroStats,
    base_config: &CombatConfig,
    max_boons: i64,
) -> Vec<(i64, TtkResult)> {
    (0..=max_boons)
        .map(|boon| {
            let config = CombatConfig {
                boons: boon,
                weapon_damage_bonus: base_config.weapon_damage_bonus,
                fire_rate_bonus: base_config.fire_rate_bonus,
                ammo_increase: base_config.ammo_increase,
                shred: base_config.shred.clone(),
                current_spirit: base_config.current_spirit,
                spirit_amp: base_config.spirit_amp,
                accuracy: base_config.accuracy,
                headshot_rate: base_config.headshot_rate,
                headshot_multiplier: base_config.headshot_multiplier,
                enemy_bullet_resist: base_config.enemy_bullet_resist,
                enemy_spirit_resist: base_config.enemy_spirit_resist,
                enemy_hp: 0.0,
                enemy_bonus_hp: base_config.enemy_bonus_hp,
                ..Default::default()
            };
            (boon, ttk(attacker, defender, &config))
        })
        .collect()
}
