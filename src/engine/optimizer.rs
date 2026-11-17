//! Goal-driven build optimizer.
//!
//! Unlike the greedy gun optimizers in [`super::builds`], this one scores whole
//! builds (gun, abilities and survivability together), understands component
//! upgrades, and refines its greedy pick with a swap-based local search.

use indexmap::IndexMap;
use serde::Serialize;

use crate::models::Item;

use super::analysis::{summarize, BuildContext, BuildSummary};
use super::builds::MAX_ITEMS;
use super::components::{add_item, AddOutcome};

/// What the optimizer maximizes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Goal {
    /// Sustained gun DPS.
    Gun,
    /// Ability DPS.
    Spirit,
    /// Gun + ability DPS.
    Damage,
    /// Resist-weighted effective HP.
    Tank,
    /// Damage × survivability.
    Balanced,
}

impl Goal {
    pub const ALL: [(&'static str, Goal); 5] = [
        ("gun", Goal::Gun),
        ("spirit", Goal::Spirit),
        ("damage", Goal::Damage),
        ("tank", Goal::Tank),
        ("balanced", Goal::Balanced),
    ];

    pub fn parse(s: &str) -> Option<Goal> {
        let s = s.to_lowercase();
        match s.as_str() {
            "dps" => Some(Goal::Gun),
            "ehp" => Some(Goal::Tank),
            "combined" => Some(Goal::Damage),
            _ => Goal::ALL.iter().find(|(n, _)| *n == s).map(|(_, g)| *g),
        }
    }

    fn value(self, s: &BuildSummary, base: &BuildSummary) -> f64 {
        match self {
            Goal::Gun => s.gun_dps,
            Goal::Spirit => s.spirit_dps,
            Goal::Damage => s.combined_dps,
            Goal::Tank => s.effective_hp,
            Goal::Balanced => {
                let dps = if base.combined_dps > 0.0 { s.combined_dps / base.combined_dps } else { 1.0 };
                let ehp = if base.effective_hp > 0.0 { s.effective_hp / base.effective_hp } else { 1.0 };
                dps * ehp
            }
        }
    }
}

/// Optimizer settings.
#[derive(Debug, Clone)]
pub struct OptimizeParams {
    pub goal: Goal,
    /// Total souls available, including what the starting items cost.
    pub budget: i64,
    pub max_items: usize,
    /// Highest item tier to consider (legendary items are tier 5).
    pub max_tier: i64,
    /// Skip items whose stats only apply under a condition.
    pub exclude_conditional: bool,
}

impl Default for OptimizeParams {
    fn default() -> Self {
        OptimizeParams {
            goal: Goal::Balanced,
            budget: 15000,
            max_items: MAX_ITEMS,
            max_tier: 4,
            exclude_conditional: false,
        }
    }
}

/// An optimized build with its before/after numbers.
#[derive(Debug, Clone, Serialize)]
pub struct OptimizeResult {
    pub goal: Goal,
    pub budget: i64,
    pub items: Vec<String>,
    pub total_cost: i64,
    /// Items the caller started with (kept in the build).
    pub locked: Vec<String>,
    pub before: BuildSummary,
    pub after: BuildSummary,
}

/// A candidate purchase ranked for the current build.
#[derive(Debug, Clone, Serialize)]
pub struct Recommendation {
    pub item: String,
    pub cost: i64,
    /// Souls actually paid after component discounts.
    pub purchase_cost: i64,
    pub consumes: Vec<String>,
    pub gun_dps_delta: f64,
    pub spirit_dps_delta: f64,
    pub ehp_delta: f64,
    /// Gain in the goal's objective.
    pub gain: f64,
    pub gain_per_1k: f64,
}

/// Evaluates builds for a hero at a fixed soul total (so boons stay constant
/// while items are shuffled within the budget).
struct Evaluator<'a> {
    ctx: &'a BuildContext<'a>,
    goal: Goal,
    budget: i64,
    base: BuildSummary,
}

/// Summary of `items` on the context's hero with the soul total pinned to `budget`.
fn summary_at(ctx: &BuildContext, items: &[Item], budget: i64) -> BuildSummary {
    let cost: i64 = items.iter().map(|i| i.cost).sum();
    summarize(&BuildContext { extra_souls: (budget - cost).max(0), ..ctx.with_items(items.to_vec()) })
}

impl<'a> Evaluator<'a> {
    fn new(ctx: &'a BuildContext<'a>, goal: Goal, budget: i64) -> Self {
        Evaluator { ctx, goal, budget, base: summary_at(ctx, &[], budget) }
    }

    fn summary(&self, items: &[Item]) -> BuildSummary {
        summary_at(self.ctx, items, self.budget)
    }

    fn score(&self, items: &[Item]) -> f64 {
        self.goal.value(&self.summary(items), &self.base)
    }
}

fn cost_of(items: &[Item]) -> i64 {
    items.iter().map(|i| i.cost).sum()
}

fn candidates<'a>(items: &'a IndexMap<String, Item>, p: &OptimizeParams) -> Vec<&'a Item> {
    items
        .values()
        .filter(|i| i.tier <= p.max_tier && i.cost <= p.budget)
        .filter(|i| !(p.exclude_conditional && !i.condition.is_empty()))
        .collect()
}

/// Minimum relative improvement for a change to count (guards against float noise).
const EPS: f64 = 1e-9;
/// Upper bound on local-search passes.
const MAX_PASSES: usize = 40;

/// Find a strong build for `ctx.hero` within a soul budget.
///
/// `ctx.items` are kept as a locked starting point. The search first adds the
/// item with the best objective gain per soul until nothing affordable helps,
/// then repeatedly applies the best single swap or addition until no change
/// improves the objective.
pub fn optimize(ctx: &BuildContext, items: &IndexMap<String, Item>, p: &OptimizeParams) -> OptimizeResult {
    let eval = Evaluator::new(ctx, p.goal, p.budget);
    let pool = candidates(items, p);
    let locked: Vec<String> = ctx.items.iter().map(|i| i.name.clone()).collect();
    let mut build: Vec<Item> = ctx.items.clone();
    let before = eval.summary(&build);

    // Applies `item` to a copy of the build; None if it cannot be added within limits.
    let try_add = |build: &[Item], item: &Item| -> Option<Vec<Item>> {
        let mut next = build.to_vec();
        match add_item(&mut next, item, items) {
            AddOutcome::Added { consumed } => {
                // Never consume an item the caller locked in.
                if consumed.iter().any(|c| locked.contains(c)) {
                    return None;
                }
                (next.len() <= p.max_items && cost_of(&next) <= p.budget).then_some(next)
            }
            _ => None,
        }
    };

    // Phase 1: greedy by gain per soul.
    loop {
        let current = eval.score(&build);
        let mut best: Option<(f64, Vec<Item>)> = None;
        for item in &pool {
            let Some(next) = try_add(&build, item) else { continue };
            let gain = eval.score(&next) - current;
            let paid = (cost_of(&next) - cost_of(&build)).max(1) as f64;
            let rate = gain / paid;
            if gain > EPS * current.abs().max(1.0) && best.as_ref().is_none_or(|(r, _)| rate > *r) {
                best = Some((rate, next));
            }
        }
        match best {
            Some((_, next)) => build = next,
            None => break,
        }
    }

    // Phase 2: local search — best single swap (or addition) by absolute gain.
    for _ in 0..MAX_PASSES {
        let current = eval.score(&build);
        let mut best: Option<(f64, Vec<Item>)> = None;
        let mut consider = |next: Vec<Item>| {
            let score = eval.score(&next);
            if score > current + EPS * current.abs().max(1.0) && best.as_ref().is_none_or(|(s, _)| score > *s) {
                best = Some((score, next));
            }
        };
        for item in &pool {
            if let Some(next) = try_add(&build, item) {
                consider(next);
            }
            for i in 0..build.len() {
                if locked.contains(&build[i].name) {
                    continue;
                }
                let mut without = build.clone();
                without.remove(i);
                if let Some(next) = try_add(&without, item) {
                    consider(next);
                }
            }
        }
        match best {
            Some((_, next)) => build = next,
            None => break,
        }
    }

    let after = eval.summary(&build);
    OptimizeResult {
        goal: p.goal,
        budget: p.budget,
        items: build.iter().map(|i| i.name.clone()).collect(),
        total_cost: cost_of(&build),
        locked,
        before,
        after,
    }
}

/// Rank the purchases available right now for a build.
///
/// `available_souls` limits candidates to those affordable after component
/// discounts (`None` = no limit). Results are ordered by objective gain per soul.
pub fn recommend(
    ctx: &BuildContext,
    items: &IndexMap<String, Item>,
    goal: Goal,
    available_souls: Option<i64>,
    max_tier: i64,
    limit: usize,
) -> Vec<Recommendation> {
    // Souls are spent, not gained, by a purchase: keep the soul total fixed.
    let total = ctx.total_souls();
    let eval = Evaluator::new(ctx, goal, total.max(ctx.item_cost()));
    let now = eval.summary(&ctx.items);
    let now_score = goal.value(&now, &eval.base);

    let mut recs: Vec<Recommendation> = items
        .values()
        .filter(|i| i.tier <= max_tier)
        .filter_map(|item| {
            let mut next = ctx.items.clone();
            let AddOutcome::Added { consumed } = add_item(&mut next, item, items) else { return None };
            let paid = cost_of(&next) - cost_of(&ctx.items);
            if available_souls.is_some_and(|s| paid > s) {
                return None;
            }
            // When the purchase exceeds current souls, assume the souls are earned first.
            let after =
                summarize(&BuildContext { extra_souls: (total - cost_of(&next)).max(0), ..ctx.with_items(next) });
            let gain = goal.value(&after, &eval.base) - now_score;
            Some(Recommendation {
                item: item.name.clone(),
                cost: item.cost,
                purchase_cost: paid,
                consumes: consumed,
                gun_dps_delta: after.gun_dps - now.gun_dps,
                spirit_dps_delta: after.spirit_dps - now.spirit_dps,
                ehp_delta: after.effective_hp - now.effective_hp,
                gain,
                gain_per_1k: gain / paid.max(1) as f64 * 1000.0,
            })
        })
        .filter(|r| r.gain > 0.0)
        .collect();
    recs.sort_by(|a, b| b.gain_per_1k.total_cmp(&a.gain_per_1k));
    recs.truncate(limit);
    recs
}
