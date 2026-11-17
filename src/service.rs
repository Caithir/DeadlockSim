//! Application layer: request types and operations shared by the web API, the
//! MCP server and the CLI. Everything here takes loaded [`GameData`] and
//! returns serializable results.

use std::collections::{BTreeMap, HashMap, HashSet};

use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::data::{self, GameData, ABILITY_TIER_COSTS};
use crate::engine::analysis::{self, classify_build_type, summarize, BuildContext, BuildSummary};
use crate::engine::builds::{self, build_to_attacker_config, defender_effective_hp, AttackerOptions, MAX_ITEMS};
use crate::engine::comparison;
use crate::engine::components::{self, AddOutcome};
use crate::engine::damage::{self, AbilityUpgrades, MeleeContext, SpiritContext};
use crate::engine::heroes;
use crate::engine::montecarlo::{monte_carlo_ttk, MonteCarloParams};
use crate::engine::optimizer::{self, Goal, OptimizeParams};
use crate::engine::scoring::{self, ScoreMode, ScoringConfig, Trial};
use crate::engine::simulation::{self, run_simulation, AbilityUse, DamageType, SimConfig, SimResult, SimSettings};
use crate::models::{Build, HeroStats, Item};
use crate::patchnotes;
use crate::presentation::{self, commas};
use crate::share::{self, SharedBuild};

pub type ServiceResult = Result<Value, String>;

// ── Settings ───────────────────────────────────────────────────────

/// User-tunable assumptions, shared by every calculation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub duration: f64,
    pub accuracy: f64,
    pub headshot_rate: f64,
    pub weapon_uptime: f64,
    pub ability_uptime: f64,
    pub active_item_uptime: f64,
    /// Engagement range in meters.
    pub distance: f64,
    pub weave_melee: bool,
    pub melee_after_reload: bool,
    pub reload_cancel_melee: bool,
    pub bidirectional: bool,
    // Which conditional (triggered) item stats count as active.
    pub cond_shred: bool,
    pub cond_weapon: bool,
    pub cond_spirit: bool,
    pub cond_defense: bool,
    pub cond_sustain: bool,
    /// Hero name → ability indices excluded from simulations.
    pub disabled_abilities: HashMap<String, Vec<usize>>,
    /// Hero name → ability indices in cast order.
    pub ability_priority: HashMap<String, Vec<usize>>,
    /// DPS / EHP equivalents assigned to utility items for simulation scoring.
    pub custom_item_dps: HashMap<String, f64>,
    pub custom_item_ehp: HashMap<String, f64>,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            duration: 15.0,
            accuracy: 0.65,
            headshot_rate: 0.10,
            weapon_uptime: 1.0,
            ability_uptime: 1.0,
            active_item_uptime: 1.0,
            distance: 20.0,
            weave_melee: false,
            melee_after_reload: true,
            reload_cancel_melee: false,
            bidirectional: false,
            cond_shred: true,
            cond_weapon: false,
            cond_spirit: false,
            cond_defense: false,
            cond_sustain: false,
            disabled_abilities: HashMap::new(),
            ability_priority: HashMap::new(),
            custom_item_dps: HashMap::new(),
            custom_item_ehp: HashMap::new(),
        }
    }
}

/// Conditional stat field → the settings category that enables it.
const COND_CATEGORIES: &[(&str, &str)] = &[
    ("bullet_resist_shred", "shred"),
    ("spirit_resist_shred", "shred"),
    ("weapon_damage_pct", "weapon"),
    ("fire_rate_pct", "weapon"),
    ("ammo_flat", "weapon"),
    ("ammo_pct", "weapon"),
    ("headshot_bonus", "weapon"),
    ("spirit_power", "spirit"),
    ("spirit_power_pct", "spirit"),
    ("spirit_amp_pct", "spirit"),
    ("cooldown_reduction", "spirit"),
    ("bullet_resist_pct", "defense"),
    ("spirit_resist_pct", "defense"),
    ("bonus_hp", "defense"),
    ("bullet_shield", "defense"),
    ("spirit_shield", "defense"),
    ("bullet_lifesteal", "sustain"),
    ("spirit_lifesteal", "sustain"),
    ("hp_regen", "sustain"),
];

impl Settings {
    /// Clamp every knob into its valid range.
    pub fn sanitized(mut self) -> Self {
        let unit = |v: f64| if v.is_finite() { v.clamp(0.0, 1.0) } else { 0.0 };
        self.duration = if self.duration.is_finite() { self.duration.clamp(1.0, 120.0) } else { 15.0 };
        self.accuracy = unit(self.accuracy);
        self.headshot_rate = unit(self.headshot_rate);
        self.weapon_uptime = unit(self.weapon_uptime);
        self.ability_uptime = if self.ability_uptime.is_finite() { self.ability_uptime.clamp(0.0, 2.0) } else { 1.0 };
        self.active_item_uptime =
            if self.active_item_uptime.is_finite() { self.active_item_uptime.clamp(0.0, 2.0) } else { 1.0 };
        self.distance = if self.distance.is_finite() { self.distance.clamp(0.0, 200.0) } else { 20.0 };
        self
    }

    /// Stat fields whose conditional values are enabled.
    pub fn conditionals(&self) -> HashSet<String> {
        COND_CATEGORIES
            .iter()
            .filter(|(_, cat)| match *cat {
                "shred" => self.cond_shred,
                "weapon" => self.cond_weapon,
                "spirit" => self.cond_spirit,
                "defense" => self.cond_defense,
                _ => self.cond_sustain,
            })
            .map(|(field, _)| field.to_string())
            .collect()
    }

    pub fn sim_settings(&self, attacker_boons: i64, defender_boons: i64) -> SimSettings {
        SimSettings {
            duration: self.duration,
            accuracy: self.accuracy,
            headshot_rate: self.headshot_rate,
            weapon_uptime: self.weapon_uptime,
            ability_uptime: self.ability_uptime,
            active_item_uptime: self.active_item_uptime,
            distance: self.distance,
            weave_melee: self.weave_melee,
            melee_after_reload: self.melee_after_reload,
            reload_cancel_melee: self.reload_cancel_melee,
            attacker_boons,
            defender_boons,
            bidirectional: self.bidirectional,
            ..Default::default()
        }
    }

    /// Ability schedule for a hero: enabled damaging abilities in priority order.
    pub fn ability_schedule(&self, hero: &HeroStats) -> Vec<AbilityUse> {
        let disabled: &[usize] = self.disabled_abilities.get(&hero.name).map(|v| v.as_slice()).unwrap_or(&[]);
        let mut schedulable: Vec<usize> = hero
            .abilities
            .iter()
            .enumerate()
            .filter(|(i, a)| !disabled.contains(i) && a.base_damage > 0.0 && a.cooldown > 0.0)
            .map(|(i, _)| i)
            .collect();
        if let Some(priority) = self.ability_priority.get(&hero.name).filter(|p| !p.is_empty()) {
            let mut ordered: Vec<usize> = Vec::new();
            for i in priority {
                if schedulable.contains(i) && !ordered.contains(i) {
                    ordered.push(*i);
                }
            }
            ordered.extend(schedulable.iter().filter(|i| !priority.contains(i)));
            schedulable = ordered;
        }
        schedulable
            .into_iter()
            .enumerate()
            .map(|(rank, idx)| AbilityUse {
                ability_index: idx,
                first_use: 0.1 * (rank as f64 + 1.0),
                use_on_cooldown: true,
            })
            .collect()
    }
}

// ── Build requests ─────────────────────────────────────────────────

/// A build as the client describes it.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct BuildSpec {
    pub hero: String,
    pub items: Vec<String>,
    pub extra_souls: i64,
    /// Ability index → highest purchased tier (1-3).
    pub ability_upgrades: BTreeMap<usize, i64>,
    /// Fixed boon count; derived from souls when absent.
    pub boons: Option<i64>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct BuildRequest {
    pub build: BuildSpec,
    pub settings: Settings,
}

/// `{index: max tier}` → `{index: [1..=max tier]}`.
pub fn tiers_map(upgrades: &BTreeMap<usize, i64>) -> AbilityUpgrades {
    upgrades.iter().filter(|(_, t)| **t > 0).map(|(i, t)| (*i, (1..=(*t).min(3)).collect())).collect()
}

impl BuildSpec {
    /// Resolve names into a [`BuildContext`].
    pub fn context<'a>(&self, data: &'a GameData, settings: &Settings) -> Result<BuildContext<'a>, String> {
        let hero = data.hero_or_err(&self.hero)?;
        if self.items.len() > 64 {
            return Err("Too many items in build.".into());
        }
        Ok(BuildContext {
            hero,
            items: data.resolve_items(&self.items)?,
            extra_souls: self.extra_souls.clamp(0, 1_000_000),
            ability_upgrades: tiers_map(&self.ability_upgrades),
            accuracy: settings.accuracy,
            headshot_rate: settings.headshot_rate,
            conditionals: Some(settings.conditionals()),
            boons_override: self.boons.map(|b| b.clamp(0, 100)),
        })
    }
}

fn ap_spent(upgrades: &BTreeMap<usize, i64>) -> i64 {
    upgrades.values().map(|&t| ABILITY_TIER_COSTS.iter().take(t.clamp(0, 3) as usize).sum::<i64>()).sum()
}

// ── Catalog ────────────────────────────────────────────────────────

/// Items with utility effects the simulator cannot model; users may assign
/// DPS/EHP-equivalent values to them in settings.
pub const UTILITY_ITEMS: &[(&str, &str)] = &[
    ("Knockdown", "Stun after channel"),
    ("Slowing Hex", "Movement slow"),
    ("Silence Wave", "AoE silence"),
    ("Disarming Hex", "Disarm + spirit resist reduction"),
    ("Cursed Relic", "Interrupt, silence, disarm"),
    ("Ethereal Shift", "Invulnerability"),
    ("Vortex Web", "Vacuum grenade"),
    ("Metal Skin", "Bullet immunity"),
    ("Majestic Leap", "Mobility leap"),
    ("Warp Stone", "Teleport + fire rate"),
    ("Phantom Strike", "Teleport to enemy + melee"),
    ("Shadow Weave", "Stealth + ambush"),
    ("Unstoppable", "CC immunity"),
    ("Divine Barrier", "Cleanse + barrier"),
    ("Magic Carpet", "Flight"),
    ("Refresher", "Reset all cooldowns"),
    ("Echo Shard", "Reset imbued ability cooldown"),
    ("Colossus", "Size + HP + CC resistance"),
];

fn hero_json(hero: &HeroStats) -> Value {
    let mut v = json!(hero);
    if let Some(abilities) = v["abilities"].as_array_mut() {
        for ab in abilities {
            if let Some(o) = ab.as_object_mut() {
                o.shift_remove("properties");
                for up in o.get_mut("upgrades").and_then(Value::as_array_mut).into_iter().flatten() {
                    if let Some(u) = up.as_object_mut() {
                        u.shift_remove("property_upgrades");
                    }
                }
            }
        }
    }
    v
}

fn item_json(item: &Item) -> Value {
    let mut v = json!(item);
    let o = v.as_object_mut().expect("item object");
    o.shift_remove("raw_properties");
    o.shift_remove("tooltip_sections");
    o.insert("tooltip_html".into(), json!(presentation::item_tooltip_html(item)));
    let fallback = match crate::item_images::local_item_image(&item.name) {
        Some(file) => format!("/static/items/{file}"),
        None => "/static/ui/all_stats.png".to_string(),
    };
    o.insert("fallback_image".into(), json!(fallback));
    o.insert("behavior".into(), json!(simulation::classify_item(item).map(|b| b.behavior_type)));
    v
}

/// Everything the UI needs up front: heroes, items and game tables.
pub fn catalog(data: &GameData) -> Value {
    let mut heroes: Vec<&HeroStats> = data.heroes.values().collect();
    heroes.sort_by(|a, b| a.name.cmp(&b.name));
    json!({
        "version": env!("CARGO_PKG_VERSION"),
        "heroes": heroes.iter().map(|h| hero_json(h)).collect::<Vec<_>>(),
        "items": data.items.values().map(item_json).collect::<Vec<_>>(),
        "shop_tiers": data::load_shop_tiers(),
        "soul_levels": data::SOUL_LEVEL_TABLE,
        "ability_tier_costs": ABILITY_TIER_COSTS,
        "max_items": MAX_ITEMS,
        "max_boons": data::MAX_BOONS,
        "utility_items": UTILITY_ITEMS.iter()
            .filter(|(n, _)| data.items.contains_key(*n))
            .map(|(n, d)| json!({"name": n, "description": d})).collect::<Vec<_>>(),
        "rank_stats": comparison::RANK_STATS,
        "goals": Goal::ALL.iter().map(|(n, _)| *n).collect::<Vec<_>>(),
        "default_settings": Settings::default(),
        "warnings": data.warnings,
        "cache_age_seconds": crate::api_client::cache_age_seconds(),
    })
}

// ── Build editing ──────────────────────────────────────────────────

/// Add an item to a build, consuming components. Returns the new item list.
pub fn add_item(data: &GameData, items: &[String], item: &str) -> ServiceResult {
    let mut build = data.resolve_items(items)?;
    let new_item = data
        .resolve_item(item)
        .ok_or_else(|| format!("Item '{item}' not found.{}", data::suggest(&data.items, item)))?;
    let before_cost: i64 = build.iter().map(|i| i.cost).sum();
    let outcome = components::add_item(&mut build, new_item, &data.items);
    let (status, message, consumed) = match &outcome {
        AddOutcome::Added { consumed } if consumed.is_empty() => ("added", format!("Added {}.", new_item.name), vec![]),
        AddOutcome::Added { consumed } => {
            ("upgraded", format!("Upgraded {} into {}.", consumed.join(" + "), new_item.name), consumed.clone())
        }
        AddOutcome::Duplicate => ("duplicate", format!("{} is already in the build.", new_item.name), vec![]),
        AddOutcome::Full => ("full", format!("All {MAX_ITEMS} item slots are full."), vec![]),
        AddOutcome::Superseded { by } => ("superseded", format!("{} is already part of {by}.", new_item.name), vec![]),
    };
    let after_cost: i64 = build.iter().map(|i| i.cost).sum();
    Ok(json!({
        "status": status,
        "message": message,
        "consumed": consumed,
        "paid": after_cost - before_cost,
        "items": build.iter().map(|i| &i.name).collect::<Vec<_>>(),
    }))
}

// ── Build evaluation ───────────────────────────────────────────────

fn spirit_ctx(s: &BuildSummary) -> SpiritContext {
    SpiritContext {
        current_spirit: s.spirit_power as f64,
        cooldown_reduction: s.stats.cooldown_reduction,
        spirit_amp: s.stats.spirit_amp_pct,
        enemy_spirit_resist: 0.0,
        resist_shred: s.stats.spirit_resist_shred,
    }
}

fn melee_ctx(s: &BuildSummary) -> MeleeContext {
    MeleeContext {
        boons: s.boons,
        weapon_damage_bonus: s.stats.weapon_damage_pct,
        melee_damage_pct: s.stats.melee_damage_pct,
    }
}

/// Per-ability panel: current numbers plus what each upgrade tier would do.
fn ability_panel(ctx: &BuildContext, s: &BuildSummary, spec: &BuildSpec, ap_remaining: i64) -> Vec<Value> {
    let hero = ctx.hero;
    let sctx = spirit_ctx(s);
    let mctx = melee_ctx(s);
    let total = |upgrades: &AbilityUpgrades| damage::hero_total_spirit_dps(hero, &sctx, Some(upgrades), &mctx);
    let current_total = total(&ctx.ability_upgrades);
    hero.abilities
        .iter()
        .enumerate()
        .map(|(idx, ab)| {
            let owned = spec.ability_upgrades.get(&idx).copied().unwrap_or(0);
            let now = damage::ability_dps_in_total(hero, idx, &sctx, Some(&ctx.ability_upgrades), &mctx);
            let tiers: Vec<Value> = (1..=3i64)
                .map(|tier| {
                    let cost = ABILITY_TIER_COSTS[tier as usize - 1];
                    let active = tier <= owned;
                    let mut trial = ctx.ability_upgrades.clone();
                    trial.insert(idx, (1..=tier).collect());
                    json!({
                        "tier": tier,
                        "cost": cost,
                        "active": active,
                        "can_buy": !active && tier == owned + 1 && ap_remaining >= cost,
                        "description": ab.upgrades.iter().find(|u| u.tier == tier).map(|u| u.description.as_str()).unwrap_or("No data"),
                        "spirit_dps_delta": total(&trial) - current_total,
                    })
                })
                .collect();
            json!({
                "index": idx,
                "name": ab.name,
                "ability_type": ab.ability_type,
                "image_url": ab.image_url,
                "tier": owned,
                "damage": now.as_ref().map(|r| r.modified_damage),
                "dps": now.as_ref().map(|r| r.dps),
                "tiers": tiers,
            })
        })
        .collect()
}

/// Evaluate a build: headline numbers, the stat sheet, ability panel and share code.
pub fn evaluate(data: &GameData, req: &BuildRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let ctx = req.build.context(data, &settings)?;
    let s = summarize(&ctx);
    let ap_total = data::souls_to_ability_points(s.total_souls);
    let spent = ap_spent(&req.build.ability_upgrades);
    let ap_remaining = (ap_total - spent).max(0);
    let shared = SharedBuild {
        hero: ctx.hero.name.clone(),
        items: ctx.items.iter().map(|i| i.name.clone()).collect(),
        extra_souls: ctx.extra_souls,
        ability_upgrades: req.build.ability_upgrades.clone(),
    };
    let mut warnings: Vec<String> = Vec::new();
    if spent > ap_total {
        warnings
            .push(format!("Ability upgrades cost {spent} AP but only {ap_total} are available at this soul count."));
    }
    if ctx.items.len() > MAX_ITEMS {
        warnings.push(format!("Build has {} items; only {MAX_ITEMS} slots exist.", ctx.items.len()));
    }
    let next_boon =
        data::SOUL_LEVEL_TABLE.iter().find(|r| r.0 > s.total_souls && r.1 > s.boons).map(|r| r.0 - s.total_souls);
    Ok(json!({
        "hero": ctx.hero.name,
        "items": shared.items,
        "souls": {"total": s.total_souls, "items": s.item_cost, "extra": ctx.extra_souls, "to_next_boon": next_boon},
        "boons": s.boons,
        "ap": {"total": ap_total, "spent": spent, "remaining": ap_remaining},
        "summary": {
            "gun_dps": s.gun_dps, "spirit_dps": s.spirit_dps, "combined_dps": s.combined_dps,
            "hp_pool": s.hp_pool, "effective_hp": s.effective_hp, "hp_regen": s.hp_regen,
            "spirit_power": s.spirit_power,
            "build_type": classify_build_type(s.gun_dps, s.spirit_dps),
        },
        "sheet": presentation::stat_sheet(&ctx, &s),
        "abilities": ability_panel(&ctx, &s, &req.build, ap_remaining),
        "share_code": share::encode(&shared, data).ok(),
        "warnings": warnings,
    }))
}

// ── Item scoring ───────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct ScoreRequest {
    pub build: BuildSpec,
    pub settings: Settings,
    /// "fast", "gun", "spirit" or "hybrid".
    pub mode: String,
    /// Restrict scoring to these items (all unowned items when empty).
    pub candidates: Vec<String>,
}

/// Score every purchasable item against the current build.
///
/// Fast mode recomputes boons for the souls each purchase adds; simulation
/// modes run a short fight against a target dummy per candidate.
pub fn score_items(data: &GameData, req: &ScoreRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let ctx = req.build.context(data, &settings)?;
    let mode = ScoreMode::parse(if req.mode.is_empty() { "fast" } else { &req.mode })
        .ok_or_else(|| format!("Unknown scoring mode '{}'. Use fast, gun, spirit or hybrid.", req.mode))?;
    let now = summarize(&ctx);

    let wanted: Option<HashSet<&str>> =
        (!req.candidates.is_empty()).then(|| req.candidates.iter().map(String::as_str).collect());
    // Each candidate with the build that results from buying it.
    let trials: Vec<(Trial, Vec<String>)> = data
        .items
        .values()
        .filter(|i| wanted.as_ref().is_none_or(|w| w.contains(i.name.as_str())))
        .filter_map(|item| {
            let mut next = ctx.items.clone();
            match components::add_item(&mut next, item, &data.items) {
                AddOutcome::Added { consumed } => {
                    let paid = next.iter().map(|i| i.cost).sum::<i64>() - ctx.item_cost();
                    Some((Trial { item_name: item.name.clone(), cost: paid, build: Build::new(next) }, consumed))
                }
                _ => None,
            }
        })
        .collect();

    let mut out: IndexMap<String, Value> = IndexMap::new();
    if mode == ScoreMode::Fast {
        for (t, consumed) in &trials {
            let after = summarize(&ctx.with_items(t.build.items.clone()));
            let cost = t.cost.max(1) as f64;
            let (gun, spirit, ehp) =
                (after.gun_dps - now.gun_dps, after.spirit_dps - now.spirit_dps, after.effective_hp - now.effective_hp);
            out.insert(
                t.item_name.clone(),
                json!({
                    "dps_delta": gun, "spirit_delta": spirit, "ehp_delta": ehp,
                    "dps_per_soul": (gun + spirit) / cost, "ehp_per_soul": ehp / cost,
                    "purchase_cost": t.cost, "consumes": consumed,
                }),
            );
        }
    } else {
        let cfg = ScoringConfig {
            sim_settings: Some(settings.sim_settings(now.boons, 0)),
            ability_schedule: settings.ability_schedule(ctx.hero),
            ability_upgrades: ctx.ability_upgrades.clone(),
            custom_item_dps: settings.custom_item_dps.clone(),
            custom_item_ehp: settings.custom_item_ehp.clone(),
            enabled_conditionals: ctx.conditionals.clone(),
        };
        let only: Vec<Trial> = trials.iter().map(|(t, _)| t.clone()).collect();
        let scores = scoring::score_trials(ctx.hero, &Build::new(ctx.items.clone()), &only, now.boons, mode, &cfg);
        for (t, consumed) in &trials {
            let sc = &scores[&t.item_name];
            out.insert(
                t.item_name.clone(),
                json!({
                    "sim_dps_delta": sc.sim_dps_delta, "sim_ehp_delta": sc.sim_ehp_delta,
                    "sim_dps_per_soul": sc.sim_dps_per_soul, "sim_ehp_per_soul": sc.sim_ehp_per_soul,
                    "sim_dps": sc.sim_dps, "purchase_cost": t.cost, "consumes": consumed,
                }),
            );
        }
    }
    Ok(json!({"mode": req.mode, "scores": out}))
}

// ── Simulation ─────────────────────────────────────────────────────

/// The opposing side of a simulation or duel.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct DefenderSpec {
    pub hero: String,
    pub items: Vec<String>,
    pub boons: i64,
    pub ability_upgrades: BTreeMap<usize, i64>,
}

impl Default for DefenderSpec {
    fn default() -> Self {
        DefenderSpec { hero: String::new(), items: Vec::new(), boons: 10, ability_upgrades: BTreeMap::new() }
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct SimRequest {
    pub build: BuildSpec,
    pub defender: DefenderSpec,
    pub settings: Settings,
}

/// Width of the DPS-over-time buckets, in seconds.
const BUCKET_SECONDS: f64 = 0.5;

fn sim_side(name: &str, cid: &str, r: &SimResult) -> Value {
    let (total, dps, by_source, dps_by_source, bullet, spirit, melee, bullets, headshots, reloads, procs, kill) =
        if cid == "a" {
            (
                r.total_damage,
                r.overall_dps,
                r.damage_by_source.clone(),
                r.dps_by_source.clone(),
                r.bullet_damage,
                r.spirit_damage,
                r.melee_damage,
                r.bullets_fired,
                r.headshots,
                r.reloads,
                r.procs_triggered.clone(),
                r.kill_time,
            )
        } else {
            (
                r.defender_total_damage.unwrap_or(0.0),
                r.defender_dps.unwrap_or(0.0),
                r.defender_damage_by_source.clone().unwrap_or_default(),
                r.defender_dps_by_source.clone().unwrap_or_default(),
                r.defender_bullet_damage.unwrap_or(0.0),
                r.defender_spirit_damage.unwrap_or(0.0),
                r.defender_melee_damage.unwrap_or(0.0),
                r.defender_bullets_fired.unwrap_or(0),
                r.defender_headshots.unwrap_or(0),
                r.defender_reloads.unwrap_or(0),
                r.defender_procs_triggered.clone().unwrap_or_default(),
                r.defender_kill_time,
            )
        };
    let mut sources: Vec<Value> = by_source
        .iter()
        .map(|(src, dmg)| {
            json!({
                "source": src, "damage": dmg, "dps": dps_by_source.get(src).copied().unwrap_or(0.0),
                "share": if total > 0.0 { dmg / total } else { 0.0 },
            })
        })
        .collect();
    sources.sort_by(|a, b| b["damage"].as_f64().unwrap_or(0.0).total_cmp(&a["damage"].as_f64().unwrap_or(0.0)));
    json!({
        "name": name, "combatant": cid, "dps": dps, "total_damage": total, "kill_time": kill,
        "by_type": {"bullet": bullet, "spirit": spirit, "melee": melee},
        "sources": sources,
        "bullets_fired": bullets, "headshots": headshots, "reloads": reloads, "procs": procs,
    })
}

/// Run the combat simulation for a build against a defender.
pub fn simulate(data: &GameData, req: &SimRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let ctx = req.build.context(data, &settings)?;
    let defender = data.hero_or_err(&req.defender.hero)?;
    let defender_items = components::normalize_build(&data.resolve_items(&req.defender.items)?, &data.items);
    let atk_boons = ctx.boons();
    let def_boons = req.defender.boons.clamp(0, 100);

    let config = SimConfig {
        attacker: ctx.hero.clone(),
        attacker_build: Build::new(ctx.items.clone()),
        defender: defender.clone(),
        defender_build: Build::new(defender_items.clone()),
        settings: settings.sim_settings(atk_boons, def_boons),
        ability_schedule: settings.ability_schedule(ctx.hero),
        attacker_ability_upgrades: ctx.ability_upgrades.clone(),
        defender_ability_upgrades: tiers_map(&req.defender.ability_upgrades),
        defender_ability_schedule: settings.ability_schedule(defender),
        ..Default::default()
    };
    let r = run_simulation(&config);
    let bidirectional = settings.bidirectional;

    // DPS-over-time buckets per (combatant, source), plus cumulative damage per side.
    let n_buckets = ((r.total_duration / BUCKET_SECONDS) as usize + 1).max(1);
    let mut series: IndexMap<(String, &str), (DamageType, Vec<f64>)> = IndexMap::new();
    let mut cumulative = [vec![0.0; n_buckets], vec![0.0; n_buckets]];
    for e in &r.timeline {
        let idx = ((e.time / BUCKET_SECONDS) as usize).min(n_buckets - 1);
        let entry =
            series.entry((e.source.to_string(), e.combatant)).or_insert_with(|| (e.damage_type, vec![0.0; n_buckets]));
        entry.1[idx] += e.damage;
        cumulative[usize::from(e.combatant == "b")][idx] += e.damage;
    }
    for side in &mut cumulative {
        for i in 1..side.len() {
            side[i] += side[i - 1];
        }
    }
    let chart_series: Vec<Value> = series
        .iter()
        .map(|((source, cid), (dtype, buckets))| {
            json!({
                "source": source, "combatant": cid, "damage_type": dtype,
                "dps": buckets.iter().map(|v| v / BUCKET_SECONDS).collect::<Vec<_>>(),
            })
        })
        .collect();

    let def_stats = builds::aggregate_stats(&Build::new(defender_items.clone()), None);
    let atk_stats = builds::aggregate_stats(&Build::new(ctx.items.clone()), None);
    let mut sides = vec![sim_side(&ctx.hero.name, "a", &r)];
    if bidirectional {
        sides.push(sim_side(&defender.name, "b", &r));
    }
    Ok(json!({
        "attacker": {"name": ctx.hero.name, "items": ctx.items.len(), "boons": atk_boons,
                     "pool": defender_effective_hp(ctx.hero, &atk_stats, atk_boons)},
        "defender": {"name": defender.name, "items": defender_items.iter().map(|i| &i.name).collect::<Vec<_>>(),
                     "boons": def_boons, "pool": defender_effective_hp(defender, &def_stats, def_boons)},
        "bidirectional": bidirectional,
        "duration": r.total_duration,
        "configured_duration": settings.duration,
        "winner": r.winner,
        "kill_time": r.kill_time,
        "defender_kill_time": r.defender_kill_time,
        "target_hp_remaining": r.target_hp_remaining,
        "attacker_hp_remaining": r.attacker_hp_remaining,
        "sides": sides,
        "chart": {
            "bucket_seconds": BUCKET_SECONDS,
            "times": (0..n_buckets).map(|i| i as f64 * BUCKET_SECONDS).collect::<Vec<_>>(),
            "series": chart_series,
            "cumulative": {"a": cumulative[0], "b": if bidirectional { Some(&cumulative[1]) } else { None }},
        },
        "events": r.timeline.len(),
    }))
}

// ── Duels: Monte Carlo, matchups ───────────────────────────────────

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct MonteCarloRequest {
    pub build: BuildSpec,
    pub defender: DefenderSpec,
    pub settings: Settings,
    pub trials: usize,
    pub seed: Option<u64>,
}

impl Default for MonteCarloRequest {
    fn default() -> Self {
        MonteCarloRequest {
            build: BuildSpec::default(),
            defender: DefenderSpec::default(),
            settings: Settings::default(),
            trials: 2000,
            seed: None,
        }
    }
}

/// Roll a gun duel many times and report the spread of kill times.
pub fn monte_carlo(data: &GameData, req: &MonteCarloRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let ctx = req.build.context(data, &settings)?;
    let defender = data.hero_or_err(&req.defender.hero)?;
    let defender_items = components::normalize_build(&data.resolve_items(&req.defender.items)?, &data.items);
    let def_stats = builds::aggregate_stats(&Build::new(defender_items), ctx.conditionals.as_ref());
    let def_boons = req.defender.boons.clamp(0, 100);
    let me = summarize(&ctx);

    let mut config = build_to_attacker_config(
        &me.stats,
        &AttackerOptions {
            boons: me.boons,
            spirit_gain: ctx.hero.spirit_gain,
            accuracy: settings.accuracy,
            headshot_rate: settings.headshot_rate,
            headshot_multiplier: ctx.hero.crit_bonus_start,
            enemy_bullet_resist: def_stats.bullet_resist_pct,
            enemy_hp: defender_effective_hp(defender, &def_stats, def_boons),
            enemy_bonus_hp: 0.0,
        },
    );
    config.distance = settings.distance;
    let params = MonteCarloParams {
        trials: req.trials.clamp(100, 20_000),
        seed: req.seed.unwrap_or(MonteCarloParams::default().seed),
        ..Default::default()
    };
    let dist = monte_carlo_ttk(ctx.hero, defender, &config, &params);
    Ok(json!({
        "attacker": ctx.hero.name, "defender": defender.name, "defender_boons": def_boons,
        "accuracy": settings.accuracy, "headshot_rate": settings.headshot_rate, "distance": settings.distance,
        "distribution": dist,
    }))
}

/// Gun-duel matchups of the build against every hero.
pub fn matchups(data: &GameData, req: &BuildRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let ctx = req.build.context(data, &settings)?;
    let rows = analysis::matchups(&ctx, &data.heroes);
    let wins = rows.iter().filter(|m| m.margin > 0.0).count();
    Ok(json!({
        "hero": ctx.hero.name, "boons": ctx.boons(),
        "accuracy": settings.accuracy, "headshot_rate": settings.headshot_rate,
        "wins": wins, "total": rows.len(), "matchups": rows,
    }))
}

// ── Curves ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct CurveRequest {
    pub build: BuildSpec,
    pub settings: Settings,
    /// Reorder items into an efficient purchase order first.
    pub reorder: bool,
}

/// Power curve over the purchase order, plus DPS by range.
pub fn curves(data: &GameData, req: &CurveRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let mut ctx = req.build.context(data, &settings)?;
    let suggested = analysis::suggest_purchase_order(&ctx);
    if req.reorder {
        ctx.items = suggested.clone();
    }
    let max_range = (ctx.hero.falloff_range_max * 1.25).max(40.0).ceil();
    Ok(json!({
        "hero": ctx.hero.name,
        "order": ctx.items.iter().map(|i| &i.name).collect::<Vec<_>>(),
        "suggested_order": suggested.iter().map(|i| &i.name).collect::<Vec<_>>(),
        "power": analysis::power_curve(&ctx),
        "range": analysis::range_curve(&ctx, max_range, 1.0),
        "falloff": {"start": ctx.hero.falloff_range_min, "end": ctx.hero.falloff_range_max},
    }))
}

// ── Optimizer ──────────────────────────────────────────────────────

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct OptimizeRequest {
    /// Hero, plus items to keep as a locked starting point.
    pub build: BuildSpec,
    pub settings: Settings,
    pub goal: String,
    pub budget: i64,
    pub max_items: usize,
    pub max_tier: i64,
    pub exclude_conditional: bool,
}

impl Default for OptimizeRequest {
    fn default() -> Self {
        OptimizeRequest {
            build: BuildSpec::default(),
            settings: Settings::default(),
            goal: "balanced".into(),
            budget: 15000,
            max_items: MAX_ITEMS,
            max_tier: 4,
            exclude_conditional: false,
        }
    }
}

fn parse_goal(goal: &str) -> Result<Goal, String> {
    Goal::parse(goal).ok_or_else(|| format!("Unknown goal '{goal}'. Use gun, spirit, damage, tank or balanced."))
}

/// Find a strong build within a soul budget.
pub fn optimize(data: &GameData, req: &OptimizeRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let mut ctx = req.build.context(data, &settings)?;
    ctx.boons_override = None;
    let params = OptimizeParams {
        goal: parse_goal(&req.goal)?,
        budget: req.budget.clamp(0, 500_000).max(ctx.item_cost()),
        max_items: req.max_items.clamp(1, MAX_ITEMS).max(ctx.items.len().min(MAX_ITEMS)),
        max_tier: req.max_tier.clamp(1, 5),
        exclude_conditional: req.exclude_conditional,
    };
    let result = optimizer::optimize(&ctx, &data.items, &params);
    let ordered = analysis::suggest_purchase_order(&ctx.with_items(data.resolve_items(&result.items)?));
    Ok(json!({
        "hero": ctx.hero.name,
        "result": result,
        "purchase_order": ordered.iter().map(|i| &i.name).collect::<Vec<_>>(),
        "build_type": classify_build_type(result.after.gun_dps, result.after.spirit_dps),
    }))
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct RecommendRequest {
    pub build: BuildSpec,
    pub settings: Settings,
    pub goal: String,
    /// Only consider purchases affordable with this many souls.
    pub available_souls: Option<i64>,
    pub limit: usize,
}

impl Default for RecommendRequest {
    fn default() -> Self {
        RecommendRequest {
            build: BuildSpec::default(),
            settings: Settings::default(),
            goal: "balanced".into(),
            available_souls: None,
            limit: 8,
        }
    }
}

/// Rank the next purchases for a build.
pub fn recommend(data: &GameData, req: &RecommendRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let ctx = req.build.context(data, &settings)?;
    let recs =
        optimizer::recommend(&ctx, &data.items, parse_goal(&req.goal)?, req.available_souls, 4, req.limit.clamp(1, 50));
    Ok(json!({"hero": ctx.hero.name, "goal": req.goal, "recommendations": recs}))
}

// ── Build comparison ───────────────────────────────────────────────

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct CompareBuildsRequest {
    pub a: BuildSpec,
    pub b: BuildSpec,
    pub settings: Settings,
}

/// Compare two builds stat by stat.
pub fn compare_builds(data: &GameData, req: &CompareBuildsRequest) -> ServiceResult {
    let settings = req.settings.clone().sanitized();
    let (ca, cb) = (req.a.context(data, &settings)?, req.b.context(data, &settings)?);
    let (sa, sb) = (summarize(&ca), summarize(&cb));
    let names = |c: &BuildContext| c.items.iter().map(|i| i.name.clone()).collect::<Vec<_>>();
    let (ia, ib) = (names(&ca), names(&cb));
    Ok(json!({
        "a": {"hero": ca.hero.name, "items": ia, "build_type": classify_build_type(sa.gun_dps, sa.spirit_dps)},
        "b": {"hero": cb.hero.name, "items": ib, "build_type": classify_build_type(sb.gun_dps, sb.spirit_dps)},
        "only_a": ia.iter().filter(|n| !ib.contains(n)).collect::<Vec<_>>(),
        "only_b": ib.iter().filter(|n| !ia.contains(n)).collect::<Vec<_>>(),
        "shared": ia.iter().filter(|n| ib.contains(n)).collect::<Vec<_>>(),
        "rows": analysis::compare_builds(&sa, &sb),
    }))
}

// ── Heroes ─────────────────────────────────────────────────────────

/// Rank heroes by a base stat at a boon level.
pub fn rankings(data: &GameData, stat: &str, boons: i64, limit: usize) -> ServiceResult {
    if !comparison::RANK_STATS.contains(&stat) {
        return Err(format!("Unknown stat '{stat}'. Use one of: {}.", comparison::RANK_STATS.join(", ")));
    }
    let mut ranks = comparison::rank_heroes(&data.heroes, stat, boons.clamp(0, 100), false);
    ranks.truncate(limit.max(1));
    Ok(json!({"stat": stat, "boons": boons, "rankings": ranks}))
}

/// Compare two heroes' base stats at a boon level and across the boon curve.
pub fn compare_heroes(data: &GameData, a: &str, b: &str, boons: i64) -> ServiceResult {
    let (ha, hb) = (data.hero_or_err(a)?, data.hero_or_err(b)?);
    let boons = boons.clamp(0, 100);
    Ok(json!({
        "at": comparison::compare_two(ha, hb, boons),
        "curve": comparison::compare_curve(ha, hb, data::MAX_BOONS),
        "growth": {"a": heroes::growth_percentage(ha, data::MAX_BOONS), "b": heroes::growth_percentage(hb, data::MAX_BOONS)},
    }))
}

/// Scaling curve for a hero across boon levels.
pub fn scaling(data: &GameData, hero: &str, max_boons: i64) -> ServiceResult {
    let h = data.hero_or_err(hero)?;
    let max_boons = max_boons.clamp(1, 100);
    Ok(json!({
        "hero": h.name,
        "growth": heroes::growth_percentage(h, max_boons),
        "curve": heroes::scaling_curve(h, max_boons),
    }))
}

// ── Sharing ────────────────────────────────────────────────────────

/// Decode a share code into a build.
pub fn decode_share(data: &GameData, code: &str) -> ServiceResult {
    let (build, warnings) = share::decode(code, data)?;
    Ok(json!({"build": build, "warnings": warnings}))
}

// ── Patch notes ────────────────────────────────────────────────────

/// Saved patches, newest first.
pub fn list_patches() -> Value {
    let mut dates = patchnotes::list_saved_patches();
    // File names are MM-DD-YYYY: sort by (year, month, day).
    dates.sort_by_key(|d| {
        let p: Vec<&str> = d.split('-').collect();
        if let [m, d, y] = p[..] {
            (y.to_string(), m.to_string(), d.to_string())
        } else {
            (String::new(), d.clone(), String::new())
        }
    });
    dates.reverse();
    json!({"patches": dates})
}

fn report_json(date: &str, saved: &str, data: &GameData) -> Value {
    let url = saved.lines().find_map(|l| l.strip_prefix("# Source: ")).unwrap_or("").to_string();
    let mut changes = patchnotes::parse_patch_notes(&patchnotes::patch_body(saved));
    let mut report = patchnotes::diff_patch(&mut changes, &data.heroes, Some(&data.items));
    report.patch_date = date.to_string();
    report.patch_url = url;
    json!({
        "date": report.patch_date, "url": report.patch_url, "total": report.total_changes,
        "counts": {
            "already_applied": report.already_applied().len(),
            "needs_update": report.needs_update().len(),
            "manual_review": report.manual_review().len(),
        },
        "entries": report.entries,
    })
}

/// Diff a saved patch against the loaded data.
pub fn patch_report(data: &GameData, date: &str) -> ServiceResult {
    let saved = patchnotes::load_saved_patch(date).ok_or_else(|| format!("No saved patch for '{date}'."))?;
    Ok(report_json(date, &saved, data))
}

/// Fetch the latest patch notes from the forum, save them, and diff them.
pub fn fetch_latest_patch(data: &GameData) -> ServiceResult {
    let (url, date, text) = patchnotes::fetch_latest_patch()?;
    patchnotes::save_patch(&date, &text, &url)?;
    let saved = patchnotes::load_saved_patch(&date).ok_or("Saved patch could not be read back.")?;
    Ok(report_json(&date, &saved, data))
}

/// Short one-line description of a build for logs and text UIs.
pub fn describe_build(spec: &BuildSpec, s: &BuildSummary) -> String {
    format!(
        "{} — {} items, {} souls, {} boons: gun {:.1} DPS, spirit {:.1} DPS, {:.0} EHP",
        spec.hero,
        spec.items.len(),
        commas(s.total_souls),
        s.boons,
        s.gun_dps,
        s.spirit_dps,
        s.effective_hp
    )
}
