//! Item scoring: how much DPS / EHP each candidate item adds to a baseline build.
//!
//! Supports a fast analytical mode and full simulation modes.

use std::collections::{HashMap, HashSet};

use indexmap::IndexMap;
use serde::Serialize;

use crate::models::{Build, BuildStats, HeroStats, Item};

use super::builds::{aggregate_stats, build_to_attacker_config, resist_weighted_ehp, AttackerOptions};
use super::damage::{calculate_bullet, hero_total_spirit_dps, AbilityUpgrades, MeleeContext, SpiritContext};
use super::simulation::{run_simulation, AbilityUse, SimConfig, SimSettings};

/// How candidate items are scored.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScoreMode {
    /// Analytical DPS/EHP only (no simulation).
    Fast,
    /// Simulation with weapon only.
    SimGun,
    /// Simulation with abilities only.
    SimSpirit,
    /// Simulation with both.
    SimHybrid,
}

impl ScoreMode {
    pub fn parse(s: &str) -> Option<ScoreMode> {
        Some(match s {
            "fast" => ScoreMode::Fast,
            "sim_gun" | "gun" => ScoreMode::SimGun,
            "sim_spirit" | "spirit" => ScoreMode::SimSpirit,
            "sim_hybrid" | "hybrid" => ScoreMode::SimHybrid,
            _ => return None,
        })
    }
}

/// Advanced settings for item scoring.
#[derive(Debug, Clone, Default)]
pub struct ScoringConfig {
    pub sim_settings: Option<SimSettings>,
    pub ability_schedule: Vec<AbilityUse>,
    pub ability_upgrades: AbilityUpgrades,
    /// DPS-equivalent values assigned to utility items (simulation modes).
    pub custom_item_dps: HashMap<String, f64>,
    /// EHP-equivalent values assigned to utility items (simulation modes).
    pub custom_item_ehp: HashMap<String, f64>,
    pub enabled_conditionals: Option<HashSet<String>>,
}

/// All computed metrics for a single candidate item.
#[derive(Debug, Clone, Default, Serialize)]
pub struct ItemScore {
    pub item_name: String,
    // Fast-mode deltas
    pub dps_delta: f64,
    pub spirit_dps_delta: f64,
    pub ehp_delta: f64,
    pub dps_per_soul: f64,
    pub ehp_per_soul: f64,
    // Simulation-mode deltas
    pub sim_dps_delta: f64,
    pub sim_ehp_delta: f64,
    pub sim_dps: f64,
    pub sim_ehp: f64,
    pub sim_dps_per_soul: f64,
    pub sim_ehp_per_soul: f64,
}

/// HP of the stationary target used for simulation scoring.
const DUMMY_HP: f64 = 2500.0;
/// Simulation scoring caps the fight length for responsiveness.
const MAX_SCORING_DURATION: f64 = 10.0;

/// Gun (sustained) DPS, spirit DPS and resist-weighted EHP of a build.
fn analytic(hero: &HeroStats, stats: &BuildStats, boons: i64, cfg: &ScoringConfig) -> (f64, f64, f64) {
    let combat = build_to_attacker_config(
        stats,
        &AttackerOptions { boons, spirit_gain: hero.spirit_gain, ..Default::default() },
    );
    let gun = calculate_bullet(hero, &combat).sustained_dps;
    let upgrades = (!cfg.ability_upgrades.is_empty()).then_some(&cfg.ability_upgrades);
    let spirit = hero_total_spirit_dps(
        hero,
        &SpiritContext {
            current_spirit: combat.current_spirit as f64,
            cooldown_reduction: stats.cooldown_reduction,
            spirit_amp: stats.spirit_amp_pct,
            enemy_spirit_resist: 0.0,
            resist_shred: stats.spirit_resist_shred,
        },
        upgrades,
        &MeleeContext::default(),
    );
    (gun, spirit, resist_weighted_ehp(hero, boons, stats))
}

/// A candidate purchase: the item and the build that results from buying it.
#[derive(Debug, Clone)]
pub struct Trial {
    pub item_name: String,
    /// Souls the purchase costs (used for the per-soul metrics).
    pub cost: i64,
    pub build: Build,
}

/// Score each candidate item against `baseline_build`. Returns item name → score.
pub fn score_candidates(
    hero: &HeroStats,
    baseline_build: &Build,
    candidates: &[&Item],
    boons: i64,
    mode: ScoreMode,
    cfg: &ScoringConfig,
) -> IndexMap<String, ItemScore> {
    let trials: Vec<Trial> = candidates
        .iter()
        .map(|item| Trial { item_name: item.name.clone(), cost: item.cost, build: baseline_build.with(item) })
        .collect();
    score_trials(hero, baseline_build, &trials, boons, mode, cfg)
}

/// Score prepared trial builds against `baseline_build`. Returns item name → score.
pub fn score_trials(
    hero: &HeroStats,
    baseline_build: &Build,
    trials: &[Trial],
    boons: i64,
    mode: ScoreMode,
    cfg: &ScoringConfig,
) -> IndexMap<String, ItemScore> {
    let conds = cfg.enabled_conditionals.as_ref();
    let per_soul = |cost: i64| if cost != 0 { cost as f64 } else { 1.0 };
    if mode == ScoreMode::Fast {
        let (cur_gun, cur_spirit, cur_ehp) = analytic(hero, &aggregate_stats(baseline_build, conds), boons, cfg);
        return trials
            .iter()
            .map(|t| {
                let (gun, spirit, ehp) = analytic(hero, &aggregate_stats(&t.build, conds), boons, cfg);
                let cost = per_soul(t.cost);
                let score = ItemScore {
                    item_name: t.item_name.clone(),
                    dps_delta: gun - cur_gun,
                    spirit_dps_delta: spirit - cur_spirit,
                    ehp_delta: ehp - cur_ehp,
                    dps_per_soul: (gun - cur_gun) / cost,
                    ehp_per_soul: (ehp - cur_ehp) / cost,
                    ..Default::default()
                };
                (t.item_name.clone(), score)
            })
            .collect();
    }

    let mut settings = cfg.sim_settings.clone().unwrap_or_default();
    settings.attacker_boons = boons;
    settings.defender_boons = 0;
    match mode {
        ScoreMode::SimGun => settings.ability_uptime = 0.0,
        ScoreMode::SimSpirit => {
            settings.weapon_uptime = 0.0;
            settings.ability_uptime = 1.0;
        }
        _ => {}
    }
    settings.duration = settings.duration.min(MAX_SCORING_DURATION);

    let dummy = HeroStats::dummy("Dummy Target", DUMMY_HP);
    let sim_dps = |build: Build| -> f64 {
        run_simulation(&SimConfig {
            attacker: hero.clone(),
            attacker_build: build,
            defender: dummy.clone(),
            settings: settings.clone(),
            ability_schedule: cfg.ability_schedule.clone(),
            attacker_ability_upgrades: cfg.ability_upgrades.clone(),
            ..Default::default()
        })
        .overall_dps
    };

    let base_dps = sim_dps(baseline_build.clone());
    let base_ehp = resist_weighted_ehp(hero, boons, &aggregate_stats(baseline_build, conds));

    trials
        .iter()
        .map(|t| {
            let test_ehp = resist_weighted_ehp(hero, boons, &aggregate_stats(&t.build, conds));
            let test_dps = sim_dps(t.build.clone());
            let cost = per_soul(t.cost);
            let dps_delta = test_dps - base_dps + cfg.custom_item_dps.get(&t.item_name).copied().unwrap_or(0.0);
            let ehp_delta = test_ehp - base_ehp + cfg.custom_item_ehp.get(&t.item_name).copied().unwrap_or(0.0);
            let score = ItemScore {
                item_name: t.item_name.clone(),
                sim_dps_delta: dps_delta,
                sim_ehp_delta: ehp_delta,
                sim_dps: test_dps,
                sim_ehp: test_ehp,
                sim_dps_per_soul: dps_delta / cost,
                sim_ehp_per_soul: ehp_delta / cost,
                ..Default::default()
            };
            (t.item_name.clone(), score)
        })
        .collect()
}
