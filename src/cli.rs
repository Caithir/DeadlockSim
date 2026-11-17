//! Text UI: display functions and the interactive menu.
//!
//! Pure presentation — every number comes from the engine or service layer.

use std::io::{self, BufRead, Write};

use serde_json::Value;

use crate::data::GameData;
use crate::engine::analysis::{summarize, BuildContext};
use crate::engine::builds::{self, EvalOptions};
use crate::engine::comparison;
use crate::engine::damage::{self, calculate_bullet, calculate_spirit, dps_with_accuracy};
use crate::engine::heroes;
use crate::models::{AbilityConfig, Build, CombatConfig, HeroStats, Item};
use crate::presentation::{commas, pct, StatSheet};

// ── Formatting helpers ───────────────────────────────────────────

fn divider(width: usize) -> String {
    "-".repeat(width)
}

pub fn header(title: &str) -> String {
    let bar = "=".repeat(60);
    format!("\n{bar}\n  {title}\n{bar}")
}

/// Format a number with `decimals` places, showing `-` for zero/inf/nan.
fn val(v: f64, decimals: usize) -> String {
    if !v.is_finite() || v == 0.0 {
        "-".into()
    } else {
        format!("{v:.decimals$}")
    }
}

fn secs(v: f64) -> String {
    if v.is_finite() && v > 0.0 {
        format!("{v:.2}s")
    } else {
        "-".into()
    }
}

fn pct1(v: f64) -> String {
    if !v.is_finite() || v == 0.0 {
        "-".into()
    } else {
        format!("{:.1}%", v * 100.0)
    }
}

// ── Display functions ────────────────────────────────────────────

pub fn display_hero_stats(hero: &HeroStats) {
    println!("{}", header(&format!("{} - Base Stats", hero.name)));
    if hero.hero_labs {
        println!("  [Hero Labs - stats may be incomplete]");
    }
    if hero.base_bullet_damage > 0.0 || hero.base_fire_rate > 0.0 {
        println!("  Bullet Damage:   {:.2} x{} pellets", hero.base_bullet_damage, hero.pellets);
        println!("  Fire Rate:       {} shots/sec", val(hero.base_fire_rate, 2));
        println!("  Base DPS:        {}", val(hero.base_dps, 2));
        println!("  Magazine:        {}", val(hero.base_ammo as f64, 0));
        println!("  DPM:             {}", val(hero.base_dpm, 2));
        println!("  Reload:          {}", secs(hero.reload_duration));
        println!("  Falloff:         {:.0}m - {:.0}m", hero.falloff_range_min, hero.falloff_range_max);
        println!("  Headshot Mult:   {:.2}x", hero.crit_bonus_start);
    } else {
        println!("  Gun Stats:       - (no data)");
    }
    println!("  HP:              {}", val(hero.base_hp, 0));
    println!("  Regen:           {:.1}/s", hero.base_regen);
    println!("  Move Speed:      {}", val(hero.base_move_speed, 2));
    println!("  Sprint Speed:    {:.1}", hero.base_sprint);
    println!("  Stamina:         {}", val(hero.base_stamina as f64, 0));
    println!("  Light / Heavy Melee: {} / {}", val(hero.light_melee_damage, 0), val(hero.heavy_melee_damage, 0));
    println!("{}", divider(60));
    println!("  Per-Boon Scaling:");
    println!(
        "    Damage Gain:   {}/boon",
        if hero.damage_gain != 0.0 { format!("{:+.2}", hero.damage_gain) } else { "-".into() }
    );
    println!(
        "    HP Gain:       {}/boon",
        if hero.hp_gain != 0.0 { format!("{:+.0}", hero.hp_gain) } else { "-".into() }
    );
    println!(
        "    Spirit Gain:   {}/boon",
        if hero.spirit_gain != 0.0 { format!("{:+.1}", hero.spirit_gain) } else { "-".into() }
    );
    if !hero.abilities.is_empty() {
        println!("{}", divider(60));
        println!("  Abilities:");
        for a in hero.abilities.iter().filter(|a| !a.name.is_empty()) {
            let mut parts = Vec::new();
            if a.base_damage != 0.0 {
                parts.push(format!("dmg {:.0}", a.base_damage));
            }
            if a.spirit_scaling != 0.0 {
                parts.push(format!("spirit x{:.2}", a.spirit_scaling));
            }
            if a.cooldown != 0.0 {
                parts.push(format!("cd {:.1}s", a.cooldown));
            }
            if a.duration != 0.0 {
                parts.push(format!("dur {:.1}s", a.duration));
            }
            println!("    {:<24} {}", a.name, parts.join(" | "));
        }
    }
}

pub fn display_bullet_calc(hero: &HeroStats, config: &CombatConfig) {
    let r = calculate_bullet(hero, config);
    println!("{}", header(&format!("{} - Bullet Damage (Boon {})", hero.name, config.boons)));
    if r.bullets_per_second == 0.0 && r.damage_per_bullet == 0.0 {
        println!("  No gun data available for {}.", hero.name);
        return;
    }
    println!("  Damage/Bullet:   {}", val(r.damage_per_bullet, 2));
    println!("  Bullets/Sec:     {}", val(r.bullets_per_second, 2));
    println!("  Burst DPS:       {}", val(r.final_dps, 2));
    println!("  Sustained DPS:   {}", val(r.sustained_dps, 2));
    println!("  Shred:           {:.1}%", r.total_shred * 100.0);
    println!("  Enemy Resist:    {:.1}% -> {:.1}%", config.enemy_bullet_resist * 100.0, r.final_resist * 100.0);
    println!("{}", divider(60));
    println!("  Magazine:        {} rounds", val(r.magazine_size as f64, 0));
    println!("  Damage/Mag:      {}", val(r.damage_per_magazine, 2));
    println!("  Magdump Time:    {}", secs(r.magdump_time));
    println!("  Reload Time:     {}", secs(r.reload_time));
    if config.accuracy < 1.0 || config.headshot_rate > 0.0 {
        println!(
            "  Realistic DPS:   {} ({} acc, {} HS)",
            val(dps_with_accuracy(hero, config), 2),
            pct(config.accuracy),
            pct(config.headshot_rate)
        );
    }
}

pub fn display_scaling(hero: &HeroStats, max_boons: i64) {
    let max_boons = max_boons.max(1);
    let growth = heroes::growth_percentage(hero, max_boons);
    println!("{}", header(&format!("{} - Scaling (0 to {max_boons} Boons)", hero.name)));
    let has_gun = hero.base_bullet_damage > 0.0 || hero.base_fire_rate > 0.0;
    let has_hp = hero.base_hp > 0.0;
    if !has_gun && !has_hp {
        println!("  No scaling data available for {}.", hero.name);
        return;
    }
    println!("  {:>4}  {:>10}  {:>10}  {:>8}  {:>7}", "Boon", "Bullet Dmg", "DPS", "HP", "Spirit");
    println!("  {}", divider(47));
    let step = (max_boons / 10).max(1);
    for snap in heroes::scaling_curve(hero, max_boons) {
        if snap.boon_level % step == 0 || snap.boon_level == max_boons {
            let dmg = if has_gun { format!("{:10.2}", snap.bullet_damage) } else { format!("{:>10}", "-") };
            let dps = if has_gun && hero.base_fire_rate > 0.0 {
                format!("{:10.2}", snap.dps)
            } else {
                format!("{:>10}", "-")
            };
            let hp = if has_hp { format!("{:8.0}", snap.hp) } else { format!("{:>8}", "-") };
            println!("  {:4}  {dmg}  {dps}  {hp}  {:7.1}", snap.boon_level, snap.spirit);
        }
    }
    println!("{}", divider(60));
    println!("  Growth (0 -> {max_boons} boons):");
    println!("    DPS:   {}", pct1(growth.dps_growth));
    println!("    HP:    {}", pct1(growth.hp_growth));
    println!("    Total: {}", pct1(growth.aggregate_growth));
}

pub fn display_ttk(attacker: &HeroStats, defender: &HeroStats, config: &CombatConfig) {
    let r = heroes::ttk(attacker, defender, config);
    println!("{}", header(&format!("TTK: {} vs {}", attacker.name, defender.name)));
    if r.effective_dps == 0.0 {
        println!("  {} has no gun DPS data - cannot calculate TTK.", attacker.name);
        return;
    }
    if r.target_hp == 0.0 {
        println!("  {} has no HP data - cannot calculate TTK.", defender.name);
        return;
    }
    println!("  Attacker ({}):", attacker.name);
    println!("    Boons:         {}", config.boons);
    println!("    Effective DPS: {}", val(r.effective_dps, 2));
    println!("    Realistic DPS: {}", val(r.realistic_dps, 2));
    println!("    Dmg/Magazine:  {}", val(r.damage_per_magazine, 2));
    println!("  Defender ({}):", defender.name);
    println!("    Target HP:     {:.0}", r.target_hp);
    println!("    Bullet Resist: {}", pct(config.enemy_bullet_resist));
    println!("{}", divider(60));
    println!("  Ideal TTK:        {}", secs(r.ttk_seconds));
    println!("  Realistic TTK:    {}", secs(r.realistic_ttk));
    println!("  Can One-Mag:      {}", if r.can_one_mag { "Yes" } else { "No" });
    println!("  Magazines Needed: {}", val(r.magazines_needed as f64, 0));
}

pub fn display_comparison(a: &HeroStats, b: &HeroStats, boon_level: i64) {
    let c = comparison::compare_two(a, b, boon_level);
    let ratio = |v: f64| if v == 0.0 || !v.is_finite() { "-".to_string() } else { format!("{v:.2}") };
    println!("{}", header(&format!("Comparison: {} vs {} (Boon {boon_level})", a.name, b.name)));
    println!("  {:16}   {:>14}  {:>14}  {:>8}", "", a.name, b.name, "Ratio");
    println!("  {}", divider(56));
    println!("  {:16}   {:>14}  {:>14}  {:>8}", "DPS", val(c.hero_a_dps, 2), val(c.hero_b_dps, 2), ratio(c.dps_ratio));
    println!("  {:16}   {:>14}  {:>14}  {:>8}", "HP", val(c.hero_a_hp, 0), val(c.hero_b_hp, 0), ratio(c.hp_ratio));
    println!("  {:16}   {:>14}  {:>14}  {:>8}", "DPM", val(c.hero_a_dpm, 2), val(c.hero_b_dpm, 2), ratio(c.dpm_ratio));
}

pub fn display_rankings(data: &GameData, stat: &str, boon_level: i64, top_n: usize) {
    let rankings = comparison::rank_heroes(&data.heroes, stat, boon_level, false);
    println!("{}", header(&format!("Hero Rankings - {} (Boon {boon_level})", stat.to_uppercase())));
    println!("  {:>4}  {:<16}  {:>12}", "Rank", "Hero", "Value");
    println!("  {}", divider(36));
    for e in rankings.iter().take(top_n) {
        let v = if stat.contains("growth") { pct1(e.value) } else { val(e.value, 2) };
        println!("  {:4}  {:<16}  {:>12}", e.rank, e.hero_name, v);
    }
}

fn print_items(items: &[Item]) {
    for item in items {
        println!("    - {} ({} T{}, {})", item.name, item.category, item.tier, commas(item.cost));
    }
}

/// Print the stat sheet as aligned text.
pub fn display_sheet(sheet: &StatSheet) {
    let tiles: Vec<String> = sheet.tiles.iter().map(|t| format!("{} {}", t.label, t.value)).collect();
    println!("  {}", tiles.join("   |   "));
    for col in &sheet.columns {
        println!("\n  {}", col.title.to_uppercase());
        if col.rows.is_empty() {
            println!("    {}", col.empty_note);
        }
        for row in &col.rows {
            let extra = [row.bonus.as_str(), row.per_k.as_str()]
                .iter()
                .filter(|s| !s.is_empty())
                .copied()
                .collect::<Vec<_>>()
                .join("  ");
            println!("    {:<20} {:>12}  {extra}", row.label, row.value);
        }
    }
    println!();
    for row in &sheet.footer {
        println!("  {:<22} {:>12}  {}", row.label, row.value, row.per_k);
    }
}

/// Print a full build evaluation from the service layer's JSON.
pub fn display_build(ctx: &BuildContext, view: &Value) {
    let s = summarize(ctx);
    println!(
        "{}",
        header(&format!("Build: {} ({})", ctx.hero.name, view["summary"]["build_type"].as_str().unwrap_or("")))
    );
    println!(
        "  {} souls ({} in items) | {} boons | {} ability points",
        commas(s.total_souls),
        commas(s.item_cost),
        s.boons,
        view["ap"]["total"]
    );
    println!("  Items ({}):", ctx.items.len());
    if ctx.items.is_empty() {
        println!("    (none)");
    }
    print_items(&ctx.items);
    println!();
    display_sheet(&crate::presentation::stat_sheet(ctx, &s));
    if let Some(code) = view["share_code"].as_str() {
        println!("\n  Share code: {code}");
    }
    for w in view["warnings"].as_array().into_iter().flatten() {
        println!("  Warning: {}", w.as_str().unwrap_or(""));
    }
}

// ── Prompts ─────────────────────────────────────────────────────

/// Line-oriented prompt reader. `None` means input ended (EOF).
struct Prompt<R: BufRead> {
    input: R,
}

impl<R: BufRead> Prompt<R> {
    fn line(&mut self, prompt: &str) -> Option<String> {
        print!("{prompt}");
        io::stdout().flush().ok();
        let mut buf = String::new();
        match self.input.read_line(&mut buf) {
            Ok(0) | Err(_) => None,
            Ok(_) => Some(buf.trim().to_string()),
        }
    }

    fn choice<'a>(&mut self, prompt: &str, options: &[&'a str]) -> Option<&'a str> {
        for (i, opt) in options.iter().enumerate() {
            println!("  {}. {opt}", i + 1);
        }
        loop {
            let raw = self.line(&format!("\n{prompt} [1-{}]: ", options.len()))?;
            if let Some(opt) = raw.parse::<usize>().ok().and_then(|i| options.get(i.wrapping_sub(1))) {
                return Some(opt);
            }
            println!("  Invalid choice, try again.");
        }
    }

    fn int(&mut self, prompt: &str, default: i64) -> Option<i64> {
        Some(self.line(&format!("{prompt} [{default}]: "))?.parse().unwrap_or(default))
    }

    fn float(&mut self, prompt: &str, default: f64) -> Option<f64> {
        Some(self.line(&format!("{prompt} [{default}]: "))?.parse().unwrap_or(default))
    }

    /// Percentage prompt returning a fraction.
    fn percent(&mut self, prompt: &str, default: f64) -> Option<f64> {
        Some(self.float(prompt, default)? / 100.0)
    }

    fn hero<'a>(&mut self, data: &'a GameData, prompt: &str) -> Option<&'a HeroStats> {
        let names = data.hero_names();
        println!("\n{prompt}:");
        for (i, name) in names.iter().enumerate() {
            println!("  {:2}. {name}", i + 1);
        }
        loop {
            let raw = self.line("\n  Enter number or name: ")?;
            if let Some(name) = raw.parse::<usize>().ok().and_then(|i| names.get(i.wrapping_sub(1))) {
                return data.heroes.get(name);
            }
            if let Some(h) = data.resolve_hero(&raw) {
                return Some(h);
            }
            println!("  Not found, try again.{}", crate::data::suggest(&data.heroes, &raw));
        }
    }

    /// Interactive item picker: add items one at a time until "done".
    fn items(&mut self, data: &GameData) -> Option<Vec<Item>> {
        const CATEGORIES: [&str; 3] = ["weapon", "vitality", "spirit"];
        let mut selected: Vec<Item> = Vec::new();
        println!("\nAdd items to build (enter 'done' when finished)");
        loop {
            println!(
                "\n  Current build ({} items, {} souls):",
                selected.len(),
                commas(selected.iter().map(|i| i.cost).sum())
            );
            if selected.is_empty() {
                println!("    (empty)");
            }
            for (i, item) in selected.iter().enumerate() {
                println!("    {}. {} ({} T{}, {})", i + 1, item.name, item.category, item.tier, item.cost);
            }
            println!("\n  Filter by category:");
            for (i, cat) in CATEGORIES.iter().enumerate() {
                let n = data.items.values().filter(|it| it.category == *cat).count();
                println!("    {}. {} ({n} items)", i + 1, capitalize(cat));
            }
            println!("    4. Search by name\n    5. Done");

            let raw = self.line("\n  Choice: ")?.to_lowercase();
            let mut matches: Vec<&Item> = match raw.as_str() {
                "done" | "5" | "d" => break,
                "4" => {
                    let query = self.line("  Search: ")?.to_lowercase();
                    data.items.values().filter(|it| it.name.to_lowercase().contains(&query)).collect()
                }
                "1" | "2" | "3" => {
                    let cat = CATEGORIES[raw.parse::<usize>().unwrap_or(1) - 1];
                    data.items.values().filter(|it| it.category == cat).collect()
                }
                _ => continue,
            };
            if matches.is_empty() {
                println!("  No matches found.");
                continue;
            }
            matches.sort_by(|a, b| (a.tier, a.cost, &a.name).cmp(&(b.tier, b.cost, &b.name)));
            for (i, it) in matches.iter().enumerate() {
                let cond = if it.condition.is_empty() { String::new() } else { format!(" [{}]", it.condition) };
                println!("    {:3}. T{} {:30} ({:>5}){cond}", i + 1, it.tier, it.name, it.cost);
            }
            let pick = self.line("  Select #: ")?;
            if let Some(it) = pick.parse::<usize>().ok().and_then(|i| matches.get(i.wrapping_sub(1))) {
                use crate::engine::components::{add_item, AddOutcome};
                match add_item(&mut selected, it, &data.items) {
                    AddOutcome::Added { consumed } if consumed.is_empty() => println!("  Added: {}", it.name),
                    AddOutcome::Added { consumed } => println!("  Upgraded {} into {}", consumed.join(" + "), it.name),
                    AddOutcome::Duplicate => println!("  {} is already in the build.", it.name),
                    AddOutcome::Full => println!("  All item slots are full."),
                    AddOutcome::Superseded { by } => println!("  {} is already part of {by}.", it.name),
                }
            }
        }
        Some(selected)
    }
}

fn capitalize(s: &str) -> String {
    let mut c = s.chars();
    c.next().map(|f| f.to_uppercase().collect::<String>() + c.as_str()).unwrap_or_default()
}

// ── Interactive flows ───────────────────────────────────────────

fn build_eval<R: BufRead>(p: &mut Prompt<R>, data: &GameData) -> Option<()> {
    let hero = p.hero(data, "Select hero for build")?;
    let items = p.items(data)?;
    if items.is_empty() {
        println!("  No items selected.");
        return Some(());
    }
    let boons = p.int("  Boons", 0)?;
    let accuracy = p.percent("  Accuracy %", 50.0)?;
    let headshot_rate = p.percent("  Headshot rate %", 15.0)?;
    println!("\n  Evaluate TTK against a defender?");
    let defender =
        if p.line("  (y/n) [n]: ")?.eq_ignore_ascii_case("y") { Some(p.hero(data, "Select defender")?) } else { None };

    let build = Build::new(items);
    let result = builds::evaluate_build(
        hero,
        &build,
        &EvalOptions { boons, accuracy, headshot_rate, defender, ..Default::default() },
    );
    println!("{}", header(&format!("Build Evaluation: {}", hero.name)));
    println!("  Items ({}, {} souls):", build.items.len(), commas(build.total_cost()));
    print_items(&build.items);

    let bs = &result.build_stats;
    println!("\n  Aggregated Stats:");
    let pct_rows = [
        ("Weapon Damage:", bs.weapon_damage_pct, "+"),
        ("Fire Rate:", bs.fire_rate_pct, "+"),
        ("Ammo (%):", bs.ammo_pct, "+"),
        ("Bullet Resist:", bs.bullet_resist_pct, "+"),
        ("Spirit Resist:", bs.spirit_resist_pct, "+"),
        ("Bullet Shred:", bs.bullet_resist_shred, ""),
        ("Bullet Lifesteal:", bs.bullet_lifesteal, ""),
        ("CDR:", bs.cooldown_reduction, ""),
    ];
    for (label, v, sign) in pct_rows {
        if v != 0.0 {
            println!("    {label:<18}{sign}{}", pct(v));
        }
    }
    for (label, v) in [
        ("Ammo (flat):", bs.ammo_flat as f64),
        ("Bonus HP:", bs.bonus_hp),
        ("Spirit Power:", bs.spirit_power),
        ("Bullet Shield:", bs.bullet_shield),
    ] {
        if v != 0.0 {
            println!("    {label:<18}+{v:.0}");
        }
    }
    println!("\n  Effective HP:       {:.0}", result.effective_hp);
    let br = &result.bullet_result;
    println!("\n  Bullet Damage (Boon {boons}):");
    println!("    Damage/Bullet:    {}", val(br.damage_per_bullet, 2));
    println!("    Bullets/Sec:      {}", val(br.bullets_per_second, 2));
    println!("    Burst DPS:        {}", val(br.final_dps, 2));
    println!("    Sustained DPS:    {}", val(br.sustained_dps, 2));
    println!("    Magazine:         {} rounds", val(br.magazine_size as f64, 0));
    println!("    Damage/Mag:       {}", val(br.damage_per_magazine, 2));
    if let (Some(tr), Some(d)) = (&result.ttk_result, defender) {
        println!("\n  TTK vs {}:", d.name);
        println!("    Target HP:        {:.0}", tr.target_hp);
        println!("    Ideal TTK:        {}", secs(tr.ttk_seconds));
        println!("    Realistic TTK:    {}", secs(tr.realistic_ttk));
        println!("    Can One-Mag:      {}", if tr.can_one_mag { "Yes" } else { "No" });
    }
    Some(())
}

fn build_optimizer<R: BufRead>(p: &mut Prompt<R>, data: &GameData) -> Option<()> {
    let hero = p.hero(data, "Select hero to optimize")?;
    let budget = p.int("  Soul budget", 15000)?;
    let boons = p.int("  Boons", 0)?;
    let mode = p.choice("Optimize for", &["Max DPS", "Min TTK"])?;
    let (build, result) = if mode == "Min TTK" {
        let defender = p.hero(data, "Select defender")?;
        let accuracy = p.percent("  Accuracy %", 50.0)?;
        let headshot_rate = p.percent("  Headshot rate %", 15.0)?;
        let build = builds::best_ttk_items(
            &data.items,
            hero,
            defender,
            budget,
            boons,
            accuracy,
            headshot_rate,
            builds::MAX_ITEMS,
            true,
        );
        let r = builds::evaluate_build(
            hero,
            &build,
            &EvalOptions { boons, accuracy, headshot_rate, defender: Some(defender), ..Default::default() },
        );
        (build, r)
    } else {
        let build = builds::best_dps_items(&data.items, hero, budget, boons, builds::MAX_ITEMS, true);
        let r = builds::evaluate_build(hero, &build, &EvalOptions { boons, ..Default::default() });
        (build, r)
    };
    println!("{}", header(&format!("Optimal Build: {} ({mode})", hero.name)));
    println!("  Budget: {} souls | Spent: {} souls", commas(budget), commas(build.total_cost()));
    println!("  Items ({}):", build.items.len());
    print_items(&build.items);
    let br = &result.bullet_result;
    println!("\n  DPS Results (Boon {boons}):");
    println!("    Burst DPS:     {}", val(br.final_dps, 2));
    println!("    Sustained DPS: {}", val(br.sustained_dps, 2));
    println!("    Magazine:      {} rounds", val(br.magazine_size as f64, 0));
    if let Some(tr) = &result.ttk_result {
        println!("\n  TTK Result:");
        println!("    Realistic TTK: {}", secs(tr.realistic_ttk));
        println!("    Can One-Mag:   {}", if tr.can_one_mag { "Yes" } else { "No" });
    }
    Some(())
}

const MAIN_MENU: &[&str] = &[
    "Hero Stats Lookup",
    "Bullet Damage Calculator",
    "Spirit Damage Calculator",
    "Scaling Curve",
    "Time-to-Kill Calculator",
    "Hero Comparison",
    "Hero Rankings",
    "Build Evaluator",
    "Build Optimizer",
    "Quit",
];

fn run_choice<R: BufRead>(p: &mut Prompt<R>, data: &GameData, choice: &str) -> Option<()> {
    match choice {
        "Hero Stats Lookup" => display_hero_stats(p.hero(data, "Select hero")?),
        "Bullet Damage Calculator" => {
            let hero = p.hero(data, "Select attacker")?;
            let boons = p.int("  Boons", 0)?;
            let weapon_damage_bonus = p.percent("  Weapon damage bonus %", 0.0)?;
            let fire_rate_bonus = p.percent("  Fire rate bonus %", 0.0)?;
            let enemy_bullet_resist = p.percent("  Enemy bullet resist %", 0.0)?;
            let shred = p.percent("  Shred %", 0.0)?;
            let accuracy = p.percent("  Accuracy % (100 = perfect)", 100.0)?;
            let config = CombatConfig {
                boons,
                weapon_damage_bonus,
                fire_rate_bonus,
                enemy_bullet_resist,
                shred: if shred > 0.0 { vec![shred] } else { vec![] },
                accuracy,
                ..Default::default()
            };
            display_bullet_calc(hero, &config);
        }
        "Spirit Damage Calculator" => {
            let base_damage = p.float("  Ability base damage", 100.0)?;
            let spirit_multiplier = p.float("  Spirit multiplier", 1.0)?;
            let current_spirit = p.int("  Current spirit", 0)? as f64;
            let enemy_spirit_resist = p.percent("  Enemy spirit resist %", 0.0)?;
            let ability_duration = p.float("  Ability duration (0 = instant)", 0.0)?;
            let r = calculate_spirit(&AbilityConfig {
                base_damage,
                spirit_multiplier,
                current_spirit,
                enemy_spirit_resist,
                ability_duration,
                ..Default::default()
            });
            println!("{}", header("Spirit Damage Result"));
            println!("  Raw Damage:      {:.2}", r.raw_damage);
            println!("  Spirit Contrib:  {:.2}", r.spirit_contribution);
            println!("  Modified Damage: {:.2}", r.modified_damage);
            if ability_duration > 0.0 {
                println!("  DPS:             {:.2}", r.dps);
                println!("  Total DoT:       {:.2}", r.total_dot_damage);
            }
        }
        "Scaling Curve" => {
            let hero = p.hero(data, "Select hero")?;
            display_scaling(hero, p.int("  Max boons to show", 35)?);
        }
        "Time-to-Kill Calculator" => {
            let attacker = p.hero(data, "Select attacker")?;
            let defender = p.hero(data, "Select defender")?;
            let config = CombatConfig {
                boons: p.int("  Boons (both)", 0)?,
                enemy_bullet_resist: p.percent("  Defender bullet resist %", 0.0)?,
                enemy_bonus_hp: p.float("  Defender bonus HP (items)", 0.0)?,
                accuracy: p.percent("  Accuracy %", 50.0)?,
                headshot_rate: p.percent("  Headshot rate %", 15.0)?,
                headshot_multiplier: attacker.crit_bonus_start,
                ..Default::default()
            };
            display_ttk(attacker, defender, &config);
        }
        "Hero Comparison" => {
            let a = p.hero(data, "Select hero A")?;
            let b = p.hero(data, "Select hero B")?;
            display_comparison(a, b, p.int("  Boon level", 0)?);
        }
        "Hero Rankings" => {
            let stat = p.choice("Rank by", comparison::RANK_STATS)?;
            display_rankings(data, stat, p.int("  Boon level", 0)?, 10);
        }
        "Build Evaluator" => build_eval(p, data)?,
        "Build Optimizer" => build_optimizer(p, data)?,
        _ => {}
    }
    Some(())
}

/// Interactive menu loop. Returns when the user quits or input ends.
pub fn run_interactive(data: &GameData) {
    println!("{}", header("DEADLOCK COMBAT SIMULATOR"));
    println!("  Loaded {} heroes, {} items.", data.heroes.len(), data.items.len());
    println!("  Tip: run `deadlock-sim --help` for scriptable commands, or `deadlock-sim serve` for the web UI.\n");
    let stdin = io::stdin();
    let mut p = Prompt { input: stdin.lock() };
    loop {
        println!("\n{}\n  MAIN MENU", divider(40));
        match p.choice("Choose", MAIN_MENU) {
            None | Some("Quit") => {
                println!("\n  Goodbye!");
                return;
            }
            Some(choice) => {
                if run_choice(&mut p, data, choice).is_none() {
                    println!("\n  Goodbye!");
                    return;
                }
            }
        }
    }
}

/// Spirit DPS per ability for text output.
pub fn display_spirit(hero: &HeroStats, ctx: &damage::SpiritContext) {
    println!("{}", header(&format!("{} - Ability Damage ({} spirit)", hero.name, ctx.current_spirit)));
    println!("  {:<26} {:>10} {:>10} {:>10}", "Ability", "Raw", "Final", "DPS");
    println!("  {}", divider(58));
    let mut total = 0.0;
    for (i, ab) in hero.abilities.iter().enumerate() {
        if let Some(r) = damage::ability_dps_in_total(hero, i, ctx, None, &damage::MeleeContext::default()) {
            total += r.dps;
            println!("  {:<26} {:>10.1} {:>10.1} {:>10.1}", ab.name, r.raw_damage, r.modified_damage, r.dps);
        }
    }
    println!("  {}", divider(58));
    println!("  {:<26} {:>32.1}", "Total spirit DPS", total);
}
