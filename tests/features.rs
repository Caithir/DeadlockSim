//! Tests for behavior beyond the reference port: components, optimizer, Monte
//! Carlo, curves, share codes, the service layer, the MCP server and patch scraping.

use std::sync::OnceLock;

use deadlock_sim::data::{self, GameData};
use deadlock_sim::engine::analysis::{self, summarize, BuildContext};
use deadlock_sim::engine::components::{add_item, component_closure, purchase_cost, AddOutcome};
use deadlock_sim::engine::montecarlo::{monte_carlo_ttk, MonteCarloParams};
use deadlock_sim::engine::optimizer::{optimize, recommend, Goal, OptimizeParams};
use deadlock_sim::engine::primitives::falloff_multiplier;
use deadlock_sim::models::{CombatConfig, Item};
use deadlock_sim::service::{self, BuildRequest, BuildSpec, Settings};
use deadlock_sim::share::{self, SharedBuild};
use deadlock_sim::{mcp, patchnotes, presentation};
use serde_json::{json, Value};

fn data() -> &'static GameData {
    static DATA: OnceLock<GameData> = OnceLock::new();
    DATA.get_or_init(|| GameData::load().expect("api cache"))
}

fn items(names: &[&str]) -> Vec<Item> {
    names.iter().map(|n| data().items[*n].clone()).collect()
}

fn spec(hero: &str, names: &[&str]) -> BuildSpec {
    BuildSpec { hero: hero.into(), items: names.iter().map(|s| s.to_string()).collect(), ..Default::default() }
}

// ── Data ──────────────────────────────────────────────────────────

#[test]
fn falloff_ranges_are_in_meters() {
    for hero in data().heroes.values().filter(|h| h.falloff_range_max > 0.0) {
        assert!(
            hero.falloff_range_min <= hero.falloff_range_max,
            "{}: {} > {}",
            hero.name,
            hero.falloff_range_min,
            hero.falloff_range_max
        );
        assert!(hero.falloff_range_max < 200.0, "{} falloff end {} is not meters", hero.name, hero.falloff_range_max);
    }
    let haze = &data().heroes["Haze"];
    assert_eq!(falloff_multiplier(haze.falloff_range_min, haze.falloff_range_min, haze.falloff_range_max), 1.0);
    assert!(
        (falloff_multiplier(haze.falloff_range_max, haze.falloff_range_min, haze.falloff_range_max) - 0.1).abs()
            < 1e-12
    );
}

#[test]
fn soul_tables_are_consistent() {
    assert_eq!(data::souls_to_boons(599), 0);
    assert_eq!(data::souls_to_boons(900), 1);
    assert_eq!(data::souls_to_boons(1_000_000), data::MAX_BOONS);
    for boons in 1..=data::MAX_BOONS {
        let souls = data::boons_to_souls(boons);
        assert_eq!(data::souls_to_boons(souls), boons);
        assert_eq!(data::souls_to_boons(souls - 1), boons - 1);
    }
}

#[test]
fn name_lookup_is_forgiving_and_suggests() {
    let d = data();
    assert_eq!(d.resolve_hero("haze").unwrap().name, "Haze");
    assert_eq!(d.resolve_item("toxic").unwrap().name, "Toxic Bullets");
    let err = d.hero_or_err("Hazz").unwrap_err();
    assert!(err.contains("Did you mean") && err.contains("Haze"), "{err}");
}

// ── Components ────────────────────────────────────────────────────

#[test]
fn buying_an_upgrade_consumes_its_component() {
    let d = data();
    let mut build = items(&["Extra Health", "Headshot Booster"]);
    let headhunter = &d.items["Headhunter"];
    assert_eq!(headhunter.component_names, vec!["Headshot Booster"]);
    assert_eq!(purchase_cost(headhunter, &build, &d.items), headhunter.cost - d.items["Headshot Booster"].cost);

    let outcome = add_item(&mut build, headhunter, &d.items);
    assert_eq!(outcome, AddOutcome::Added { consumed: vec!["Headshot Booster".into()] });
    let names: Vec<&str> = build.iter().map(|i| i.name.as_str()).collect();
    assert_eq!(names, ["Extra Health", "Headhunter"], "upgrade takes the component's slot");

    assert_eq!(add_item(&mut build, headhunter, &d.items), AddOutcome::Duplicate);
    assert_eq!(
        add_item(&mut build, &d.items["Headshot Booster"], &d.items),
        AddOutcome::Superseded { by: "Headhunter".into() }
    );
}

#[test]
fn build_is_limited_to_twelve_slots() {
    let d = data();
    let mut build: Vec<Item> = Vec::new();
    let standalone: Vec<&Item> =
        d.items.values().filter(|i| i.component_names.is_empty() && i.upgrades_to.is_empty()).take(13).collect();
    assert_eq!(standalone.len(), 13);
    for item in &standalone[..12] {
        assert!(matches!(add_item(&mut build, item, &d.items), AddOutcome::Added { .. }));
    }
    assert_eq!(add_item(&mut build, standalone[12], &d.items), AddOutcome::Full);
    assert_eq!(build.len(), 12);
}

#[test]
fn component_closure_never_contains_the_item_itself() {
    let d = data();
    for item in d.items.values() {
        let closure = component_closure(item, &d.items);
        assert!(!closure.contains(&item.name), "{} is its own component", item.name);
        for direct in &item.component_names {
            assert!(closure.contains(direct));
        }
    }
}

// ── Analysis ──────────────────────────────────────────────────────

#[test]
fn summary_derives_boons_from_souls() {
    let d = data();
    let mut ctx = BuildContext::new(&d.heroes["Infernus"], items(&["Extra Spirit", "Extra Health"]));
    let s = summarize(&ctx);
    assert_eq!(s.item_cost, 1600);
    assert_eq!(s.boons, data::souls_to_boons(1600));
    ctx.extra_souls = 8000;
    let richer = summarize(&ctx);
    assert_eq!(richer.boons, data::souls_to_boons(9600));
    assert!(richer.gun_dps > s.gun_dps && richer.hp_pool > s.hp_pool);
    ctx.boons_override = Some(0);
    assert_eq!(summarize(&ctx).boons, 0);
}

#[test]
fn power_curve_follows_the_purchase_order() {
    let d = data();
    let ctx = BuildContext::new(&d.heroes["Haze"], items(&["Headshot Booster", "Extra Health", "Toxic Bullets"]));
    let curve = analysis::power_curve(&ctx);
    assert_eq!(curve.len(), 4);
    assert_eq!(curve[0].souls, 0);
    assert_eq!(curve[3].souls, ctx.item_cost());
    assert!(curve.windows(2).all(|w| w[1].souls > w[0].souls && w[1].boons >= w[0].boons));
    assert_eq!(curve[2].item, "Extra Health");

    let order = analysis::suggest_purchase_order(&ctx);
    let mut got: Vec<&str> = order.iter().map(|i| i.name.as_str()).collect();
    got.sort();
    assert_eq!(got, ["Extra Health", "Headshot Booster", "Toxic Bullets"]);
}

#[test]
fn range_curve_drops_with_distance() {
    let d = data();
    let ctx = BuildContext::new(&d.heroes["Haze"], vec![]);
    let curve = analysis::range_curve(&ctx, 80.0, 1.0);
    assert_eq!(curve.len(), 81);
    assert!(curve.windows(2).all(|w| w[1].dps <= w[0].dps + 1e-9));
    assert!((curve[80].dps / curve[0].dps - 0.1).abs() < 1e-9);
    // The headline number is quoted at the default 20 m engagement distance.
    let at_default = curve.iter().find(|p| p.distance == CombatConfig::default().distance).unwrap();
    assert!((at_default.dps - summarize(&ctx).gun_dps).abs() < 1e-9);
}

#[test]
fn matchups_cover_every_hero_and_sort_by_margin() {
    let d = data();
    let mut ctx = BuildContext::new(&d.heroes["Haze"], items(&["Headhunter", "Battle Vest"]));
    ctx.accuracy = 0.6;
    ctx.headshot_rate = 0.1;
    let rows = analysis::matchups(&ctx, &d.heroes);
    assert_eq!(rows.len(), d.heroes.len());
    assert!(rows.windows(2).all(|w| w[0].margin >= w[1].margin));
    let bare = analysis::matchups(&ctx.with_items(vec![]), &d.heroes);
    let find = |rows: &[analysis::Matchup], n: &str| rows.iter().find(|m| m.opponent == n).unwrap().clone();
    let (with, without) = (find(&rows, "Abrams"), find(&bare, "Abrams"));
    assert!(with.time_to_die > without.time_to_die, "Battle Vest should make the build harder to kill");
}

// ── Optimizer ─────────────────────────────────────────────────────

#[test]
fn optimizer_respects_budget_slots_and_locked_items() {
    let d = data();
    let hero = &d.heroes["Infernus"];
    for (_, goal) in Goal::ALL {
        let ctx = BuildContext::new(hero, items(&["Extra Health"]));
        let p = OptimizeParams { goal, budget: 9000, ..Default::default() };
        let r = optimize(&ctx, &d.items, &p);
        assert!(r.total_cost <= 9000, "{goal:?} overspent: {}", r.total_cost);
        assert!(r.items.len() <= 12);
        assert!(r.items.contains(&"Extra Health".to_string()), "{goal:?} dropped a locked item");
        assert!(r.items.iter().all(|n| d.items[n].tier <= 4));
        let mut unique = r.items.clone();
        unique.sort();
        unique.dedup();
        assert_eq!(unique.len(), r.items.len());
    }
}

#[test]
fn optimizer_improves_its_own_goal() {
    let d = data();
    let ctx = BuildContext::new(&d.heroes["Haze"], vec![]);
    let gun = optimize(&ctx, &d.items, &OptimizeParams { goal: Goal::Gun, budget: 10000, ..Default::default() });
    let tank = optimize(&ctx, &d.items, &OptimizeParams { goal: Goal::Tank, budget: 10000, ..Default::default() });
    assert!(gun.after.gun_dps > gun.before.gun_dps * 1.3);
    assert!(tank.after.effective_hp > tank.before.effective_hp * 1.3);
    assert!(gun.after.gun_dps > tank.after.gun_dps);
    assert!(tank.after.effective_hp > gun.after.effective_hp);
}

#[test]
fn recommendations_are_affordable_and_helpful() {
    let d = data();
    let mut ctx = BuildContext::new(&d.heroes["Haze"], items(&["Headshot Booster"]));
    ctx.extra_souls = 2000;
    let recs = recommend(&ctx, &d.items, Goal::Gun, Some(2000), 4, 5);
    assert!(!recs.is_empty() && recs.len() <= 5);
    assert!(recs.iter().all(|r| r.purchase_cost <= 2000 && r.gain > 0.0));
    assert!(recs.windows(2).all(|w| w[0].gain_per_1k >= w[1].gain_per_1k));
    assert!(recs.iter().all(|r| r.item != "Headshot Booster"));
}

// ── Monte Carlo ───────────────────────────────────────────────────

#[test]
fn monte_carlo_is_reproducible_and_brackets_the_expected_ttk() {
    let d = data();
    let (atk, def) = (&d.heroes["Haze"], &d.heroes["Abrams"]);
    let cfg = CombatConfig { boons: 10, accuracy: 0.6, headshot_rate: 0.2, ..Default::default() };
    let p = MonteCarloParams { trials: 1500, seed: 7, max_time: 600.0 };
    let a = monte_carlo_ttk(atk, def, &cfg, &p);
    let b = monte_carlo_ttk(atk, def, &cfg, &p);
    assert_eq!(a.median, b.median);
    assert_eq!(a.histogram, b.histogram);
    let other = monte_carlo_ttk(atk, def, &cfg, &MonteCarloParams { seed: 8, ..p.clone() });
    assert_ne!(a.mean, other.mean);

    assert_eq!(a.kills, 1500);
    assert!(a.min <= a.p10 && a.p10 <= a.median && a.median <= a.p90 && a.p90 <= a.max);
    assert!((a.median - a.expected).abs() / a.expected < 0.15, "median {} vs expected {}", a.median, a.expected);
    assert_eq!(a.histogram.iter().map(|b| b.1).sum::<usize>(), a.kills);
}

#[test]
fn monte_carlo_with_perfect_aim_has_no_spread() {
    let d = data();
    let cfg = CombatConfig { accuracy: 1.0, headshot_rate: 0.0, ..Default::default() };
    let r = monte_carlo_ttk(&d.heroes["Haze"], &d.heroes["Abrams"], &cfg, &MonteCarloParams::default());
    assert_eq!(r.min, r.max);
    assert!((r.median - r.expected).abs() < 1e-9);
}

#[test]
fn monte_carlo_handles_heroes_that_cannot_hit() {
    let d = data();
    let cfg = CombatConfig { accuracy: 0.0, ..Default::default() };
    let r = monte_carlo_ttk(
        &d.heroes["Haze"],
        &d.heroes["Abrams"],
        &cfg,
        &MonteCarloParams { trials: 50, ..Default::default() },
    );
    assert_eq!(r.kills, 0);
    assert_eq!(r.kill_rate, 0.0);
}

// ── Share codes ───────────────────────────────────────────────────

#[test]
fn share_codes_round_trip() {
    let d = data();
    let build = SharedBuild {
        hero: "Haze".into(),
        items: vec!["Toxic Bullets".into(), "Headhunter".into(), "Extra Health".into()],
        extra_souls: 1234,
        ability_upgrades: [(0, 2), (3, 1)].into_iter().collect(),
    };
    let code = share::encode(&build, d).unwrap();
    assert!(code.starts_with("v1-") && code.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '.'));
    let (decoded, warnings) = share::decode(&code, d).unwrap();
    assert_eq!(decoded, build);
    assert!(warnings.is_empty());
}

#[test]
fn share_codes_reject_garbage_and_skip_unknown_items() {
    let d = data();
    for bad in ["", "hello", "v2-1-0-0000-", "v1-zzzzzzzzzzzzzzz-0-0000-", "v1-d-0-9999-"] {
        assert!(share::decode(bad, d).is_err(), "{bad:?} should be rejected");
    }
    let code = share::encode(&SharedBuild { hero: "Haze".into(), ..Default::default() }, d).unwrap();
    let (b, warnings) = share::decode(&format!("{code}zz"), d).unwrap();
    assert!(b.items.is_empty());
    assert_eq!(warnings.len(), 1);
}

// ── Service layer ─────────────────────────────────────────────────

#[test]
fn evaluate_reports_sheet_abilities_and_share_code() {
    let d = data();
    let req = BuildRequest { build: spec("haze", &["Toxic Bullets", "Extra Health"]), settings: Settings::default() };
    let v = service::evaluate(d, &req).unwrap();
    assert_eq!(v["hero"], "Haze");
    assert_eq!(v["souls"]["items"], 4000);
    assert_eq!(v["sheet"]["columns"].as_array().unwrap().len(), 3);
    assert_eq!(v["abilities"].as_array().unwrap().len(), 4);
    assert!(v["abilities"][0]["tiers"][0]["can_buy"].as_bool().unwrap());
    assert!(!v["abilities"][0]["tiers"][1]["can_buy"].as_bool().unwrap(), "T2 needs T1 first");
    let (decoded, _) = share::decode(v["share_code"].as_str().unwrap(), d).unwrap();
    assert_eq!(decoded.items, ["Toxic Bullets", "Extra Health"]);
}

#[test]
fn evaluate_warns_when_ability_points_are_overspent() {
    let d = data();
    let mut build = spec("Haze", &[]);
    build.ability_upgrades.insert(0, 3);
    let v = service::evaluate(d, &BuildRequest { build, settings: Settings::default() }).unwrap();
    assert_eq!(v["ap"]["spent"], 8);
    assert!(v["warnings"][0].as_str().unwrap().contains("AP"));
}

#[test]
fn service_reports_unknown_names_clearly() {
    let d = data();
    let err =
        service::evaluate(d, &BuildRequest { build: spec("Nobody", &[]), settings: Settings::default() }).unwrap_err();
    assert!(err.contains("Nobody"));
    let err =
        service::evaluate(d, &BuildRequest { build: spec("Haze", &["Sword of Doom"]), settings: Settings::default() })
            .unwrap_err();
    assert!(err.contains("Sword of Doom"));
}

#[test]
fn fast_scores_account_for_component_discounts() {
    let d = data();
    let req =
        service::ScoreRequest { build: spec("Haze", &["Headshot Booster"]), mode: "fast".into(), ..Default::default() };
    let v = service::score_items(d, &req).unwrap();
    let hh = &v["scores"]["Headhunter"];
    assert_eq!(hh["consumes"], json!(["Headshot Booster"]));
    assert_eq!(hh["purchase_cost"].as_i64().unwrap(), d.items["Headhunter"].cost - d.items["Headshot Booster"].cost);
    assert!(v["scores"].get("Headshot Booster").is_none(), "owned items are not candidates");
    assert!(service::score_items(d, &service::ScoreRequest { mode: "bogus".into(), ..req }).is_err());
}

#[test]
fn simulation_scores_cover_requested_candidates() {
    let d = data();
    let req = service::ScoreRequest {
        build: spec("Infernus", &["Extra Spirit"]),
        mode: "hybrid".into(),
        candidates: vec!["Mystic Shot".into(), "Extra Health".into()],
        ..Default::default()
    };
    let v = service::score_items(d, &req).unwrap();
    let scores = v["scores"].as_object().unwrap();
    assert_eq!(scores.len(), 2);
    assert!(scores["Mystic Shot"]["sim_dps_delta"].as_f64().unwrap() > 0.0);
    assert!(scores["Extra Health"]["sim_ehp_delta"].as_f64().unwrap() > 0.0);
}

#[test]
fn simulate_reports_both_sides_when_bidirectional() {
    let d = data();
    let mut req = service::SimRequest {
        build: spec("Haze", &["Toxic Bullets"]),
        defender: service::DefenderSpec { hero: "Abrams".into(), ..Default::default() },
        settings: Settings::default(),
    };
    let one = service::simulate(d, &req).unwrap();
    assert_eq!(one["sides"].as_array().unwrap().len(), 1);
    assert!(one["chart"]["cumulative"]["b"].is_null());
    assert!(one["sides"][0]["sources"].as_array().unwrap().iter().any(|s| s["source"] == "Toxic Bullets"));

    req.settings.bidirectional = true;
    req.settings.duration = 60.0;
    let two = service::simulate(d, &req).unwrap();
    assert_eq!(two["sides"].as_array().unwrap().len(), 2);
    assert!(two["winner"].is_string(), "a 60s duel should end with a winner");
    let cum = two["chart"]["cumulative"]["a"].as_array().unwrap();
    assert!(cum.windows(2).all(|w| w[1].as_f64() >= w[0].as_f64()));
}

#[test]
fn settings_are_clamped_and_schedule_respects_priority() {
    let d = data();
    let s = Settings { accuracy: 7.0, duration: -3.0, headshot_rate: f64::NAN, ..Default::default() }.sanitized();
    assert_eq!((s.accuracy, s.duration, s.headshot_rate), (1.0, 1.0, 0.0));

    let hero = &d.heroes["Infernus"];
    let default = Settings::default().ability_schedule(hero);
    assert!(default.len() >= 2);
    let (first, second) = (default[0].ability_index, default[1].ability_index);
    let mut custom = Settings::default();
    custom.ability_priority.insert(hero.name.clone(), vec![second, first]);
    custom.disabled_abilities.insert(hero.name.clone(), vec![first]);
    let schedule = custom.ability_schedule(hero);
    assert_eq!(schedule[0].ability_index, second);
    assert!(schedule.iter().all(|u| u.ability_index != first));
    assert!(Settings::default().conditionals().contains("bullet_resist_shred"));
    assert!(!Settings::default().conditionals().contains("bonus_hp"));
}

#[test]
fn compare_builds_marks_direction() {
    let d = data();
    let req = service::CompareBuildsRequest {
        a: spec("Haze", &[]),
        b: spec("Haze", &["Extra Health"]),
        settings: Settings::default(),
    };
    let v = service::compare_builds(d, &req).unwrap();
    assert_eq!(v["only_b"], json!(["Extra Health"]));
    let row = |label: &str| v["rows"].as_array().unwrap().iter().find(|r| r["label"] == label).unwrap().clone();
    assert!(row("HP + Shields")["delta"].as_f64().unwrap() > 0.0);
    assert_eq!(row("Souls")["higher_is_better"], false);
}

#[test]
fn catalog_is_complete_and_lean() {
    let v = service::catalog(data());
    assert_eq!(v["heroes"].as_array().unwrap().len(), data().heroes.len());
    let item = &v["items"][0];
    assert!(item.get("raw_properties").is_none());
    assert!(item["tooltip_html"].as_str().unwrap().contains("tt-name"));
    assert!(item["fallback_image"].as_str().unwrap().starts_with("/static/"));
}

#[test]
fn tooltips_escape_names_and_list_components() {
    let html = presentation::item_tooltip_html(&data().items["Headhunter"]);
    assert!(html.contains("Built from") && html.contains("Headshot Booster"));
    let mut odd = data().items["Extra Health"].clone();
    odd.name = "<script>alert(1)</script>".into();
    assert!(!presentation::item_tooltip_html(&odd).contains("<script>"));
    assert_eq!(presentation::commas(1234567), "1,234,567");
    assert_eq!(presentation::commas(-1500), "-1,500");
}

// ── MCP ───────────────────────────────────────────────────────────

fn rpc(d: &mut GameData, method: &str, params: Value) -> Value {
    mcp::handle_message(d, &json!({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})).unwrap()
}

fn tool(d: &mut GameData, name: &str, args: Value) -> (Value, bool) {
    let r = rpc(d, "tools/call", json!({"name": name, "arguments": args}));
    let text = r["result"]["content"][0]["text"].as_str().unwrap().to_string();
    (serde_json::from_str(&text).unwrap_or(Value::String(text)), r["result"]["isError"].as_bool().unwrap())
}

#[test]
fn mcp_handshake_and_tool_listing() {
    let mut d = data().clone();
    let init = rpc(&mut d, "initialize", json!({"protocolVersion": "2024-11-05"}));
    assert_eq!(init["result"]["protocolVersion"], "2024-11-05");
    assert!(init["result"]["capabilities"]["tools"].is_object());
    assert!(mcp::handle_message(&mut d, &json!({"jsonrpc": "2.0", "method": "notifications/initialized"})).is_none());
    let tools = rpc(&mut d, "tools/list", json!({}));
    let names: Vec<&str> =
        tools["result"]["tools"].as_array().unwrap().iter().map(|t| t["name"].as_str().unwrap()).collect();
    for expected in [
        "list_heroes",
        "get_hero",
        "get_hero_abilities",
        "list_items",
        "get_item",
        "calculate_bullet_dps",
        "calculate_spirit_dps",
        "calculate_ttk",
        "scaling_curve",
        "compare_heroes",
        "rank_heroes",
        "evaluate_build",
        "optimize_build",
        "reload_data",
        "simulate_combat",
        "monte_carlo_ttk",
        "recommend_items",
    ] {
        assert!(names.contains(&expected), "missing tool {expected}");
    }
    assert_eq!(rpc(&mut d, "nope", json!({}))["error"]["code"], -32601);
}

#[test]
fn mcp_tools_return_results_and_flag_errors() {
    let mut d = data().clone();
    let (heroes, err) = tool(&mut d, "list_heroes", json!({}));
    assert!(!err && heroes.as_array().unwrap().len() == d.heroes.len());

    let (ttk, err) =
        tool(&mut d, "calculate_ttk", json!({"attacker_name": "haze", "defender_name": "abrams", "boons": 5}));
    assert!(!err && ttk["realistic_ttk"].as_f64().unwrap() > ttk["ttk_seconds"].as_f64().unwrap());

    let (build, err) = tool(
        &mut d,
        "evaluate_build",
        json!({"hero_name": "Haze", "item_names": ["toxic bullets"], "defender_name": "Abrams"}),
    );
    assert!(!err && build["total_cost"] == 3200 && build["ttk_result"].is_object() && build["share_code"].is_string());

    let (sim, err) = tool(
        &mut d,
        "simulate_combat",
        json!({"hero_name": "Haze", "defender_name": "Abrams", "ability_upgrades": {"0": 1}}),
    );
    assert!(!err && sim["sides"][0]["dps"].as_f64().unwrap() > 0.0 && sim.get("chart").is_none());

    let (opt, err) = tool(&mut d, "optimize_build", json!({"hero_name": "Haze", "budget": 5000, "goal": "dps"}));
    assert!(!err && opt["total_cost"].as_i64().unwrap() <= 5000);

    let (msg, err) = tool(&mut d, "get_hero", json!({"name": "Nobody"}));
    assert!(err && msg.as_str().unwrap().contains("not found"));
    let (_, err) = tool(&mut d, "no_such_tool", json!({}));
    assert!(err);
}

// ── Patch notes scraping ──────────────────────────────────────────

#[test]
fn changelog_index_yields_newest_thread() {
    let html =
        r#"<a href="/threads/03-25-2026-update.121766/">x</a> <a href="/threads/03-10-2026-update.120000/">y</a>"#;
    let (url, date) = patchnotes::latest_patch_in(html).unwrap();
    assert_eq!(url, "https://forums.playdeadlock.com/threads/03-25-2026-update.121766/");
    assert_eq!(date, "03-25-2026");
    assert!(patchnotes::latest_patch_in("<html>nothing</html>").is_none());
}

#[test]
fn thread_html_is_reduced_to_change_lines() {
    let html = "<div class=\"bbWrapper\">\n- Infernus: Afterburn DPS increased from 12 to 14<br />\n\
                - Infernus: Afterburn DPS increased from 12 to 14<br />\n- Wraith: Card Trick &amp; Deck now reworked<br />\n\
                - truncated line: something...\n- no colon here\n</div>";
    let text = patchnotes::extract_patch_lines(html);
    assert_eq!(text, "Infernus: Afterburn DPS increased from 12 to 14\nWraith: Card Trick & Deck now reworked");
    let changes = patchnotes::parse_patch_notes(&text);
    assert_eq!(
        (changes[0].ability.as_str(), changes[0].stat.as_str(), changes[0].new_numeric),
        ("Afterburn", "DPS", Some(14.0))
    );
    assert_eq!(changes[1].change_type, "mechanical");
}

#[test]
fn applying_a_patch_mutates_only_when_asked() {
    let d = data();
    let changes = patchnotes::parse_patch_notes(
        "Infernus: Base health increased from 1 to 999\nHaze: Gun Falloff changed from 20->46 to 22->58",
    );
    let mut heroes = d.heroes.clone();
    let dry = patchnotes::apply_patch(&changes, &mut heroes, true);
    assert_eq!(dry.len(), 2);
    assert_eq!(heroes["Infernus"].base_hp, d.heroes["Infernus"].base_hp);
    patchnotes::apply_patch(&changes, &mut heroes, false);
    assert_eq!(heroes["Infernus"].base_hp, 999.0);
    assert_eq!((heroes["Haze"].falloff_range_min, heroes["Haze"].falloff_range_max), (22.0, 58.0));
}

#[test]
fn saved_patch_names_cannot_escape_the_patch_directory() {
    assert!(patchnotes::load_saved_patch("../../Cargo").is_none());
    assert!(patchnotes::load_saved_patch("").is_none());
    assert!(patchnotes::load_saved_patch("03-25-2026").is_some());
}
