//! Build engine: aggregate item stats and evaluate builds.

use std::collections::HashSet;

use indexmap::IndexMap;

use crate::data::SHOP_TIER_DATA;
use crate::models::{Build, BuildResult, BuildStats, CombatConfig, HeroStats, Item};

use super::damage::calculate_bullet;
use super::heroes::ttk;

/// Maximum number of item slots in a build.
pub const MAX_ITEMS: usize = 12;

/// Shop bonus category column in [`SHOP_TIER_DATA`].
#[derive(Debug, Clone, Copy)]
pub enum ShopBonus {
    Weapon,
    Vitality,
    Spirit,
}

/// Shop tier bonus for a category spend: the value at the highest threshold reached.
pub fn shop_tier_bonus(category_cost: i64, kind: ShopBonus) -> f64 {
    SHOP_TIER_DATA
        .iter()
        .take_while(|row| category_cost >= row.0)
        .last()
        .map(|row| match kind {
            ShopBonus::Weapon => row.1,
            ShopBonus::Vitality => row.2,
            ShopBonus::Spirit => row.3,
        })
        .unwrap_or(0) as f64
}

/// Per-category soul spend: (weapon, vitality, spirit).
fn category_costs(build: &Build) -> (i64, i64, i64) {
    let mut c = (0, 0, 0);
    for item in &build.items {
        match item.category.to_lowercase().as_str() {
            "weapon" => c.0 += item.cost,
            "vitality" => c.1 += item.cost,
            "spirit" => c.2 += item.cost,
            _ => {}
        }
    }
    c
}

/// Sum all item stats in a build.
///
/// Resistances stack multiplicatively (`1 − Π(1 − Rᵢ)`); everything else is
/// additive. Shop tier bonuses are applied per category spend: weapon → weapon
/// damage %, vitality → base HP %, spirit → flat spirit power.
///
/// Conditional stats are included only for the field names in `enabled_conditionals`.
pub fn aggregate_stats(build: &Build, enabled_conditionals: Option<&HashSet<String>>) -> BuildStats {
    let mut bs = BuildStats::default();
    let mut bullet_resist_mult = 1.0;
    let mut spirit_resist_mult = 1.0;
    for item in &build.items {
        bs.weapon_damage_pct += item.weapon_damage_pct;
        bs.fire_rate_pct += item.fire_rate_pct;
        bs.ammo_flat += item.ammo_flat;
        bs.ammo_pct += item.ammo_pct;
        if item.bullet_resist_pct != 0.0 {
            bullet_resist_mult *= 1.0 - item.bullet_resist_pct;
        }
        if item.spirit_resist_pct != 0.0 {
            spirit_resist_mult *= 1.0 - item.spirit_resist_pct;
        }
        bs.bonus_hp += item.bonus_hp;
        bs.spirit_power += item.spirit_power;
        bs.bullet_lifesteal += item.bullet_lifesteal;
        bs.spirit_lifesteal += item.spirit_lifesteal;
        bs.hp_regen += item.hp_regen;
        bs.bullet_shield += item.bullet_shield;
        bs.spirit_shield += item.spirit_shield;
        bs.headshot_bonus += item.headshot_bonus;
        bs.bullet_resist_shred += item.bullet_resist_shred;
        bs.spirit_resist_shred += item.spirit_resist_shred;
        bs.cooldown_reduction += item.cooldown_reduction;
        bs.item_cooldown_reduction += item.item_cooldown_reduction;
        bs.spirit_amp_pct += item.spirit_amp_pct;
        bs.spirit_power_pct += item.spirit_power_pct;
        bs.melee_damage_pct += item.melee_damage_pct;
        bs.heavy_melee_damage_pct += item.heavy_melee_damage_pct;
        if let Some(enabled) = enabled_conditionals {
            for (stat_name, &cval) in &item.conditional_stats {
                if !enabled.contains(stat_name) {
                    continue;
                }
                match stat_name.as_str() {
                    "bullet_resist_pct" => {
                        if cval != 0.0 {
                            bullet_resist_mult *= 1.0 - cval;
                        }
                    }
                    "spirit_resist_pct" => {
                        if cval != 0.0 {
                            spirit_resist_mult *= 1.0 - cval;
                        }
                    }
                    _ => {
                        bs.add_stat(stat_name, cval);
                    }
                }
            }
        }
    }
    bs.bullet_resist_pct = 1.0 - bullet_resist_mult;
    bs.spirit_resist_pct = 1.0 - spirit_resist_mult;
    bs.total_cost = build.total_cost();
    (bs.weapon_cost, bs.vitality_cost, bs.spirit_cost) = category_costs(build);

    if bs.weapon_cost > 0 {
        bs.weapon_damage_pct += shop_tier_bonus(bs.weapon_cost, ShopBonus::Weapon) / 100.0;
    }
    if bs.vitality_cost > 0 {
        bs.base_hp_pct = shop_tier_bonus(bs.vitality_cost, ShopBonus::Vitality) / 100.0;
    }
    if bs.spirit_cost > 0 {
        bs.spirit_power += shop_tier_bonus(bs.spirit_cost, ShopBonus::Spirit);
    }
    bs
}

/// Stat fields reported by [`stat_breakdown`].
const BREAKDOWN_FIELDS: &[&str] = &[
    "weapon_damage_pct",
    "fire_rate_pct",
    "ammo_flat",
    "ammo_pct",
    "bonus_hp",
    "spirit_power",
    "bullet_lifesteal",
    "spirit_lifesteal",
    "hp_regen",
    "bullet_shield",
    "spirit_shield",
    "headshot_bonus",
    "bullet_resist_shred",
    "spirit_resist_shred",
    "cooldown_reduction",
    "item_cooldown_reduction",
    "spirit_amp_pct",
    "spirit_power_pct",
    "melee_damage_pct",
    "heavy_melee_damage_pct",
    "bullet_resist_pct",
    "spirit_resist_pct",
];

/// Per-source breakdown for each stat: field name → `(source label, value)` list.
pub type StatBreakdown = IndexMap<String, Vec<(String, f64)>>;

/// Where each stat in a build comes from (items, enabled conditionals, shop bonuses).
pub fn stat_breakdown(build: &Build, enabled_conditionals: Option<&HashSet<String>>) -> StatBreakdown {
    let mut bd: StatBreakdown = IndexMap::new();
    for item in &build.items {
        for &field in BREAKDOWN_FIELDS {
            let val = item.stat(field);
            if val != 0.0 {
                bd.entry(field.to_string()).or_default().push((item.name.clone(), val));
            }
        }
        if let Some(enabled) = enabled_conditionals {
            for (stat_name, &cval) in &item.conditional_stats {
                if enabled.contains(stat_name) && cval != 0.0 {
                    bd.entry(stat_name.clone()).or_default().push((format!("{} (cond)", item.name), cval));
                }
            }
        }
    }
    let (weapon_cost, vitality_cost, spirit_cost) = category_costs(build);
    let shop = [
        (weapon_cost, ShopBonus::Weapon, 100.0, "weapon_damage_pct", "Weapon Shop Bonus"),
        (vitality_cost, ShopBonus::Vitality, 100.0, "base_hp_pct", "Vitality Shop Bonus"),
        (spirit_cost, ShopBonus::Spirit, 1.0, "spirit_power", "Spirit Shop Bonus"),
    ];
    for (cost, kind, divisor, field, label) in shop {
        let bonus = shop_tier_bonus(cost, kind) / divisor;
        if cost > 0 && bonus != 0.0 {
            bd.entry(field.to_string()).or_default().push((label.to_string(), bonus));
        }
    }
    bd
}

/// Total spirit power: `(item spirit + spirit_gain × boons) × (1 + spirit power %)`, truncated.
pub fn total_spirit(build_stats: &BuildStats, boons: i64, spirit_gain: f64) -> i64 {
    ((build_stats.spirit_power + spirit_gain * boons as f64) * (1.0 + build_stats.spirit_power_pct)) as i64
}

/// Defender-side and accuracy inputs for [`build_to_attacker_config`].
#[derive(Debug, Clone)]
pub struct AttackerOptions {
    pub boons: i64,
    /// The hero's per-boon spirit power.
    pub spirit_gain: f64,
    pub accuracy: f64,
    pub headshot_rate: f64,
    /// Should come from `hero.crit_bonus_start`.
    pub headshot_multiplier: f64,
    pub enemy_bullet_resist: f64,
    pub enemy_hp: f64,
    pub enemy_bonus_hp: f64,
}

impl Default for AttackerOptions {
    fn default() -> Self {
        AttackerOptions {
            boons: 0,
            spirit_gain: 0.0,
            accuracy: 1.0,
            headshot_rate: 0.0,
            headshot_multiplier: 1.65,
            enemy_bullet_resist: 0.0,
            enemy_hp: 0.0,
            enemy_bonus_hp: 0.0,
        }
    }
}

/// Create a [`CombatConfig`] from aggregated build stats (attacker perspective).
pub fn build_to_attacker_config(build_stats: &BuildStats, o: &AttackerOptions) -> CombatConfig {
    CombatConfig {
        boons: o.boons,
        weapon_damage_bonus: build_stats.weapon_damage_pct,
        fire_rate_bonus: build_stats.fire_rate_pct,
        ammo_increase: build_stats.ammo_pct,
        ammo_flat: build_stats.ammo_flat,
        shred: if build_stats.bullet_resist_shred > 0.0 { vec![build_stats.bullet_resist_shred] } else { vec![] },
        current_spirit: total_spirit(build_stats, o.boons, o.spirit_gain),
        spirit_amp: build_stats.spirit_amp_pct,
        accuracy: o.accuracy,
        headshot_rate: o.headshot_rate,
        headshot_multiplier: o.headshot_multiplier,
        enemy_bullet_resist: o.enemy_bullet_resist,
        enemy_hp: o.enemy_hp,
        enemy_bonus_hp: o.enemy_bonus_hp,
        ..Default::default()
    }
}

/// HP pool including build bonuses and shields (no resist weighting).
pub fn defender_effective_hp(hero: &HeroStats, stats: &BuildStats, boons: i64) -> f64 {
    hero.hp_at(boons) * (1.0 + stats.base_hp_pct) + stats.bonus_hp + stats.bullet_shield + stats.spirit_shield
}

/// Effective HP weighted by resistances: the pool divided by (1 − bullet resist),
/// then blended half-and-half with the spirit-resist multiplier. Resists cap at 90%.
pub fn resist_weighted_ehp(hero: &HeroStats, boons: i64, stats: &BuildStats) -> f64 {
    let mut ehp = defender_effective_hp(hero, stats, boons);
    if stats.bullet_resist_pct > 0.0 {
        ehp /= 1.0 - stats.bullet_resist_pct.min(0.9);
    }
    if stats.spirit_resist_pct > 0.0 {
        let spirit_mult = 1.0 / (1.0 - stats.spirit_resist_pct.min(0.9));
        ehp *= 0.5 + 0.5 * spirit_mult;
    }
    ehp
}

/// Inputs for [`evaluate_build`].
#[derive(Debug, Clone)]
pub struct EvalOptions<'a> {
    pub boons: i64,
    pub accuracy: f64,
    pub headshot_rate: f64,
    pub defender: Option<&'a HeroStats>,
    pub defender_build: Option<&'a Build>,
    pub enabled_conditionals: Option<&'a HashSet<String>>,
}

impl Default for EvalOptions<'_> {
    fn default() -> Self {
        EvalOptions {
            boons: 0,
            accuracy: 1.0,
            headshot_rate: 0.0,
            defender: None,
            defender_build: None,
            enabled_conditionals: None,
        }
    }
}

/// Evaluate a build for a hero, computing DPS and optional TTK against a defender.
pub fn evaluate_build(hero: &HeroStats, build: &Build, o: &EvalOptions) -> BuildResult {
    let build_stats = aggregate_stats(build, o.enabled_conditionals);

    let mut enemy_resist = 0.0;
    let mut enemy_hp = 0.0;
    if let Some(defender) = o.defender {
        let defender_bs = match o.defender_build {
            Some(b) if !b.items.is_empty() => aggregate_stats(b, o.enabled_conditionals),
            _ => BuildStats::default(),
        };
        enemy_resist = defender_bs.bullet_resist_pct;
        enemy_hp = defender_effective_hp(defender, &defender_bs, o.boons);
    }

    let config = build_to_attacker_config(
        &build_stats,
        &AttackerOptions {
            boons: o.boons,
            spirit_gain: hero.spirit_gain,
            accuracy: o.accuracy,
            headshot_rate: o.headshot_rate,
            headshot_multiplier: hero.crit_bonus_start,
            enemy_bullet_resist: enemy_resist,
            enemy_hp,
            enemy_bonus_hp: 0.0,
        },
    );

    let bullet_result = calculate_bullet(hero, &config);
    let ttk_result = match o.defender {
        Some(defender) if enemy_hp > 0.0 => Some(ttk(hero, defender, &config)),
        _ => None,
    };
    let effective_hp = defender_effective_hp(hero, &build_stats, o.boons);

    BuildResult {
        hero_name: hero.name.clone(),
        build: build.clone(),
        build_stats,
        bullet_result,
        ttk_result,
        spirit_dps: 0.0,
        combined_dps: 0.0,
        effective_hp,
    }
}

// ── Greedy gun optimizers ──────────────────────────────────────────

fn offensive_candidates<'a>(items: &'a IndexMap<String, Item>, budget: i64, exclude_conditional: bool) -> Vec<&'a Item> {
    items
        .values()
        .filter(|item| !(exclude_conditional && !item.condition.is_empty()))
        .filter(|item| item.cost <= budget)
        .filter(|item| {
            item.weapon_damage_pct > 0.0
                || item.fire_rate_pct > 0.0
                || item.ammo_flat > 0
                || item.ammo_pct > 0.0
                || item.bullet_resist_shred > 0.0
        })
        .collect()
}

/// Greedy: repeatedly add the unowned affordable candidate that `pick` prefers.
fn greedy<'a>(
    candidates: &[&'a Item],
    budget: i64,
    max_items: usize,
    mut pick: impl FnMut(&[Item], &[&'a Item]) -> Option<&'a Item>,
) -> Build {
    let mut selected: Vec<Item> = Vec::new();
    let mut remaining = budget;
    while selected.len() < max_items && !candidates.is_empty() {
        let affordable: Vec<&Item> = candidates
            .iter()
            .copied()
            .filter(|c| c.cost <= remaining && !selected.iter().any(|s| s.name == c.name))
            .collect();
        let Some(best) = pick(&selected, &affordable) else { break };
        remaining -= best.cost;
        selected.push(best.clone());
    }
    Build::new(selected)
}

/// Find a build that maximizes raw gun DPS within a budget (greedy by DPS gain).
pub fn best_dps_items(
    items: &IndexMap<String, Item>,
    hero: &HeroStats,
    budget: i64,
    boons: i64,
    max_items: usize,
    exclude_conditional: bool,
) -> Build {
    let raw_dps = |build_items: &[Item]| -> f64 {
        let stats = aggregate_stats(&Build::new(build_items.to_vec()), None);
        let cfg = build_to_attacker_config(
            &stats,
            &AttackerOptions {
                boons,
                spirit_gain: hero.spirit_gain,
                headshot_multiplier: hero.crit_bonus_start,
                ..Default::default()
            },
        );
        calculate_bullet(hero, &cfg).raw_dps
    };
    let candidates = offensive_candidates(items, budget, exclude_conditional);
    greedy(&candidates, budget, max_items, |selected, affordable| {
        let current = raw_dps(selected);
        let mut best = None;
        let mut best_gain = 0.0;
        for &item in affordable {
            let mut test = selected.to_vec();
            test.push(item.clone());
            let gain = raw_dps(&test) - current;
            if gain > best_gain {
                best_gain = gain;
                best = Some(item);
            }
        }
        best
    })
}

/// Find a build that minimizes realistic TTK within a budget (greedy).
#[allow(clippy::too_many_arguments)]
pub fn best_ttk_items(
    items: &IndexMap<String, Item>,
    hero: &HeroStats,
    defender: &HeroStats,
    budget: i64,
    boons: i64,
    accuracy: f64,
    headshot_rate: f64,
    max_items: usize,
    exclude_conditional: bool,
) -> Build {
    let candidates = offensive_candidates(items, budget, exclude_conditional);
    greedy(&candidates, budget, max_items, |selected, affordable| {
        let mut best = None;
        let mut best_ttk = f64::INFINITY;
        for &item in affordable {
            let mut test = selected.to_vec();
            test.push(item.clone());
            let result = evaluate_build(
                hero,
                &Build::new(test),
                &EvalOptions { boons, accuracy, headshot_rate, defender: Some(defender), ..Default::default() },
            );
            if let Some(t) = result.ttk_result {
                if t.realistic_ttk > 0.0 && t.realistic_ttk < best_ttk {
                    best_ttk = t.realistic_ttk;
                    best = Some(item);
                }
            }
        }
        best
    })
}
