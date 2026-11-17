//! Replays reference cases captured from the original Python implementation
//! (`tests/fixtures/python_reference.json`) and checks that every engine
//! output still matches.

use std::collections::{HashMap, HashSet};

use deadlock_sim::data::{self, GameData};
use deadlock_sim::engine::builds::{self, EvalOptions};
use deadlock_sim::engine::comparison;
use deadlock_sim::engine::damage::{self, ItemDamageParams, MeleeContext, MeleeParams, SpiritContext};
use deadlock_sim::engine::heroes;
use deadlock_sim::engine::scoring::{self, ScoreMode, ScoringConfig};
use deadlock_sim::engine::simulation::{self, AbilityUse, SimConfig, SimSettings};
use deadlock_sim::models::{AbilityConfig, Build, CombatConfig};
use deadlock_sim::patchnotes;
use serde_json::{json, Value};

fn norm_str(s: &str) -> String {
    // Python prints integral floats as "600.0"; reports here print "600".
    regex::Regex::new(r"(\d)\.0\b").unwrap().replace_all(s, "$1").into_owned()
}

fn close(expected: &Value, actual: &Value, path: &str) -> Result<(), String> {
    match (expected, actual) {
        (Value::Number(a), Value::Number(b)) => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            let tol = 1e-9_f64.max(1e-9 * a.abs().max(b.abs()));
            if (a - b).abs() <= tol {
                Ok(())
            } else {
                Err(format!("{path}: expected {a}, got {b}"))
            }
        }
        // Non-finite floats have no JSON form: the fixture spells them out, serde writes null.
        (Value::String(s), Value::Null) if matches!(s.as_str(), "inf" | "-inf" | "nan") => Ok(()),
        (Value::String(a), Value::String(b)) => {
            if a == b || norm_str(a) == norm_str(b) {
                Ok(())
            } else {
                Err(format!("{path}: expected {a:?}, got {b:?}"))
            }
        }
        (Value::Array(a), Value::Array(b)) => {
            if a.len() != b.len() {
                return Err(format!("{path}: expected {} elements, got {}", a.len(), b.len()));
            }
            a.iter().zip(b).enumerate().try_for_each(|(i, (x, y))| close(x, y, &format!("{path}[{i}]")))
        }
        (Value::Object(a), Value::Object(b)) => {
            for (k, v) in a {
                let other = b.get(k).ok_or_else(|| format!("{path}.{k}: missing"))?;
                close(v, other, &format!("{path}.{k}"))?;
            }
            match b.keys().find(|k| !a.contains_key(*k)) {
                Some(extra) => Err(format!("{path}.{extra}: unexpected key")),
                None => Ok(()),
            }
        }
        (a, b) if a == b => Ok(()),
        (a, b) => Err(format!("{path}: expected {a}, got {b}")),
    }
}

fn names(v: &Value) -> Vec<String> {
    v.as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default()
}

fn build_of(d: &GameData, v: &Value) -> Build {
    Build::new(names(v).iter().map(|n| d.items[n].clone()).collect())
}

fn conds(v: &Value) -> HashSet<String> {
    names(v).into_iter().collect()
}

fn f(v: &Value, k: &str) -> f64 {
    v[k].as_f64().unwrap()
}

fn float_map(v: &Value) -> HashMap<String, f64> {
    v.as_object().map(|o| o.iter().map(|(k, x)| (k.clone(), x.as_f64().unwrap())).collect()).unwrap_or_default()
}

fn run_case(d: &GameData, kind: &str, a: &Value) -> Value {
    let hero = |k: &str| &d.heroes[a[k].as_str().unwrap()];
    let boons = || a["boons"].as_i64().unwrap();
    match kind {
        "hero" => {
            let mut v = serde_json::to_value(hero("name")).unwrap();
            for ab in v["abilities"].as_array_mut().unwrap() {
                ab.as_object_mut().unwrap().shift_remove("properties");
            }
            v
        }
        "item" => {
            let mut v = serde_json::to_value(&d.items[a["name"].as_str().unwrap()]).unwrap();
            let o = v.as_object_mut().unwrap();
            o.shift_remove("raw_properties");
            o.shift_remove("tooltip_sections");
            v
        }
        "classify" => json!(simulation::classify_item(&d.items[a["name"].as_str().unwrap()])),
        "item_damage" => json!(damage::calculate_item_damage(
            &d.items[a["name"].as_str().unwrap()],
            &ItemDamageParams {
                current_spirit: f(a, "spirit"),
                boons: boons(),
                weapon_damage_bonus: 0.3,
                enemy_spirit_resist: 0.2,
                enemy_bullet_resist: 0.15,
                spirit_resist_shred: 0.1,
                bullet_resist_shred: 0.05,
                spirit_amp: 0.1,
            },
        )),
        "souls" => {
            let s = a["souls"].as_i64().unwrap();
            json!([data::souls_to_boons(s), data::souls_to_ability_points(s)])
        }
        "bullet" => {
            let cfg: CombatConfig = serde_json::from_value(a["config"].clone()).unwrap();
            let mut v = json!(damage::calculate_bullet(hero("hero"), &cfg));
            v["realistic_dps"] = json!(damage::dps_with_accuracy(hero("hero"), &cfg));
            v
        }
        "ttk" => {
            let cfg: CombatConfig = serde_json::from_value(a["config"].clone()).unwrap();
            json!(heroes::ttk(hero("attacker"), hero("defender"), &cfg))
        }
        "snapshot" => json!(heroes::snapshot(hero("hero"), boons())),
        "melee" => json!(damage::calculate_melee(
            hero("hero"),
            &MeleeParams {
                boons: boons(),
                weapon_damage_bonus: 0.4,
                enemy_bullet_resist: 0.25,
                shred_sources: vec![0.1],
                melee_damage_pct: 0.15,
                heavy_melee_damage_pct: 0.3,
            },
        )),
        "ability_breakdown" => json!(damage::hero_ability_breakdown(
            hero("hero"),
            boons(),
            25.0,
            &SpiritContext {
                current_spirit: 0.0,
                cooldown_reduction: 0.12,
                spirit_amp: 0.08,
                enemy_spirit_resist: 0.2,
                resist_shred: 0.1,
            },
        )),
        "growth" => json!(heroes::growth_percentage(hero("hero"), a["max_boons"].as_i64().unwrap())),
        "upgrades" => {
            let ab = &hero("hero").abilities[a["ability"].as_u64().unwrap() as usize];
            let tiers: Vec<i64> = a["tiers"].as_array().unwrap().iter().map(|t| t.as_i64().unwrap()).collect();
            let u = damage::apply_ability_upgrades(ab, &tiers);
            json!([u.base_damage, u.cooldown, u.duration, u.spirit_scaling])
        }
        "ability_spirit" => {
            let ab = &hero("hero").abilities[a["ability"].as_u64().unwrap() as usize];
            json!(damage::calculate_ability_spirit_dps(
                ab,
                &SpiritContext {
                    current_spirit: 60.0,
                    cooldown_reduction: 0.2,
                    spirit_amp: 0.15,
                    enemy_spirit_resist: 0.25,
                    resist_shred: 0.1,
                },
                Some(&vec![1, 2]),
            ))
        }
        "spirit_total" => {
            let ups = simulation::upgrades_from_json(&a["upgrades"]);
            if ups.is_empty() {
                json!(damage::hero_total_spirit_dps(hero("hero"), &SpiritContext::default(), None, &MeleeContext::default()))
            } else {
                json!(damage::hero_total_spirit_dps(
                    hero("hero"),
                    &SpiritContext {
                        current_spirit: 85.0,
                        cooldown_reduction: 0.18,
                        spirit_amp: 0.12,
                        enemy_spirit_resist: 0.3,
                        resist_shred: 0.15,
                    },
                    Some(&ups),
                    &MeleeContext { boons: 14, weapon_damage_bonus: 0.5, melee_damage_pct: 0.2 },
                ))
            }
        }
        "spirit" => {
            let cfg: AbilityConfig = serde_json::from_value(a["config"].clone()).unwrap();
            json!(damage::calculate_spirit(&cfg))
        }
        "rank" => json!(comparison::rank_heroes(
            &d.heroes,
            a["stat"].as_str().unwrap(),
            boons(),
            a["ascending"].as_bool().unwrap()
        )),
        "compare" => json!(comparison::compare_two(hero("a"), hero("b"), boons())),
        "cross_ttk" => {
            let cfg: CombatConfig = serde_json::from_value(a["config"].clone()).unwrap();
            json!(comparison::cross_ttk_matrix(&d.heroes, &cfg, Some(&names(&a["heroes"]))))
        }
        "aggregate" => json!(builds::aggregate_stats(&build_of(d, &a["items"]), Some(&conds(&a["conds"])))),
        "breakdown" => json!(builds::stat_breakdown(&build_of(d, &a["items"]), Some(&conds(&a["conds"])))),
        "evaluate" => {
            let ec = conds(&a["conds"]);
            let def_build = (!a["defender_items"].is_null()).then(|| build_of(d, &a["defender_items"]));
            let r = builds::evaluate_build(
                hero("hero"),
                &build_of(d, &a["items"]),
                &EvalOptions {
                    boons: boons(),
                    accuracy: 0.55,
                    headshot_rate: 0.15,
                    defender: a["defender"].as_str().map(|n| &d.heroes[n]),
                    defender_build: def_build.as_ref(),
                    enabled_conditionals: Some(&ec),
                },
            );
            json!({
                "build_stats": r.build_stats, "bullet_result": r.bullet_result,
                "ttk_result": r.ttk_result, "effective_hp": r.effective_hp,
            })
        }
        "optimize_dps" => json!(builds::best_dps_items(
            &d.items,
            hero("hero"),
            a["budget"].as_i64().unwrap(),
            boons(),
            a["max_items"].as_u64().unwrap() as usize,
            true,
        )
        .item_names()),
        "optimize_ttk" => json!(builds::best_ttk_items(
            &d.items,
            hero("hero"),
            hero("defender"),
            a["budget"].as_i64().unwrap(),
            boons(),
            0.5,
            0.15,
            12,
            true,
        )
        .item_names()),
        "score" => {
            let cand_names = names(&a["candidates"]);
            let cands: Vec<_> = cand_names.iter().map(|n| &d.items[n]).collect();
            let cfg = ScoringConfig {
                custom_item_dps: float_map(&a["custom_dps"]),
                custom_item_ehp: float_map(&a["custom_ehp"]),
                ..Default::default()
            };
            let mode = ScoreMode::parse(a["mode"].as_str().unwrap()).unwrap();
            json!(scoring::score_candidates(hero("hero"), &build_of(d, &a["items"]), &cands, boons(), mode, &cfg))
        }
        "sim" => {
            let settings: SimSettings = serde_json::from_value(a["settings"].clone()).unwrap();
            let schedule: Vec<AbilityUse> = a["schedule"]
                .as_array()
                .map(|s| {
                    s.iter()
                        .map(|e| AbilityUse {
                            ability_index: e[0].as_u64().unwrap() as usize,
                            first_use: e[1].as_f64().unwrap(),
                            use_on_cooldown: e[2].as_bool().unwrap(),
                        })
                        .collect()
                })
                .unwrap_or_default();
            let r = simulation::run_simulation(&SimConfig {
                attacker: hero("attacker").clone(),
                attacker_build: build_of(d, &a["attacker_items"]),
                defender: hero("defender").clone(),
                defender_build: build_of(d, &a["defender_items"]),
                settings,
                ability_schedule: schedule,
                attacker_ability_upgrades: simulation::upgrades_from_json(&a["upgrades"]),
                defender_ability_upgrades: simulation::upgrades_from_json(&a["def_upgrades"]),
                ..Default::default()
            });
            let checksum: f64 = r.timeline.iter().map(|e| e.time * e.damage).sum();
            let mut v = json!(r);
            let o = v.as_object_mut().unwrap();
            let timeline = o.shift_remove("timeline").unwrap();
            let tl = timeline.as_array().unwrap();
            o.insert("timeline_len".into(), json!(tl.len()));
            o.insert("timeline_checksum".into(), json!(checksum));
            o.insert("timeline_head".into(), json!(tl.iter().take(6).collect::<Vec<_>>()));
            v
        }
        "patch_parse" => json!(patchnotes::parse_patch_notes(a["text"].as_str().unwrap())),
        "patch_diff" | "patch_report" => {
            let mut changes = patchnotes::parse_patch_notes(a["text"].as_str().unwrap());
            let mut report = patchnotes::diff_patch(&mut changes, &d.heroes, Some(&d.items));
            if kind == "patch_report" {
                report.patch_date = "03-25-2026".into();
                report.patch_url = "u".into();
                return json!(patchnotes::format_report(&report));
            }
            json!(report
                .entries
                .iter()
                .map(|e| json!({
                    "status": e.status, "notes": e.notes, "current_value": e.current_value,
                    "hero": e.change.hero, "item": e.change.item,
                }))
                .collect::<Vec<_>>())
        }
        "patch_apply" => {
            let changes = patchnotes::parse_patch_notes(a["text"].as_str().unwrap());
            let mut heroes = d.heroes.clone();
            json!(patchnotes::apply_patch(&changes, &mut heroes, true))
        }
        "patch_numeric" => json!(patchnotes::try_parse_numeric(a["s"].as_str().unwrap())),
        other => panic!("unknown case kind {other}"),
    }
}

#[test]
fn matches_python_reference() {
    let d = GameData::load().expect("api cache");
    let raw = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/python_reference.json"))
        .expect("fixture");
    let fixture: Value = serde_json::from_str(&raw).unwrap();
    let cases = fixture["cases"].as_array().unwrap();
    assert!(cases.len() > 2900, "fixture looks truncated: {} cases", cases.len());

    let mut failures: Vec<String> = Vec::new();
    let mut failed_by_kind: HashMap<String, usize> = HashMap::new();
    for case in cases {
        let kind = case["kind"].as_str().unwrap();
        let actual = run_case(&d, kind, &case["args"]);
        if let Err(e) = close(&case["out"], &actual, "") {
            *failed_by_kind.entry(kind.to_string()).or_default() += 1;
            if failed_by_kind[kind] <= 3 {
                let args: String = case["args"].to_string().chars().take(300).collect();
                failures.push(format!("[{kind}] {args}\n    {e}"));
            }
        }
    }
    assert!(
        failures.is_empty(),
        "{} of {} cases differ {failed_by_kind:?}:\n{}",
        failed_by_kind.values().sum::<usize>(),
        cases.len(),
        failures.join("\n")
    );
}
