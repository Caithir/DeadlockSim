//! `deadlock-sim` command line: interactive menu, scriptable subcommands,
//! the web UI server and the MCP server.

use std::collections::BTreeMap;
use std::process::ExitCode;

use clap::{Args, CommandFactory, Parser, Subcommand};
use serde_json::{json, Value};

use deadlock_sim::data::GameData;
use deadlock_sim::engine::damage::SpiritContext;
use deadlock_sim::models::CombatConfig;
use deadlock_sim::presentation::{commas, pct};
use deadlock_sim::service::{self, BuildRequest, BuildSpec, DefenderSpec, Settings};
use deadlock_sim::{api_client, cli, mcp, patchnotes, share, web};

#[derive(Parser)]
#[command(name = "deadlock-sim", version, about = "Deadlock damage and combat simulator")]
struct Cli {
    /// Print machine-readable JSON instead of text.
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Args, Clone)]
struct BuildArgs {
    /// Hero name (partial names accepted).
    hero: Option<String>,
    /// Item to include (repeatable, or comma-separated).
    #[arg(short, long = "item", value_delimiter = ',')]
    items: Vec<String>,
    /// Load hero, items and upgrades from a share code.
    #[arg(long)]
    code: Option<String>,
    /// Souls gathered beyond what the items cost.
    #[arg(long, default_value_t = 0)]
    souls: i64,
    /// Fix the boon count instead of deriving it from souls.
    #[arg(long)]
    boons: Option<i64>,
    /// Ability upgrades as index=tier, e.g. `-u 0=2 -u 3=1`.
    #[arg(short = 'u', long = "upgrade", value_parser = parse_upgrade)]
    upgrades: Vec<(usize, i64)>,
    /// Accuracy in percent.
    #[arg(long, default_value_t = 65.0)]
    accuracy: f64,
    /// Headshot rate in percent.
    #[arg(long, default_value_t = 10.0)]
    headshots: f64,
    /// Engagement range in meters.
    #[arg(long, default_value_t = 20.0)]
    distance: f64,
}

#[derive(Args, Clone)]
struct DefenderArgs {
    /// Defender hero.
    #[arg(long = "vs")]
    defender: String,
    /// Defender item (repeatable, or comma-separated).
    #[arg(long = "vs-item", value_delimiter = ',')]
    defender_items: Vec<String>,
    /// Defender boon count.
    #[arg(long = "vs-boons", default_value_t = 10)]
    defender_boons: i64,
}

fn parse_upgrade(s: &str) -> Result<(usize, i64), String> {
    let (i, t) = s.split_once('=').ok_or("expected index=tier, e.g. 0=2")?;
    let idx: usize = i.trim().parse().map_err(|_| "ability index must be a number (0-3)")?;
    let tier: i64 = t.trim().parse().map_err(|_| "tier must be a number (1-3)")?;
    if !(0..=3).contains(&tier) {
        return Err("tier must be between 0 and 3".into());
    }
    Ok((idx, tier))
}

#[derive(Subcommand)]
enum Command {
    /// Interactive menu (the default when no command is given).
    Interactive,
    /// Start the web UI.
    Serve {
        /// Port to listen on.
        #[arg(long, env = "PORT", default_value_t = 8080)]
        port: u16,
        /// Address to bind (use 0.0.0.0 to accept remote connections).
        #[arg(long, env = "HOST", default_value = "127.0.0.1")]
        host: String,
    },
    /// Run the MCP server over stdio.
    Mcp,
    /// Refresh hero and item data from the Deadlock Assets API.
    Refresh,
    /// List heroes.
    Heroes,
    /// Show a hero's base stats and abilities.
    Hero { name: String },
    /// List shop items.
    Items {
        /// weapon, vitality or spirit.
        #[arg(long)]
        category: Option<String>,
        #[arg(long)]
        tier: Option<i64>,
        /// Only items whose name contains this text.
        #[arg(long)]
        search: Option<String>,
    },
    /// Show an item's stats.
    Item { name: String },
    /// Bullet damage for a hero.
    Bullet {
        hero: String,
        #[arg(long, default_value_t = 0)]
        boons: i64,
        /// Weapon damage bonus in percent.
        #[arg(long, default_value_t = 0.0)]
        weapon: f64,
        /// Fire rate bonus in percent.
        #[arg(long, default_value_t = 0.0)]
        fire_rate: f64,
        /// Enemy bullet resist in percent.
        #[arg(long, default_value_t = 0.0)]
        resist: f64,
        /// Bullet resist shred in percent.
        #[arg(long, default_value_t = 0.0)]
        shred: f64,
        #[arg(long, default_value_t = 100.0)]
        accuracy: f64,
        #[arg(long, default_value_t = 0.0)]
        headshots: f64,
        #[arg(long, default_value_t = 20.0)]
        distance: f64,
    },
    /// Ability damage for a hero at a spirit power.
    Spirit {
        hero: String,
        #[arg(long, default_value_t = 0.0)]
        spirit: f64,
        /// Cooldown reduction in percent.
        #[arg(long, default_value_t = 0.0)]
        cdr: f64,
        /// Enemy spirit resist in percent.
        #[arg(long, default_value_t = 0.0)]
        resist: f64,
    },
    /// Time-to-kill between two heroes without items.
    Ttk {
        attacker: String,
        defender: String,
        #[arg(long, default_value_t = 0)]
        boons: i64,
        #[arg(long, default_value_t = 65.0)]
        accuracy: f64,
        #[arg(long, default_value_t = 10.0)]
        headshots: f64,
        /// Defender bullet resist in percent.
        #[arg(long, default_value_t = 0.0)]
        resist: f64,
    },
    /// Boon scaling curve for a hero.
    Scaling {
        hero: String,
        #[arg(long, default_value_t = 35)]
        max_boons: i64,
    },
    /// Compare two heroes' base stats.
    Compare {
        a: String,
        b: String,
        #[arg(long, default_value_t = 0)]
        boons: i64,
    },
    /// Rank heroes by a stat (dps, hp, dpm, bullet_damage, fire_rate, dps_growth, hp_growth).
    Rank {
        #[arg(default_value = "dps")]
        stat: String,
        #[arg(long, default_value_t = 0)]
        boons: i64,
        #[arg(long, default_value_t = 10)]
        top: usize,
    },
    /// Evaluate a build: stat sheet and share code.
    Build(BuildArgs),
    /// Find a strong build within a soul budget.
    Optimize {
        #[command(flatten)]
        build: BuildArgs,
        /// gun, spirit, damage, tank or balanced.
        #[arg(long, default_value = "balanced")]
        goal: String,
        #[arg(long, default_value_t = 15000)]
        budget: i64,
        #[arg(long, default_value_t = 12)]
        max_items: usize,
        /// Highest item tier to consider.
        #[arg(long, default_value_t = 4)]
        max_tier: i64,
    },
    /// Rank the best next purchases for a build.
    Recommend {
        #[command(flatten)]
        build: BuildArgs,
        #[arg(long, default_value = "balanced")]
        goal: String,
        /// Only purchases affordable with this many souls.
        #[arg(long)]
        available: Option<i64>,
        #[arg(long, default_value_t = 8)]
        top: usize,
    },
    /// Simulate a fight against a defender.
    Simulate {
        #[command(flatten)]
        build: BuildArgs,
        #[command(flatten)]
        defender: DefenderArgs,
        /// Fight length in seconds.
        #[arg(long, default_value_t = 15.0)]
        duration: f64,
        /// The defender fights back.
        #[arg(long)]
        bidirectional: bool,
    },
    /// Roll a gun duel many times and show the spread of kill times.
    Montecarlo {
        #[command(flatten)]
        build: BuildArgs,
        #[command(flatten)]
        defender: DefenderArgs,
        #[arg(long, default_value_t = 2000)]
        trials: usize,
        #[arg(long)]
        seed: Option<u64>,
    },
    /// Gun-duel matchups of a build against every hero.
    Matchups(BuildArgs),
    /// Fetch patch notes and diff or apply them against the data.
    Patch {
        /// Apply numeric changes to the loaded data (in memory) and list them.
        #[arg(long)]
        apply: bool,
        /// Show what would be applied.
        #[arg(long)]
        dry_run: bool,
        /// Refresh API data first.
        #[arg(long)]
        refresh: bool,
        /// Specific patch thread URL.
        #[arg(long)]
        url: Option<String>,
        /// Use a saved patch (MM-DD-YYYY) instead of fetching.
        #[arg(long)]
        date: Option<String>,
    },
    /// Print shell completions.
    Completions { shell: clap_complete::Shell },
}

impl BuildArgs {
    fn settings(&self) -> Settings {
        Settings {
            accuracy: self.accuracy / 100.0,
            headshot_rate: self.headshots / 100.0,
            distance: self.distance,
            ..Default::default()
        }
    }

    fn spec(&self, data: &GameData) -> Result<BuildSpec, String> {
        let mut spec = match &self.code {
            Some(code) => {
                let (b, warnings) = share::decode(code, data)?;
                for w in warnings {
                    eprintln!("warning: {w}");
                }
                BuildSpec {
                    hero: b.hero,
                    items: b.items,
                    extra_souls: b.extra_souls,
                    ability_upgrades: b.ability_upgrades,
                    boons: None,
                }
            }
            None => BuildSpec::default(),
        };
        if let Some(h) = &self.hero {
            spec.hero = h.clone();
        }
        if spec.hero.is_empty() {
            return Err("Specify a hero or a --code.".into());
        }
        // Explicit items are added on top of the code's, consuming components.
        for name in &self.items {
            let r = service::add_item(data, &spec.items, name)?;
            match r["status"].as_str() {
                Some("added") | Some("upgraded") => {
                    spec.items = r["items"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect();
                }
                _ => eprintln!("warning: {}", r["message"].as_str().unwrap_or("")),
            }
        }
        if self.souls > 0 {
            spec.extra_souls = self.souls;
        }
        spec.boons = self.boons;
        spec.ability_upgrades.extend(self.upgrades.iter().copied().collect::<BTreeMap<_, _>>());
        Ok(spec)
    }
}

impl DefenderArgs {
    fn spec(&self) -> DefenderSpec {
        DefenderSpec {
            hero: self.defender.clone(),
            items: self.defender_items.clone(),
            boons: self.defender_boons,
            ..Default::default()
        }
    }
}

fn time(v: &Value) -> String {
    match v.as_f64() {
        Some(t) => format!("{t:.2}s"),
        None => "-".into(),
    }
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap_or(0.0)
}

fn print_json(v: &Value) {
    println!("{}", serde_json::to_string_pretty(v).unwrap_or_default());
}

fn load() -> Result<GameData, String> {
    api_client::ensure_data_available()?;
    GameData::load()
}

fn run(args: Cli) -> Result<(), String> {
    let json_out = args.json;
    let command = args.command.unwrap_or(Command::Interactive);
    match command {
        Command::Completions { shell } => {
            clap_complete::generate(shell, &mut Cli::command(), "deadlock-sim", &mut std::io::stdout());
            return Ok(());
        }
        Command::Refresh => {
            println!("Refreshing data from {}...", api_client::base_url());
            let s = api_client::refresh_all_data("english")?;
            if json_out {
                print_json(&json!(s));
            } else {
                println!(
                    "Refreshed: {} heroes, {} items ({} upgrades, {} abilities, {} weapons).",
                    s.heroes, s.items, s.upgrades, s.abilities, s.weapons
                );
                if !s.failed_heroes.is_empty() {
                    println!("Could not fetch abilities for: {}", s.failed_heroes.join(", "));
                }
            }
            return Ok(());
        }
        _ => {}
    }

    let data = load()?;
    let d = &data;
    match command {
        Command::Interactive => cli::run_interactive(d),
        Command::Serve { port, host } => {
            let rt = tokio::runtime::Runtime::new().map_err(|e| e.to_string())?;
            rt.block_on(web::serve(data, &host, port))?;
        }
        Command::Mcp => mcp::run_stdio(data).map_err(|e| e.to_string())?,
        Command::Heroes => {
            if json_out {
                print_json(&json!(d.hero_names()));
            } else {
                d.hero_names().iter().for_each(|n| println!("{n}"));
            }
        }
        Command::Hero { name } => {
            let hero = d.hero_or_err(&name)?;
            if json_out {
                print_json(&json!(hero));
            } else {
                cli::display_hero_stats(hero);
            }
        }
        Command::Items { category, tier, search } => {
            let search = search.map(|s| s.to_lowercase());
            let mut items: Vec<_> = d
                .items
                .values()
                .filter(|i| category.as_ref().is_none_or(|c| i.category.eq_ignore_ascii_case(c)))
                .filter(|i| tier.is_none_or(|t| i.tier == t))
                .filter(|i| search.as_ref().is_none_or(|s| i.name.to_lowercase().contains(s)))
                .collect();
            items.sort_by(|a, b| (&a.category, a.tier, a.cost, &a.name).cmp(&(&b.category, b.tier, b.cost, &b.name)));
            if json_out {
                print_json(&json!(items
                    .iter()
                    .map(|i| json!({"name": i.name, "category": i.category, "tier": i.tier, "cost": i.cost}))
                    .collect::<Vec<_>>()));
            } else {
                for i in &items {
                    println!("{:<9} T{}  {:>6}  {}", i.category, i.tier, commas(i.cost), i.name);
                }
                println!("\n{} items", items.len());
            }
        }
        Command::Item { name } => {
            let item = d
                .resolve_item(&name)
                .ok_or_else(|| format!("Item '{name}' not found.{}", deadlock_sim::data::suggest(&d.items, &name)))?;
            if json_out {
                print_json(&json!(item));
            } else {
                println!(
                    "{}",
                    cli::header(&format!(
                        "{} ({} T{}, {} souls)",
                        item.name,
                        item.category,
                        item.tier,
                        commas(item.cost)
                    ))
                );
                for field in deadlock_sim::models::ITEM_STAT_FIELDS {
                    let v = item.stat(field);
                    if v != 0.0 {
                        println!("  {field:<26} {v}");
                    }
                }
                for (k, v) in &item.conditional_stats {
                    println!("  {k:<26} {v} (conditional)");
                }
                if !item.component_names.is_empty() {
                    println!("  Built from: {}", item.component_names.join(", "));
                }
                if !item.upgrades_to.is_empty() {
                    println!("  Upgrades to: {}", item.upgrades_to);
                }
            }
        }
        Command::Bullet { hero, boons, weapon, fire_rate, resist, shred, accuracy, headshots, distance } => {
            let hero = d.hero_or_err(&hero)?;
            let config = CombatConfig {
                boons,
                weapon_damage_bonus: weapon / 100.0,
                fire_rate_bonus: fire_rate / 100.0,
                enemy_bullet_resist: resist / 100.0,
                shred: if shred > 0.0 { vec![shred / 100.0] } else { vec![] },
                accuracy: accuracy / 100.0,
                headshot_rate: headshots / 100.0,
                headshot_multiplier: hero.crit_bonus_start,
                distance,
                ..Default::default()
            };
            if json_out {
                let mut v = json!(deadlock_sim::engine::damage::calculate_bullet(hero, &config));
                v["realistic_dps"] = json!(deadlock_sim::engine::damage::dps_with_accuracy(hero, &config));
                print_json(&v);
            } else {
                cli::display_bullet_calc(hero, &config);
            }
        }
        Command::Spirit { hero, spirit, cdr, resist } => {
            let hero = d.hero_or_err(&hero)?;
            let ctx = SpiritContext {
                current_spirit: spirit,
                cooldown_reduction: cdr / 100.0,
                enemy_spirit_resist: resist / 100.0,
                ..Default::default()
            };
            if json_out {
                print_json(&json!(deadlock_sim::engine::damage::hero_ability_breakdown(hero, 0, spirit, &ctx)));
            } else {
                cli::display_spirit(hero, &ctx);
            }
        }
        Command::Ttk { attacker, defender, boons, accuracy, headshots, resist } => {
            let (a, b) = (d.hero_or_err(&attacker)?, d.hero_or_err(&defender)?);
            let config = CombatConfig {
                boons,
                accuracy: accuracy / 100.0,
                headshot_rate: headshots / 100.0,
                headshot_multiplier: a.crit_bonus_start,
                enemy_bullet_resist: resist / 100.0,
                ..Default::default()
            };
            if json_out {
                print_json(&json!(deadlock_sim::engine::heroes::ttk(a, b, &config)));
            } else {
                cli::display_ttk(a, b, &config);
            }
        }
        Command::Scaling { hero, max_boons } => {
            if json_out {
                print_json(&service::scaling(d, &hero, max_boons)?);
            } else {
                cli::display_scaling(d.hero_or_err(&hero)?, max_boons);
            }
        }
        Command::Compare { a, b, boons } => {
            if json_out {
                print_json(&service::compare_heroes(d, &a, &b, boons)?["at"]);
            } else {
                cli::display_comparison(d.hero_or_err(&a)?, d.hero_or_err(&b)?, boons);
            }
        }
        Command::Rank { stat, boons, top } => {
            let v = service::rankings(d, &stat, boons, top)?;
            if json_out {
                print_json(&v);
            } else {
                cli::display_rankings(d, &stat, boons, top);
            }
        }
        Command::Build(b) => {
            let (spec, settings) = (b.spec(d)?, b.settings());
            let view = service::evaluate(d, &BuildRequest { build: spec.clone(), settings: settings.clone() })?;
            if json_out {
                print_json(&view);
            } else {
                cli::display_build(&spec.context(d, &settings)?, &view);
            }
        }
        Command::Optimize { build, goal, budget, max_items, max_tier } => {
            let v = service::optimize(
                d,
                &service::OptimizeRequest {
                    build: build.spec(d)?,
                    settings: build.settings(),
                    goal,
                    budget,
                    max_items,
                    max_tier,
                    exclude_conditional: false,
                },
            )?;
            if json_out {
                print_json(&v);
            } else {
                let r = &v["result"];
                println!(
                    "{}",
                    cli::header(&format!(
                        "Optimized Build: {} ({}, {} build)",
                        v["hero"].as_str().unwrap_or(""),
                        r["goal"].as_str().unwrap_or(""),
                        v["build_type"].as_str().unwrap_or("")
                    ))
                );
                println!(
                    "  Budget: {} souls | Spent: {} souls",
                    commas(budget),
                    commas(r["total_cost"].as_i64().unwrap_or(0))
                );
                println!("  Suggested purchase order:");
                for (i, name) in v["purchase_order"].as_array().into_iter().flatten().enumerate() {
                    let n = name.as_str().unwrap_or("");
                    println!("    {:2}. {n} ({})", i + 1, commas(d.items[n].cost));
                }
                println!("\n  {:<14} {:>10} {:>10}", "", "Before", "After");
                for (label, key) in
                    [("Gun DPS", "gun_dps"), ("Spirit DPS", "spirit_dps"), ("Effective HP", "effective_hp")]
                {
                    println!("  {label:<14} {:>10.1} {:>10.1}", f(&r["before"][key]), f(&r["after"][key]));
                }
                let items: Vec<String> =
                    r["items"].as_array().into_iter().flatten().filter_map(|x| x.as_str().map(String::from)).collect();
                if let Ok(code) = share::encode(
                    &share::SharedBuild { hero: v["hero"].as_str().unwrap_or("").into(), items, ..Default::default() },
                    d,
                ) {
                    println!("\n  Share code: {code}");
                }
            }
        }
        Command::Recommend { build, goal, available, top } => {
            let v = service::recommend(
                d,
                &service::RecommendRequest {
                    build: build.spec(d)?,
                    settings: build.settings(),
                    goal,
                    available_souls: available,
                    limit: top,
                },
            )?;
            if json_out {
                print_json(&v);
            } else {
                println!(
                    "{}",
                    cli::header(&format!(
                        "Next purchases: {} (goal: {})",
                        v["hero"].as_str().unwrap_or(""),
                        v["goal"].as_str().unwrap_or("")
                    ))
                );
                println!("  {:<26} {:>7} {:>9} {:>10} {:>9}", "Item", "Pay", "Gun DPS", "Spirit DPS", "EHP");
                for r in v["recommendations"].as_array().into_iter().flatten() {
                    println!(
                        "  {:<26} {:>7} {:>+9.1} {:>+10.1} {:>+9.0}",
                        r["item"].as_str().unwrap_or(""),
                        commas(r["purchase_cost"].as_i64().unwrap_or(0)),
                        f(&r["gun_dps_delta"]),
                        f(&r["spirit_dps_delta"]),
                        f(&r["ehp_delta"])
                    );
                }
            }
        }
        Command::Simulate { build, defender, duration, bidirectional } => {
            let settings = Settings { duration, bidirectional, ..build.settings() };
            let v = service::simulate(
                d,
                &service::SimRequest { build: build.spec(d)?, defender: defender.spec(), settings },
            )?;
            if json_out {
                print_json(&v);
            } else {
                println!(
                    "{}",
                    cli::header(&format!(
                        "Simulation: {} vs {}",
                        v["attacker"]["name"].as_str().unwrap_or(""),
                        v["defender"]["name"].as_str().unwrap_or("")
                    ))
                );
                println!(
                    "  Duration: {:.2}s | Defender pool: {:.0} HP ({} boons)",
                    f(&v["duration"]),
                    f(&v["defender"]["pool"]),
                    v["defender"]["boons"]
                );
                match v["winner"].as_str() {
                    Some("a") => println!(
                        "  Winner: {} at {}",
                        v["attacker"]["name"].as_str().unwrap_or(""),
                        time(&v["kill_time"])
                    ),
                    Some("b") => println!(
                        "  Winner: {} at {}",
                        v["defender"]["name"].as_str().unwrap_or(""),
                        time(&v["defender_kill_time"])
                    ),
                    _ if v["kill_time"].is_number() => println!("  Target killed at {}", time(&v["kill_time"])),
                    _ => println!("  Target survived with {:.0} HP", f(&v["target_hp_remaining"])),
                }
                for side in v["sides"].as_array().into_iter().flatten() {
                    println!(
                        "\n  {} — {:.1} DPS, {:.0} total damage",
                        side["name"].as_str().unwrap_or(""),
                        f(&side["dps"]),
                        f(&side["total_damage"])
                    );
                    for s in side["sources"].as_array().into_iter().flatten() {
                        println!(
                            "    {:<28} {:>9.0} {:>8.1} DPS {:>6}",
                            s["source"].as_str().unwrap_or(""),
                            f(&s["damage"]),
                            f(&s["dps"]),
                            pct(f(&s["share"]))
                        );
                    }
                    println!("    bullets {} | reloads {}", side["bullets_fired"], side["reloads"]);
                }
            }
        }
        Command::Montecarlo { build, defender, trials, seed } => {
            let v = service::monte_carlo(
                d,
                &service::MonteCarloRequest {
                    build: build.spec(d)?,
                    defender: defender.spec(),
                    settings: build.settings(),
                    trials,
                    seed,
                },
            )?;
            if json_out {
                print_json(&v);
            } else {
                let x = &v["distribution"];
                println!(
                    "{}",
                    cli::header(&format!(
                        "Monte Carlo TTK: {} vs {}",
                        v["attacker"].as_str().unwrap_or(""),
                        v["defender"].as_str().unwrap_or("")
                    ))
                );
                println!(
                    "  {} duels at {} accuracy, {} headshots, {:.0} HP target",
                    x["trials"],
                    pct(f(&v["accuracy"])),
                    pct(f(&v["headshot_rate"])),
                    f(&x["target_hp"])
                );
                println!("  Kill rate:      {}", pct(f(&x["kill_rate"])));
                println!("  One-magazine:   {}", pct(f(&x["one_mag_rate"])));
                println!("  Median TTK:     {}   (expected-value model: {})", time(&x["median"]), time(&x["expected"]));
                println!("  Typical range:  {} - {} (10th-90th percentile)", time(&x["p10"]), time(&x["p90"]));
                println!("  Fastest/slowest: {} / {}", time(&x["min"]), time(&x["max"]));
            }
        }
        Command::Matchups(b) => {
            let v = service::matchups(d, &BuildRequest { build: b.spec(d)?, settings: b.settings() })?;
            if json_out {
                print_json(&v);
            } else {
                println!(
                    "{}",
                    cli::header(&format!(
                        "Gun duels: {} at {} boons — wins {} of {}",
                        v["hero"].as_str().unwrap_or(""),
                        v["boons"],
                        v["wins"],
                        v["total"]
                    ))
                );
                println!("  {:<16} {:>8} {:>9} {:>9} {:>8}", "Opponent", "HP", "You kill", "They kill", "Margin");
                for m in v["matchups"].as_array().into_iter().flatten() {
                    let margin = match m["margin"].as_f64() {
                        Some(x) => format!("{x:+.2}s"),
                        None => "-".into(),
                    };
                    println!(
                        "  {:<16} {:>8.0} {:>9} {:>9} {:>8}",
                        m["opponent"].as_str().unwrap_or(""),
                        f(&m["opponent_hp"]),
                        time(&m["time_to_kill"]),
                        time(&m["time_to_die"]),
                        margin
                    );
                }
            }
        }
        Command::Patch { apply, dry_run, refresh, url, date } => {
            let mut data = data;
            if refresh {
                println!("Refreshing API data...");
                api_client::refresh_all_data("english")?;
                data = GameData::load()?;
            }
            let (url, date, text) = if let Some(date) = date {
                let saved = patchnotes::load_saved_patch(&date).ok_or_else(|| {
                    format!("No saved patch for '{date}'. Saved: {}", patchnotes::list_saved_patches().join(", "))
                })?;
                (String::from("(saved)"), date, patchnotes::patch_body(&saved))
            } else {
                println!("Fetching latest patch notes...");
                let (url, date, text) = match url {
                    Some(url) => {
                        let date = regex::Regex::new(r"\d{2}-\d{2}-\d{4}")
                            .expect("regex")
                            .find(&url)
                            .map(|m| m.as_str().to_string())
                            .unwrap_or_else(|| "unknown".into());
                        let text = patchnotes::fetch_patch_text(&url)?;
                        (url, date, text)
                    }
                    None => patchnotes::fetch_latest_patch()?,
                };
                patchnotes::save_patch(&date, &text, &url)?;
                (url, date, text)
            };
            println!("  Patch: {date}  URL: {url}");
            let mut changes = patchnotes::parse_patch_notes(&text);
            println!("  Parsed {} changes\n", changes.len());
            if apply || dry_run {
                let msgs = patchnotes::apply_patch(&changes, &mut data.heroes, dry_run);
                println!("{} {} changes:", if dry_run { "Would apply" } else { "Applied (in memory)" }, msgs.len());
                msgs.iter().for_each(|m| println!("  {m}"));
            } else {
                let mut report = patchnotes::diff_patch(&mut changes, &data.heroes, Some(&data.items));
                report.patch_date = date;
                report.patch_url = url;
                println!("{}", patchnotes::format_report(&report));
            }
        }
        Command::Completions { .. } | Command::Refresh => unreachable!("handled before data load"),
    }
    Ok(())
}

fn main() -> ExitCode {
    match run(Cli::parse()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
