//! MCP server exposing the simulator engine as tools.
//!
//! Speaks JSON-RPC 2.0 over stdio (one message per line), implementing the
//! `initialize`, `ping`, `tools/list` and `tools/call` methods.

use std::io::{self, BufRead, Write};

use serde::Deserialize;
use serde_json::{json, Value};

use crate::data::GameData;
use crate::engine::builds::{self, EvalOptions, MAX_ITEMS};
use crate::engine::comparison;
use crate::engine::damage::{self, MeleeContext, SpiritContext};
use crate::engine::heroes;
use crate::models::{Build, CombatConfig};
use crate::service::{self, BuildRequest, BuildSpec, ServiceResult, Settings};
use crate::share::{self, SharedBuild};

const DEFAULT_PROTOCOL: &str = "2025-06-18";

// ── Tool catalog ───────────────────────────────────────────────────

fn prop(kind: &str, description: &str) -> Value {
    json!({"type": kind, "description": description})
}

fn tool(name: &str, description: &str, properties: Value, required: &[&str]) -> Value {
    json!({
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required},
    })
}

fn build_props() -> Value {
    json!({
        "hero_name": prop("string", "Hero name (case-insensitive, partial names accepted)."),
        "item_names": {"type": "array", "items": {"type": "string"}, "description": "Items in the build."},
        "extra_souls": prop("integer", "Souls gathered beyond what the items cost (default 0)."),
        "boons": prop("integer", "Fix the boon count instead of deriving it from souls."),
        "ability_upgrades": {"type": "object", "description": "Ability index (0-3) → highest upgrade tier owned (1-3).",
                             "additionalProperties": {"type": "integer"}},
        "accuracy": prop("number", "Fraction of shots that hit, 0-1 (default 0.65)."),
        "headshot_rate": prop("number", "Fraction of hits that are headshots, 0-1 (default 0.10)."),
    })
}

fn with(mut base: Value, extra: Value) -> Value {
    if let (Some(b), Some(e)) = (base.as_object_mut(), extra.as_object()) {
        for (k, v) in e {
            b.insert(k.clone(), v.clone());
        }
    }
    base
}

fn tool_list() -> Vec<Value> {
    let hero = || prop("string", "Hero name (case-insensitive, partial names accepted).");
    vec![
        tool("list_heroes", "List all available hero names.", json!({}), &[]),
        tool("get_hero", "Get full stats for a hero: gun data, survivability, scaling, abilities, images and lore.",
             json!({"name": hero()}), &["name"]),
        tool("get_hero_abilities", "Get detailed ability information for a hero, including raw properties.",
             json!({"name": hero()}), &["name"]),
        tool("list_items", "List shop items, optionally filtered by category (weapon/vitality/spirit) and tier (1-5).",
             json!({"category": prop("string", "weapon, vitality or spirit"), "tier": prop("integer", "Item tier 1-5")}), &[]),
        tool("get_item", "Get full details for an item by name.", json!({"name": prop("string", "Item name")}), &["name"]),
        tool("calculate_bullet_dps",
             "Calculate bullet DPS for a hero with optional combat modifiers. Returns per-bullet damage, fire rate, raw/final/sustained DPS, magazine stats and realistic DPS.",
             json!({
                 "hero_name": hero(), "boons": prop("integer", "Boon count"),
                 "weapon_damage_bonus": prop("number", "Weapon damage bonus as a fraction (0.35 = +35%)"),
                 "fire_rate_bonus": prop("number", "Fire rate bonus as a fraction"),
                 "enemy_bullet_resist": prop("number", "Enemy bullet resist, 0-1"),
                 "shred": prop("number", "Bullet resist shred, 0-1"),
                 "accuracy": prop("number", "Accuracy, 0-1"), "headshot_rate": prop("number", "Headshot rate, 0-1"),
                 "distance": prop("number", "Engagement range in meters (default 20)"),
             }), &["hero_name"]),
        tool("calculate_spirit_dps",
             "Calculate total spirit DPS from all of a hero's damaging abilities, with a per-ability breakdown.",
             json!({
                 "hero_name": hero(), "current_spirit": prop("integer", "Spirit power"),
                 "cooldown_reduction": prop("number", "Cooldown reduction, 0-1"),
                 "spirit_amp": prop("number", "Spirit amp as a fraction"),
                 "enemy_spirit_resist": prop("number", "Enemy spirit resist, 0-1"),
                 "resist_shred": prop("number", "Spirit resist shred, 0-1"),
             }), &["hero_name"]),
        tool("calculate_ttk",
             "Calculate time-to-kill for attacker vs defender: ideal TTK, realistic TTK (accuracy, headshots, reloads), magazines needed.",
             json!({
                 "attacker_name": hero(), "defender_name": hero(), "boons": prop("integer", "Boon count for both"),
                 "weapon_damage_bonus": prop("number", "Weapon damage bonus as a fraction"),
                 "fire_rate_bonus": prop("number", "Fire rate bonus as a fraction"),
                 "accuracy": prop("number", "Accuracy, 0-1 (default 0.7)"),
                 "headshot_rate": prop("number", "Headshot rate, 0-1 (default 0.15)"),
                 "enemy_bullet_resist": prop("number", "Enemy bullet resist, 0-1"),
             }), &["attacker_name", "defender_name"]),
        tool("scaling_curve", "Get the DPS and HP scaling curve for a hero across boon levels.",
             json!({"hero_name": hero(), "max_boons": prop("integer", "Highest boon level (default 35)")}), &["hero_name"]),
        tool("compare_heroes", "Compare two heroes side-by-side at a boon level: DPS, HP, DPM and ratios.",
             json!({"hero_a_name": hero(), "hero_b_name": hero(), "boon_level": prop("integer", "Boon level")}),
             &["hero_a_name", "hero_b_name"]),
        tool("rank_heroes", "Rank heroes by a stat: dps, hp, dpm, bullet_damage, fire_rate, dps_growth, hp_growth.",
             json!({"stat": prop("string", "Stat to rank by (default dps)"), "boon_level": prop("integer", "Boon level"),
                    "top_n": prop("integer", "How many to return (default 10)")}), &[]),
        tool("evaluate_build",
             "Evaluate a set of items on a hero: bullet DPS, spirit DPS, effective HP, build cost, a share code, and TTK vs an optional defender.",
             json!({
                 "hero_name": hero(), "item_names": {"type": "array", "items": {"type": "string"}, "description": "Items in the build."},
                 "boons": prop("integer", "Boon count"), "accuracy": prop("number", "Accuracy, 0-1 (default 0.7)"),
                 "headshot_rate": prop("number", "Headshot rate, 0-1 (default 0.15)"),
                 "defender_name": prop("string", "Optional defender hero for TTK"),
             }), &["hero_name", "item_names"]),
        tool("optimize_build",
             "Find a strong item build for a hero within a soul budget. goal: gun, spirit, damage, tank or balanced (whole-build optimizer); dps or ttk (greedy gun-only optimizer; ttk requires defender_name).",
             json!({
                 "hero_name": hero(), "budget": prop("integer", "Soul budget (default 15000)"),
                 "boons": prop("integer", "Boon count (greedy goals only; others derive boons from the budget)"),
                 "goal": prop("string", "gun | spirit | damage | tank | balanced | dps | ttk (default dps)"),
                 "defender_name": prop("string", "Defender hero (ttk goal)"),
                 "max_items": prop("integer", "Maximum items (default 12)"),
                 "locked_items": {"type": "array", "items": {"type": "string"}, "description": "Items that must stay in the build."},
             }), &["hero_name"]),
        tool("recommend_items",
             "Rank the best next purchases for a build by gain per soul toward a goal (gun, spirit, damage, tank, balanced). Accounts for component upgrade discounts.",
             with(build_props(), json!({
                 "goal": prop("string", "gun | spirit | damage | tank | balanced (default balanced)"),
                 "available_souls": prop("integer", "Only consider purchases affordable with this many souls."),
                 "limit": prop("integer", "How many to return (default 8)"),
             })), &["hero_name"]),
        tool("simulate_combat",
             "Run the event-driven combat simulation (weapon, reloads, item procs, DoTs, abilities, melee) for a build against a defender. Returns DPS, damage by source, kill time and, when bidirectional, the winner.",
             with(build_props(), json!({
                 "defender_name": hero(),
                 "defender_item_names": {"type": "array", "items": {"type": "string"}, "description": "Defender's items."},
                 "defender_boons": prop("integer", "Defender boon count (default 10)"),
                 "duration": prop("number", "Fight length in seconds (default 15)"),
                 "bidirectional": prop("boolean", "Defender fights back (default false)"),
                 "distance": prop("number", "Engagement range in meters (default 20)"),
             })), &["hero_name", "defender_name"]),
        tool("monte_carlo_ttk",
             "Roll a gun duel thousands of times with per-shot hit/headshot rolls. Returns the spread of kill times (mean, median, p10/p90, one-magazine rate).",
             with(build_props(), json!({
                 "defender_name": hero(),
                 "defender_item_names": {"type": "array", "items": {"type": "string"}, "description": "Defender's items."},
                 "defender_boons": prop("integer", "Defender boon count (default 10)"),
                 "trials": prop("integer", "Number of duels (default 2000)"),
                 "seed": prop("integer", "Random seed for reproducible results"),
             })), &["hero_name", "defender_name"]),
        tool("build_matchups",
             "Gun-duel matchups of a build against every hero at equal boons: time to kill, time to die and the margin.",
             build_props(), &["hero_name"]),
        tool("build_power_curve",
             "Strength of a build after each purchase (souls, boons, gun DPS, spirit DPS, EHP), plus a suggested purchase order.",
             with(build_props(), json!({"reorder": prop("boolean", "Use the suggested purchase order (default false)")})),
             &["hero_name"]),
        tool("decode_build_code", "Decode a build share code into hero, items, extra souls and ability upgrades.",
             json!({"code": prop("string", "Share code, e.g. v1-...")}), &["code"]),
        tool("reload_data", "Reload hero and item data from the on-disk API cache.", json!({}), &[]),
    ]
}

// ── Argument helpers ───────────────────────────────────────────────

struct Args<'a>(&'a Value);

impl Args<'_> {
    fn str(&self, key: &str) -> &str {
        self.0.get(key).and_then(Value::as_str).unwrap_or("")
    }
    fn f64(&self, key: &str, default: f64) -> f64 {
        self.0.get(key).and_then(Value::as_f64).unwrap_or(default)
    }
    fn i64(&self, key: &str, default: i64) -> i64 {
        self.0.get(key).and_then(|v| v.as_i64().or_else(|| v.as_f64().map(|f| f as i64))).unwrap_or(default)
    }
    fn bool(&self, key: &str, default: bool) -> bool {
        self.0.get(key).and_then(Value::as_bool).unwrap_or(default)
    }
    fn strings(&self, key: &str) -> Vec<String> {
        self.0
            .get(key)
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default()
    }

    fn build_spec(&self) -> Result<BuildSpec, String> {
        #[derive(Deserialize, Default)]
        #[serde(default)]
        struct Upgrades(std::collections::BTreeMap<usize, i64>);
        let upgrades = match self.0.get("ability_upgrades") {
            Some(v) if !v.is_null() => {
                serde_json::from_value::<Upgrades>(v.clone()).map_err(|e| format!("ability_upgrades: {e}"))?.0
            }
            _ => Default::default(),
        };
        Ok(BuildSpec {
            hero: self.str("hero_name").to_string(),
            items: self.strings("item_names"),
            extra_souls: self.i64("extra_souls", 0),
            ability_upgrades: upgrades,
            boons: self.0.get("boons").and_then(Value::as_i64),
        })
    }

    fn settings(&self) -> Settings {
        let d = Settings::default();
        Settings {
            accuracy: self.f64("accuracy", d.accuracy),
            headshot_rate: self.f64("headshot_rate", d.headshot_rate),
            duration: self.f64("duration", d.duration),
            bidirectional: self.bool("bidirectional", d.bidirectional),
            distance: self.f64("distance", d.distance),
            ..d
        }
    }

    fn defender(&self) -> service::DefenderSpec {
        service::DefenderSpec {
            hero: self.str("defender_name").to_string(),
            items: self.strings("defender_item_names"),
            boons: self.i64("defender_boons", 10),
            ..Default::default()
        }
    }
}

fn ability_json(a: &crate::models::HeroAbility, full: bool) -> Value {
    let description: String = if full { a.description.clone() } else { a.description.chars().take(200).collect() };
    let mut v = json!({
        "name": a.name, "type": a.ability_type, "description": description,
        "base_damage": a.base_damage, "cooldown": a.cooldown, "duration": a.duration,
        "spirit_scaling": a.spirit_scaling, "image_url": a.image_url,
        "upgrades": a.upgrades.iter().map(|u| json!({"tier": u.tier, "description": u.description})).collect::<Vec<_>>(),
    });
    if full {
        v["properties"] = json!(a.properties);
    }
    v
}

// ── Tool dispatch ──────────────────────────────────────────────────

/// Run a tool by name. `Err` carries a message suitable for the model.
pub fn call_tool(data: &mut GameData, name: &str, arguments: &Value) -> ServiceResult {
    let a = Args(arguments);
    let d: &GameData = data;
    match name {
        "list_heroes" => Ok(json!(d.hero_names())),
        "get_hero" => {
            let hero = d.hero_or_err(a.str("name"))?;
            let mut v = json!(hero);
            v["abilities"] = json!(hero.abilities.iter().map(|ab| ability_json(ab, false)).collect::<Vec<_>>());
            Ok(v)
        }
        "get_hero_abilities" => {
            let hero = d.hero_or_err(a.str("name"))?;
            Ok(json!(hero.abilities.iter().map(|ab| ability_json(ab, true)).collect::<Vec<_>>()))
        }
        "list_items" => {
            let category = a.str("category").to_lowercase();
            let tier = a.i64("tier", 0);
            let mut items: Vec<_> = d
                .items
                .values()
                .filter(|i| (category.is_empty() || i.category == category) && (tier == 0 || i.tier == tier))
                .collect();
            items.sort_by(|x, y| (&x.category, x.tier, x.cost).cmp(&(&y.category, y.tier, y.cost)));
            Ok(json!(items
                .iter()
                .map(|i| json!({"name": i.name, "category": i.category, "tier": i.tier, "cost": i.cost}))
                .collect::<Vec<_>>()))
        }
        "get_item" => {
            let n = a.str("name");
            let item = d
                .resolve_item(n)
                .ok_or_else(|| format!("Item '{n}' not found.{}", crate::data::suggest(&d.items, n)))?;
            Ok(json!(item))
        }
        "calculate_bullet_dps" => {
            let hero = d.hero_or_err(a.str("hero_name"))?;
            let shred = a.f64("shred", 0.0);
            let config = CombatConfig {
                boons: a.i64("boons", 0),
                weapon_damage_bonus: a.f64("weapon_damage_bonus", 0.0),
                fire_rate_bonus: a.f64("fire_rate_bonus", 0.0),
                shred: if shred > 0.0 { vec![shred] } else { vec![] },
                accuracy: a.f64("accuracy", 1.0),
                headshot_rate: a.f64("headshot_rate", 0.0),
                headshot_multiplier: hero.crit_bonus_start,
                enemy_bullet_resist: a.f64("enemy_bullet_resist", 0.0),
                distance: a.f64("distance", CombatConfig::default().distance),
                ..Default::default()
            };
            let mut v = json!(damage::calculate_bullet(hero, &config));
            v["realistic_dps"] = json!(damage::dps_with_accuracy(hero, &config));
            Ok(v)
        }
        "calculate_spirit_dps" => {
            let hero = d.hero_or_err(a.str("hero_name"))?;
            let ctx = SpiritContext {
                current_spirit: a.f64("current_spirit", 0.0),
                cooldown_reduction: a.f64("cooldown_reduction", 0.0),
                spirit_amp: a.f64("spirit_amp", 0.0),
                enemy_spirit_resist: a.f64("enemy_spirit_resist", 0.0),
                resist_shred: a.f64("resist_shred", 0.0),
            };
            let per_ability: Vec<Value> = hero
                .abilities
                .iter()
                .filter(|ab| ab.base_damage > 0.0)
                .map(|ab| {
                    let r = damage::calculate_ability_spirit_dps(ab, &ctx, None);
                    json!({"ability": ab.name, "raw_damage": r.raw_damage, "modified_damage": r.modified_damage, "dps": r.dps})
                })
                .collect();
            Ok(json!({
                "hero": hero.name,
                "total_spirit_dps": damage::hero_total_spirit_dps(hero, &ctx, None, &MeleeContext::default()),
                "abilities": per_ability,
            }))
        }
        "calculate_ttk" => {
            let attacker = d.hero_or_err(a.str("attacker_name"))?;
            let defender = d.hero_or_err(a.str("defender_name"))?;
            let config = CombatConfig {
                boons: a.i64("boons", 0),
                weapon_damage_bonus: a.f64("weapon_damage_bonus", 0.0),
                fire_rate_bonus: a.f64("fire_rate_bonus", 0.0),
                accuracy: a.f64("accuracy", 0.7),
                headshot_rate: a.f64("headshot_rate", 0.15),
                headshot_multiplier: attacker.crit_bonus_start,
                enemy_bullet_resist: a.f64("enemy_bullet_resist", 0.0),
                ..Default::default()
            };
            Ok(json!(heroes::ttk(attacker, defender, &config)))
        }
        "scaling_curve" => service::scaling(d, a.str("hero_name"), a.i64("max_boons", 35)),
        "compare_heroes" => {
            let (ha, hb) = (d.hero_or_err(a.str("hero_a_name"))?, d.hero_or_err(a.str("hero_b_name"))?);
            Ok(json!(comparison::compare_two(ha, hb, a.i64("boon_level", 0))))
        }
        "rank_heroes" => {
            let stat = if a.str("stat").is_empty() { "dps" } else { a.str("stat") };
            let r = service::rankings(d, stat, a.i64("boon_level", 0), a.i64("top_n", 10).max(1) as usize)?;
            Ok(r["rankings"].clone())
        }
        "evaluate_build" => {
            let hero = d.hero_or_err(a.str("hero_name"))?;
            let names = a.strings("item_names");
            let items = d.resolve_items(&names)?;
            let build = Build::new(items);
            let defender = match a.str("defender_name") {
                "" => None,
                n => Some(d.hero_or_err(n)?),
            };
            let boons = a.i64("boons", 0);
            let result = builds::evaluate_build(
                hero,
                &build,
                &EvalOptions {
                    boons,
                    accuracy: a.f64("accuracy", 0.7),
                    headshot_rate: a.f64("headshot_rate", 0.15),
                    defender,
                    ..Default::default()
                },
            );
            let bs = &result.build_stats;
            let spirit_dps = damage::hero_total_spirit_dps(
                hero,
                &SpiritContext {
                    current_spirit: builds::total_spirit(bs, boons, hero.spirit_gain) as f64,
                    cooldown_reduction: bs.cooldown_reduction,
                    spirit_amp: bs.spirit_amp_pct,
                    ..Default::default()
                },
                None,
                &MeleeContext {
                    boons,
                    weapon_damage_bonus: bs.weapon_damage_pct,
                    melee_damage_pct: bs.melee_damage_pct,
                },
            );
            let bullet_dps = result.bullet_result.final_dps;
            let shared = SharedBuild { hero: hero.name.clone(), items: build.item_names(), ..Default::default() };
            Ok(json!({
                "hero": hero.name, "items": build.item_names(), "total_cost": build.total_cost(),
                "build_stats": result.build_stats, "bullet_dps": bullet_dps, "spirit_dps": spirit_dps,
                "combined_dps": bullet_dps + spirit_dps, "effective_hp": result.effective_hp,
                "bullet_result": result.bullet_result, "ttk_result": result.ttk_result,
                "share_code": share::encode(&shared, d).ok(),
            }))
        }
        "optimize_build" => {
            let hero = d.hero_or_err(a.str("hero_name"))?;
            let budget = a.i64("budget", 15000);
            let boons = a.i64("boons", 0);
            let max_items = a.i64("max_items", MAX_ITEMS as i64).clamp(1, MAX_ITEMS as i64) as usize;
            let goal = if a.str("goal").is_empty() { "dps" } else { a.str("goal") };
            let build = match goal {
                "dps" => builds::best_dps_items(&d.items, hero, budget, boons, max_items, true),
                "ttk" => {
                    let n = a.str("defender_name");
                    let defender = d
                        .resolve_hero(n)
                        .ok_or_else(|| format!("TTK optimization requires a defender. '{n}' not found."))?;
                    builds::best_ttk_items(&d.items, hero, defender, budget, boons, 0.5, 0.15, max_items, true)
                }
                _ => {
                    return service::optimize(
                        d,
                        &service::OptimizeRequest {
                            build: BuildSpec {
                                hero: hero.name.clone(),
                                items: a.strings("locked_items"),
                                ..Default::default()
                            },
                            goal: goal.to_string(),
                            budget,
                            max_items,
                            ..Default::default()
                        },
                    );
                }
            };
            let result = builds::evaluate_build(hero, &build, &EvalOptions { boons, ..Default::default() });
            let bs = &result.build_stats;
            let spirit_dps = damage::hero_total_spirit_dps(
                hero,
                &SpiritContext {
                    current_spirit: builds::total_spirit(bs, boons, hero.spirit_gain) as f64,
                    cooldown_reduction: bs.cooldown_reduction,
                    spirit_amp: bs.spirit_amp_pct,
                    ..Default::default()
                },
                None,
                &MeleeContext {
                    boons,
                    weapon_damage_bonus: bs.weapon_damage_pct,
                    melee_damage_pct: bs.melee_damage_pct,
                },
            );
            let bullet_dps = result.bullet_result.final_dps;
            Ok(json!({
                "hero": hero.name, "budget": budget, "total_cost": build.total_cost(),
                "items": build.items.iter().map(|i| json!({"name": i.name, "cost": i.cost, "category": i.category, "tier": i.tier})).collect::<Vec<_>>(),
                "bullet_dps": bullet_dps, "spirit_dps": spirit_dps, "combined_dps": bullet_dps + spirit_dps,
                "effective_hp": result.effective_hp,
            }))
        }
        "recommend_items" => service::recommend(
            d,
            &service::RecommendRequest {
                build: a.build_spec()?,
                settings: a.settings(),
                goal: if a.str("goal").is_empty() { "balanced".into() } else { a.str("goal").to_string() },
                available_souls: arguments.get("available_souls").and_then(Value::as_i64),
                limit: a.i64("limit", 8).max(1) as usize,
            },
        ),
        "simulate_combat" => {
            let mut v = service::simulate(
                d,
                &service::SimRequest { build: a.build_spec()?, defender: a.defender(), settings: a.settings() },
            )?;
            // The per-bucket chart data is for UIs; keep tool output compact.
            if let Some(o) = v.as_object_mut() {
                o.shift_remove("chart");
            }
            Ok(v)
        }
        "monte_carlo_ttk" => service::monte_carlo(
            d,
            &service::MonteCarloRequest {
                build: a.build_spec()?,
                defender: a.defender(),
                settings: a.settings(),
                trials: a.i64("trials", 2000).max(1) as usize,
                seed: arguments.get("seed").and_then(Value::as_u64),
            },
        ),
        "build_matchups" => service::matchups(d, &BuildRequest { build: a.build_spec()?, settings: a.settings() }),
        "build_power_curve" => {
            let mut v = service::curves(
                d,
                &service::CurveRequest {
                    build: a.build_spec()?,
                    settings: a.settings(),
                    reorder: a.bool("reorder", false),
                },
            )?;
            if let Some(o) = v.as_object_mut() {
                o.shift_remove("range");
            }
            Ok(v)
        }
        "decode_build_code" => service::decode_share(d, a.str("code")),
        "reload_data" => {
            *data = GameData::load()?;
            Ok(json!(format!("Reloaded: {} heroes, {} items.", data.heroes.len(), data.items.len())))
        }
        other => Err(format!("Unknown tool '{other}'.")),
    }
}

// ── JSON-RPC plumbing ──────────────────────────────────────────────

fn rpc_error(id: Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})
}

/// Handle one JSON-RPC message. Returns `None` for notifications.
pub fn handle_message(data: &mut GameData, msg: &Value) -> Option<Value> {
    let method = msg.get("method").and_then(Value::as_str).unwrap_or("");
    // Messages without an id are notifications and never get a response.
    let id = msg.get("id").cloned()?;
    let params = msg.get("params").cloned().unwrap_or(Value::Null);
    let result = match method {
        "initialize" => json!({
            "protocolVersion": params.get("protocolVersion").and_then(Value::as_str).unwrap_or(DEFAULT_PROTOCOL),
            "capabilities": {"tools": {"listChanged": false}},
            "serverInfo": {"name": "Deadlock Simulator", "version": env!("CARGO_PKG_VERSION")},
            "instructions": "Deadlock combat simulator: hero and item data, damage/TTK math, build evaluation, optimization and combat simulation. Percentages are fractions (0.35 = 35%).",
        }),
        "ping" => json!({}),
        "tools/list" => json!({"tools": tool_list()}),
        "tools/call" => {
            let name = params.get("name").and_then(Value::as_str).unwrap_or("");
            let empty = json!({});
            let arguments = params.get("arguments").filter(|a| a.is_object()).unwrap_or(&empty);
            let (text, is_error) = match call_tool(data, name, arguments) {
                Ok(v) => (serde_json::to_string_pretty(&v).unwrap_or_default(), false),
                Err(e) => (e, true),
            };
            json!({"content": [{"type": "text", "text": text}], "isError": is_error})
        }
        "resources/list" => json!({"resources": []}),
        "prompts/list" => json!({"prompts": []}),
        _ => return Some(rpc_error(id, -32601, &format!("Method not found: {method}"))),
    };
    Some(json!({"jsonrpc": "2.0", "id": id, "result": result}))
}

/// Serve MCP over stdin/stdout until stdin closes.
pub fn run_stdio(mut data: GameData) -> io::Result<()> {
    eprintln!("deadlock-sim MCP server ready: {} heroes, {} items", data.heroes.len(), data.items.len());
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let response = match serde_json::from_str::<Value>(&line) {
            Ok(msg) => handle_message(&mut data, &msg),
            Err(e) => Some(rpc_error(Value::Null, -32700, &format!("Parse error: {e}"))),
        };
        if let Some(r) = response {
            writeln!(stdout, "{r}")?;
            stdout.flush()?;
        }
    }
    Ok(())
}
