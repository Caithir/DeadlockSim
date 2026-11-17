//! Whole-build analysis: one summary of a hero + build + souls, and the views
//! derived from it (power curves, range curves, matchup tables, comparisons).

use std::collections::HashSet;

use indexmap::IndexMap;
use serde::Serialize;

use crate::data::souls_to_boons;
use crate::models::{Build, BuildStats, BulletResult, HeroStats, Item};

use super::builds::{
    aggregate_stats, build_to_attacker_config, defender_effective_hp, resist_weighted_ehp, total_spirit,
    AttackerOptions,
};
use super::damage::{calculate_bullet, hero_total_spirit_dps, AbilityUpgrades, MeleeContext, SpiritContext};
use super::heroes::ttk;
use super::primitives::falloff_multiplier;

/// A hero with a build and everything needed to evaluate it.
#[derive(Debug, Clone)]
pub struct BuildContext<'a> {
    pub hero: &'a HeroStats,
    pub items: Vec<Item>,
    /// Souls gathered beyond what was spent on items.
    pub extra_souls: i64,
    pub ability_upgrades: AbilityUpgrades,
    pub accuracy: f64,
    pub headshot_rate: f64,
    /// Stat fields whose conditional (triggered) values count.
    pub conditionals: Option<HashSet<String>>,
    /// Use this boon count instead of deriving it from total souls.
    pub boons_override: Option<i64>,
}

impl<'a> BuildContext<'a> {
    pub fn new(hero: &'a HeroStats, items: Vec<Item>) -> Self {
        BuildContext {
            hero,
            items,
            extra_souls: 0,
            ability_upgrades: AbilityUpgrades::new(),
            accuracy: 1.0,
            headshot_rate: 0.0,
            conditionals: None,
            boons_override: None,
        }
    }

    pub fn item_cost(&self) -> i64 {
        self.items.iter().map(|i| i.cost).sum()
    }

    pub fn total_souls(&self) -> i64 {
        self.item_cost() + self.extra_souls.max(0)
    }

    /// Boon count: the override, or derived from total souls gathered.
    pub fn boons(&self) -> i64 {
        self.boons_override.unwrap_or_else(|| souls_to_boons(self.total_souls()))
    }

    /// The same context with a different item list.
    pub fn with_items(&self, items: Vec<Item>) -> Self {
        BuildContext { items, ..self.clone() }
    }
}

/// Headline numbers for a build.
#[derive(Debug, Clone, Serialize)]
pub struct BuildSummary {
    pub total_souls: i64,
    pub item_cost: i64,
    pub boons: i64,
    /// Sustained gun DPS (including reloads), before accuracy.
    pub gun_dps: f64,
    /// Summed DPS of all damaging abilities used on cooldown.
    pub spirit_dps: f64,
    pub combined_dps: f64,
    /// HP + shields.
    pub hp_pool: f64,
    /// HP pool weighted by bullet/spirit resist.
    pub effective_hp: f64,
    pub hp_regen: f64,
    pub spirit_power: i64,
    pub stats: BuildStats,
    pub bullet: BulletResult,
}

/// Evaluate a build context into its headline numbers.
pub fn summarize(ctx: &BuildContext) -> BuildSummary {
    let hero = ctx.hero;
    let boons = ctx.boons();
    let stats = aggregate_stats(&Build::new(ctx.items.clone()), ctx.conditionals.as_ref());
    let config = build_to_attacker_config(
        &stats,
        &AttackerOptions {
            boons,
            spirit_gain: hero.spirit_gain,
            accuracy: ctx.accuracy,
            headshot_rate: ctx.headshot_rate,
            headshot_multiplier: hero.crit_bonus_start,
            ..Default::default()
        },
    );
    let bullet = calculate_bullet(hero, &config);
    let spirit_power = total_spirit(&stats, boons, hero.spirit_gain);
    let spirit_dps = hero_total_spirit_dps(
        hero,
        &SpiritContext {
            current_spirit: spirit_power as f64,
            cooldown_reduction: stats.cooldown_reduction,
            spirit_amp: stats.spirit_amp_pct,
            enemy_spirit_resist: 0.0,
            resist_shred: stats.spirit_resist_shred,
        },
        Some(&ctx.ability_upgrades),
        &MeleeContext { boons, weapon_damage_bonus: stats.weapon_damage_pct, melee_damage_pct: stats.melee_damage_pct },
    );
    let gun_dps = if bullet.raw_dps > 0.0 { bullet.sustained_dps } else { 0.0 };
    BuildSummary {
        total_souls: ctx.total_souls(),
        item_cost: ctx.item_cost(),
        boons,
        gun_dps,
        spirit_dps,
        combined_dps: gun_dps + spirit_dps,
        hp_pool: defender_effective_hp(hero, &stats, boons),
        effective_hp: resist_weighted_ehp(hero, boons, &stats),
        hp_regen: hero.base_regen + stats.hp_regen,
        spirit_power,
        stats,
        bullet,
    }
}

/// "Gun", "Spirit" or "Hybrid" by the share of DPS that comes from the gun.
pub fn classify_build_type(gun_dps: f64, spirit_dps: f64) -> &'static str {
    let total = gun_dps + spirit_dps;
    if total < 0.01 {
        return "Hybrid";
    }
    let gun_ratio = gun_dps / total;
    if gun_ratio > 0.70 {
        "Gun"
    } else if gun_ratio < 0.30 {
        "Spirit"
    } else {
        "Hybrid"
    }
}

// ── Power curve ────────────────────────────────────────────────────

/// Build strength after a purchase.
#[derive(Debug, Clone, Serialize)]
pub struct CurvePoint {
    /// Item bought at this step ("" for the starting point).
    pub item: String,
    pub souls: i64,
    pub boons: i64,
    pub gun_dps: f64,
    pub spirit_dps: f64,
    pub effective_hp: f64,
}

/// Strength of the build after each purchase, buying `ctx.items` in order.
///
/// Souls at each step are the cost of the items bought so far, so boons grow
/// along the curve the way they would in a match.
pub fn power_curve(ctx: &BuildContext) -> Vec<CurvePoint> {
    let mut points = Vec::with_capacity(ctx.items.len() + 1);
    for n in 0..=ctx.items.len() {
        let step = BuildContext { extra_souls: 0, boons_override: None, ..ctx.with_items(ctx.items[..n].to_vec()) };
        let s = summarize(&step);
        points.push(CurvePoint {
            item: if n == 0 { String::new() } else { ctx.items[n - 1].name.clone() },
            souls: s.total_souls,
            boons: s.boons,
            gun_dps: s.gun_dps,
            spirit_dps: s.spirit_dps,
            effective_hp: s.effective_hp,
        });
    }
    points
}

/// Relative strength of a summary against a baseline: DPS ratio × EHP ratio.
fn power_index(s: &BuildSummary, base: &BuildSummary) -> f64 {
    let dps = if base.combined_dps > 0.0 { s.combined_dps / base.combined_dps } else { 1.0 };
    let ehp = if base.effective_hp > 0.0 { s.effective_hp / base.effective_hp } else { 1.0 };
    dps * ehp
}

/// Reorder a build's items into an efficient purchase order: at each step buy
/// the item with the best power gain per soul, given what is already owned.
pub fn suggest_purchase_order(ctx: &BuildContext) -> Vec<Item> {
    let mut remaining = ctx.items.clone();
    let mut ordered: Vec<Item> = Vec::with_capacity(remaining.len());
    let at = |items: &[Item]| {
        summarize(&BuildContext { extra_souls: 0, boons_override: None, ..ctx.with_items(items.to_vec()) })
    };
    let base = at(&[]);
    while !remaining.is_empty() {
        let current = power_index(&at(&ordered), &base);
        let mut best = 0;
        let mut best_rate = f64::NEG_INFINITY;
        for (i, item) in remaining.iter().enumerate() {
            let mut test = ordered.clone();
            test.push(item.clone());
            let rate = (power_index(&at(&test), &base) - current) / item.cost.max(1) as f64;
            if rate > best_rate {
                best_rate = rate;
                best = i;
            }
        }
        ordered.push(remaining.remove(best));
    }
    ordered
}

// ── Range curve ────────────────────────────────────────────────────

/// Gun DPS at a distance.
#[derive(Debug, Clone, Serialize)]
pub struct RangePoint {
    pub distance: f64,
    /// Fraction of full damage dealt at this distance.
    pub multiplier: f64,
    pub dps: f64,
}

/// Sustained gun DPS from 0 to `max_distance` meters in `step`-meter increments.
pub fn range_curve(ctx: &BuildContext, max_distance: f64, step: f64) -> Vec<RangePoint> {
    let s = summarize(ctx);
    let hero = ctx.hero;
    // The summary's DPS is at the default engagement distance; rescale from point blank.
    let default_mult = falloff_multiplier(
        crate::models::CombatConfig::default().distance,
        hero.falloff_range_min,
        hero.falloff_range_max,
    );
    let point_blank = if default_mult > 0.0 { s.gun_dps / default_mult } else { 0.0 };
    let step = step.max(0.5);
    let n = (max_distance / step).floor() as i64;
    (0..=n)
        .map(|i| {
            let distance = i as f64 * step;
            let multiplier = falloff_multiplier(distance, hero.falloff_range_min, hero.falloff_range_max);
            RangePoint { distance, multiplier, dps: point_blank * multiplier }
        })
        .collect()
}

// ── Matchups ───────────────────────────────────────────────────────

/// A gun duel between the built hero and an item-less opponent at equal boons.
#[derive(Debug, Clone, Serialize)]
pub struct Matchup {
    pub opponent: String,
    pub opponent_hp: f64,
    /// Seconds for the built hero to kill the opponent (accuracy + reloads).
    pub time_to_kill: f64,
    /// Seconds for the opponent's base gun to kill the built hero.
    pub time_to_die: f64,
    /// `time_to_die − time_to_kill`: positive means the built hero wins the duel.
    pub margin: f64,
    pub one_mag: bool,
}

/// Gun-duel matchups of a build against every hero, best margin first.
///
/// Opponents have no items and the same boon count; both sides use the
/// context's accuracy and headshot rate.
pub fn matchups(ctx: &BuildContext, heroes: &IndexMap<String, HeroStats>) -> Vec<Matchup> {
    let me = summarize(ctx);
    let boons = me.boons;
    let mut out: Vec<Matchup> = heroes
        .values()
        .map(|opp| {
            let my_cfg = build_to_attacker_config(
                &me.stats,
                &AttackerOptions {
                    boons,
                    spirit_gain: ctx.hero.spirit_gain,
                    accuracy: ctx.accuracy,
                    headshot_rate: ctx.headshot_rate,
                    headshot_multiplier: ctx.hero.crit_bonus_start,
                    enemy_hp: opp.hp_at(boons),
                    ..Default::default()
                },
            );
            let kill = ttk(ctx.hero, opp, &my_cfg);
            let their_cfg = build_to_attacker_config(
                &BuildStats::default(),
                &AttackerOptions {
                    boons,
                    spirit_gain: opp.spirit_gain,
                    accuracy: ctx.accuracy,
                    headshot_rate: ctx.headshot_rate,
                    headshot_multiplier: opp.crit_bonus_start,
                    enemy_bullet_resist: me.stats.bullet_resist_pct,
                    enemy_hp: me.hp_pool,
                    ..Default::default()
                },
            );
            let die = ttk(opp, ctx.hero, &their_cfg);
            // A hero with no gun data never kills: treat as an unbounded duel.
            let time_to_kill = if kill.realistic_ttk > 0.0 { kill.realistic_ttk } else { f64::INFINITY };
            let time_to_die = if die.realistic_ttk > 0.0 { die.realistic_ttk } else { f64::INFINITY };
            let margin = match (time_to_kill.is_finite(), time_to_die.is_finite()) {
                (true, true) => time_to_die - time_to_kill,
                (true, false) => f64::INFINITY,
                (false, true) => f64::NEG_INFINITY,
                (false, false) => 0.0,
            };
            Matchup {
                opponent: opp.name.clone(),
                opponent_hp: kill.target_hp,
                time_to_kill,
                time_to_die,
                margin,
                one_mag: kill.can_one_mag && time_to_kill.is_finite(),
            }
        })
        .collect();
    out.sort_by(|a, b| b.margin.total_cmp(&a.margin));
    out
}

// ── Build comparison ───────────────────────────────────────────────

/// One line of a build-vs-build comparison.
#[derive(Debug, Clone, Serialize)]
pub struct CompareRow {
    pub label: String,
    pub a: f64,
    pub b: f64,
    pub delta: f64,
    /// "num", "pct" or "int": how the values should be displayed.
    pub fmt: &'static str,
    /// Whether a larger value is better (false for costs).
    pub higher_is_better: bool,
}

/// Side-by-side comparison of two evaluated builds.
pub fn compare_builds(a: &BuildSummary, b: &BuildSummary) -> Vec<CompareRow> {
    let row = |label: &str, x: f64, y: f64, fmt: &'static str, higher_is_better: bool| CompareRow {
        label: label.to_string(),
        a: x,
        b: y,
        delta: y - x,
        fmt,
        higher_is_better,
    };
    let (sa, sb) = (&a.stats, &b.stats);
    let rows = vec![
        row("Souls", a.total_souls as f64, b.total_souls as f64, "int", false),
        row("Boons", a.boons as f64, b.boons as f64, "int", true),
        row("Gun DPS", a.gun_dps, b.gun_dps, "num", true),
        row("Spirit DPS", a.spirit_dps, b.spirit_dps, "num", true),
        row("Combined DPS", a.combined_dps, b.combined_dps, "num", true),
        row("HP + Shields", a.hp_pool, b.hp_pool, "num", true),
        row("Effective HP", a.effective_hp, b.effective_hp, "num", true),
        row("HP Regen", a.hp_regen, b.hp_regen, "num", true),
        row("Bullet Damage", a.bullet.damage_per_bullet, b.bullet.damage_per_bullet, "num", true),
        row("Shots/s", a.bullet.bullets_per_second, b.bullet.bullets_per_second, "num", true),
        row("Magazine", a.bullet.magazine_size as f64, b.bullet.magazine_size as f64, "int", true),
        row("Spirit Power", a.spirit_power as f64, b.spirit_power as f64, "int", true),
        row("Weapon Damage", sa.weapon_damage_pct, sb.weapon_damage_pct, "pct", true),
        row("Fire Rate", sa.fire_rate_pct, sb.fire_rate_pct, "pct", true),
        row("Bullet Resist", sa.bullet_resist_pct, sb.bullet_resist_pct, "pct", true),
        row("Spirit Resist", sa.spirit_resist_pct, sb.spirit_resist_pct, "pct", true),
        row("Bullet Lifesteal", sa.bullet_lifesteal, sb.bullet_lifesteal, "pct", true),
        row("Spirit Lifesteal", sa.spirit_lifesteal, sb.spirit_lifesteal, "pct", true),
        row("Cooldown Reduction", sa.cooldown_reduction, sb.cooldown_reduction, "pct", true),
        row("Spirit Amp", sa.spirit_amp_pct, sb.spirit_amp_pct, "pct", true),
        row("Bullet Shred", sa.bullet_resist_shred, sb.bullet_resist_shred, "pct", true),
        row("Spirit Shred", sa.spirit_resist_shred, sb.spirit_resist_shred, "pct", true),
    ];
    // Keep the headline rows always; drop detail rows that are zero on both sides.
    rows.into_iter().enumerate().filter(|(i, r)| *i < 8 || r.a != 0.0 || r.b != 0.0).map(|(_, r)| r).collect()
}
