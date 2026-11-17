//! Hero comparison engine: side-by-side comparisons, rankings and TTK matrices.

use indexmap::IndexMap;
use serde::Serialize;

use crate::models::{CombatConfig, HeroStats};

use super::heroes::{growth_percentage, snapshot, ttk};
use crate::data::MAX_BOONS;

/// Side-by-side comparison of two heroes at a given boon level.
#[derive(Debug, Clone, Serialize)]
pub struct HeroComparison {
    pub boon_level: i64,
    pub hero_a_name: String,
    pub hero_a_dps: f64,
    pub hero_a_hp: f64,
    pub hero_a_dpm: f64,
    pub hero_b_name: String,
    pub hero_b_dps: f64,
    pub hero_b_hp: f64,
    pub hero_b_dpm: f64,
    /// a / b
    pub dps_ratio: f64,
    pub hp_ratio: f64,
    pub dpm_ratio: f64,
}

/// A hero's rank in a specific stat category.
#[derive(Debug, Clone, Serialize)]
pub struct RankEntry {
    pub hero_name: String,
    pub value: f64,
    pub rank: i64,
}

/// Stats accepted by [`rank_heroes`].
pub const RANK_STATS: &[&str] = &["dps", "hp", "dpm", "bullet_damage", "fire_rate", "dps_growth", "hp_growth"];

fn ratio(a: f64, b: f64) -> f64 {
    if b != 0.0 {
        a / b
    } else {
        0.0
    }
}

/// Direct comparison of two heroes at a boon level.
pub fn compare_two(hero_a: &HeroStats, hero_b: &HeroStats, boon_level: i64) -> HeroComparison {
    let a = snapshot(hero_a, boon_level);
    let b = snapshot(hero_b, boon_level);
    HeroComparison {
        boon_level,
        hero_a_name: hero_a.name.clone(),
        hero_a_dps: a.dps,
        hero_a_hp: a.hp,
        hero_a_dpm: a.dpm,
        hero_b_name: hero_b.name.clone(),
        hero_b_dps: b.dps,
        hero_b_hp: b.hp,
        hero_b_dpm: b.dpm,
        dps_ratio: ratio(a.dps, b.dps),
        hp_ratio: ratio(a.hp, b.hp),
        dpm_ratio: ratio(a.dpm, b.dpm),
    }
}

/// Compare two heroes across all boon levels.
pub fn compare_curve(hero_a: &HeroStats, hero_b: &HeroStats, max_boons: i64) -> Vec<HeroComparison> {
    (0..=max_boons).map(|b| compare_two(hero_a, hero_b, b)).collect()
}

/// Rank all heroes by a stat at a boon level. Unknown stats produce an empty list.
pub fn rank_heroes(
    heroes: &IndexMap<String, HeroStats>,
    stat: &str,
    boon_level: i64,
    ascending: bool,
) -> Vec<RankEntry> {
    if !RANK_STATS.contains(&stat) {
        return Vec::new();
    }
    let mut entries: Vec<(&String, f64)> = heroes
        .iter()
        .map(|(name, hero)| {
            let snap = snapshot(hero, boon_level);
            let value = match stat {
                "dps" => snap.dps,
                "hp" => snap.hp,
                "dpm" => snap.dpm,
                "bullet_damage" => snap.bullet_damage,
                "fire_rate" => hero.base_fire_rate,
                "dps_growth" => growth_percentage(hero, MAX_BOONS).dps_growth,
                _ => growth_percentage(hero, MAX_BOONS).hp_growth,
            };
            (name, value)
        })
        .collect();
    // Stable sort; descending keeps the original order among ties.
    if ascending {
        entries.sort_by(|a, b| a.1.total_cmp(&b.1));
    } else {
        entries.sort_by(|a, b| b.1.total_cmp(&a.1));
    }
    entries
        .into_iter()
        .enumerate()
        .map(|(i, (name, value))| RankEntry { hero_name: name.clone(), value, rank: i as i64 + 1 })
        .collect()
}

/// NxN ideal-TTK matrix: `matrix[attacker][defender] = seconds`.
pub fn cross_ttk_matrix(
    heroes: &IndexMap<String, HeroStats>,
    config: &CombatConfig,
    hero_names: Option<&[String]>,
) -> IndexMap<String, IndexMap<String, f64>> {
    let names: Vec<String> = match hero_names {
        Some(n) if !n.is_empty() => n.to_vec(),
        _ => {
            let mut v: Vec<String> = heroes.keys().cloned().collect();
            v.sort();
            v
        }
    };
    let mut matrix = IndexMap::new();
    for atk in names.iter().filter(|n| heroes.contains_key(*n)) {
        let row: IndexMap<String, f64> = names
            .iter()
            .filter(|n| heroes.contains_key(*n))
            .map(|def| (def.clone(), ttk(&heroes[atk], &heroes[def], config).ttk_seconds))
            .collect();
        matrix.insert(atk.clone(), row);
    }
    matrix
}
