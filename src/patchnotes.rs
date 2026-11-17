//! Fetch, parse, and apply Deadlock patch notes from the official forum.
//!
//! Workflow:
//!   1. [`fetch_latest_patch_url`] — scrape the changelog index for the newest thread
//!   2. [`fetch_patch_text`] — scrape the thread for the patch note body
//!   3. [`parse_patch_notes`] — parse lines into [`PatchChange`]s
//!   4. [`diff_patch`] — compare changes against current data
//!   5. [`apply_patch`] — mutate loaded data in place

use std::collections::HashSet;
use std::fs;
use std::path::PathBuf;
use std::sync::OnceLock;

use indexmap::IndexMap;
use regex::Regex;
use serde::Serialize;

use crate::api_client::{data_dir, http_get};
use crate::models::{text, HeroStats, Item};

const CHANGELOG_URL: &str = "https://forums.playdeadlock.com/forums/changelog.10/";
const FORUM_BASE: &str = "https://forums.playdeadlock.com";

/// Patch notes may use short names the API doesn't.
fn hero_alias(entity: &str) -> &str {
    match entity {
        "Doorman" => "The Doorman",
        other => other,
    }
}

// ── Data structures ────────────────────────────────────────────────

/// A single parsed change from patch notes.
#[derive(Debug, Clone, Default, Serialize)]
pub struct PatchChange {
    pub raw_line: String,
    /// Hero name; empty for item/general changes.
    pub hero: String,
    /// Item name; empty for hero/general changes.
    pub item: String,
    /// Ability name if ability-specific.
    pub ability: String,
    /// T1=1, T2=2, T3=3, 0=base.
    pub upgrade_tier: i64,
    /// Human-readable stat description.
    pub stat: String,
    pub old_value: String,
    pub new_value: String,
    /// "numeric", "description", "mechanical", "unknown"
    pub change_type: String,
    pub old_numeric: Option<f64>,
    pub new_numeric: Option<f64>,
}

/// Comparison of a patch change against current simulator data.
#[derive(Debug, Clone, Default, Serialize)]
pub struct PatchDiffEntry {
    pub change: PatchChange,
    pub current_value: String,
    /// "already_applied", "needs_update", "not_modeled", "manual_review"
    pub status: String,
    pub notes: String,
}

/// Full report from diffing patch notes against current data.
#[derive(Debug, Clone, Default, Serialize)]
pub struct PatchReport {
    pub patch_date: String,
    pub patch_url: String,
    pub total_changes: usize,
    pub entries: Vec<PatchDiffEntry>,
}

impl PatchReport {
    pub fn already_applied(&self) -> Vec<&PatchDiffEntry> {
        self.entries.iter().filter(|e| e.status == "already_applied").collect()
    }
    pub fn needs_update(&self) -> Vec<&PatchDiffEntry> {
        self.entries.iter().filter(|e| e.status == "needs_update").collect()
    }
    pub fn manual_review(&self) -> Vec<&PatchDiffEntry> {
        self.entries.iter().filter(|e| e.status == "manual_review" || e.status == "not_modeled").collect()
    }
}

// ── Fetching ───────────────────────────────────────────────────────

fn re(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).expect("valid regex"))
}

/// Find the latest patch thread on the changelog index. Returns `(url, date)`.
pub fn fetch_latest_patch_url() -> Result<(String, String), String> {
    let html = http_get(CHANGELOG_URL)?;
    latest_patch_in(&html).ok_or_else(|| "Could not find any patch note threads on the changelog page.".into())
}

/// First (newest) `/threads/MM-DD-YYYY-update.N/` link in a changelog page.
pub fn latest_patch_in(html: &str) -> Option<(String, String)> {
    static LINK: OnceLock<Regex> = OnceLock::new();
    let caps = re(&LINK, r#"(?i)href="(/threads/(\d{2}-\d{2}-\d{4})-update\.\d+/)""#).captures(html)?;
    Some((format!("{FORUM_BASE}{}", &caps[1]), caps[2].to_string()))
}

/// Decode the HTML entities that appear in forum posts.
fn html_unescape(s: &str) -> String {
    static ENTITY: OnceLock<Regex> = OnceLock::new();
    re(&ENTITY, r"&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);")
        .replace_all(s, |caps: &regex::Captures| {
            let e = &caps[1];
            let decoded = match e {
                "amp" => Some('&'),
                "lt" => Some('<'),
                "gt" => Some('>'),
                "quot" => Some('"'),
                "apos" => Some('\''),
                "nbsp" => Some('\u{a0}'),
                _ => e
                    .strip_prefix("#x")
                    .or_else(|| e.strip_prefix("#X"))
                    .and_then(|h| u32::from_str_radix(h, 16).ok())
                    .or_else(|| e.strip_prefix('#').and_then(|d| d.parse().ok()))
                    .and_then(char::from_u32),
            };
            decoded.map(String::from).unwrap_or_else(|| caps[0].to_string())
        })
        .into_owned()
}

/// Fetch a patch thread and extract the patch note lines.
pub fn fetch_patch_text(url: &str) -> Result<String, String> {
    Ok(extract_patch_lines(&http_get(url)?))
}

/// Extract "Entity: change" bullet lines from a forum thread's HTML.
pub fn extract_patch_lines(html: &str) -> String {
    static TAG: OnceLock<Regex> = OnceLock::new();
    static ARTIFACT: OnceLock<Regex> = OnceLock::new();
    static SPACES: OnceLock<Regex> = OnceLock::new();
    static BULLET: OnceLock<Regex> = OnceLock::new();
    let tag = re(&TAG, r"<[^>]+>");
    let bullet_chars: &[char] = &['-', ' ', '\u{2011}'];

    let mut seen: HashSet<String> = HashSet::new();
    let mut lines: Vec<String> = Vec::new();
    for line in html.split('\n') {
        let stripped = line.trim();
        if !(stripped.starts_with("- ") || stripped.starts_with("\u{2011} ")) {
            continue;
        }
        let clean = tag.replace_all(stripped, "");
        // Remove partial HTML artifacts like `..." />`.
        let clean = re(&ARTIFACT, r#"\.\.\."?\s*/?\s*>"#).replace_all(&clean, "");
        let clean = html_unescape(&clean);
        let clean = clean.trim_matches(bullet_chars).trim().to_string();
        // Skip truncated fragments.
        if !clean.is_empty() && !seen.contains(&clean) && clean.contains(':') && !clean.ends_with("...") {
            seen.insert(clean.clone());
            lines.push(clean);
        }
    }

    if lines.is_empty() {
        // Fallback: look for "Hero: change" segments in the flattened text.
        let all_text = html_unescape(&tag.replace_all(html, " "));
        let all_text = re(&SPACES, r"\s+").replace_all(&all_text, " ");
        for segment in re(&BULLET, r"(?:^|\s)-\s").split(&all_text) {
            let segment = segment.trim();
            let lower = segment.to_lowercase();
            if !seen.contains(segment)
                && segment.contains(':')
                && ["increased", "reduced", "changed", "now ", "reworked"].iter().any(|kw| lower.contains(kw))
            {
                seen.insert(segment.to_string());
                lines.push(segment.to_string());
            }
        }
    }
    lines.join("\n")
}

/// Fetch the latest patch. Returns `(url, date, patch_text)`.
pub fn fetch_latest_patch() -> Result<(String, String, String), String> {
    let (url, date) = fetch_latest_patch_url()?;
    let text = fetch_patch_text(&url)?;
    Ok((url, date, text))
}

// ── Parsing ────────────────────────────────────────────────────────

/// Extract a leading numeric magnitude from a patch note value like `+2s`, `35%`, `5m`.
pub fn try_parse_numeric(s: &str) -> Option<f64> {
    static NUMERIC: OnceLock<Regex> = OnceLock::new();
    let s = s.trim().trim_end_matches(['s', 'm', '%']).trim().trim_start_matches('+');
    let caps = re(&NUMERIC, r"^[+\-]?([\d.]+)").captures(s)?;
    caps[1].parse::<f64>().ok()
}

/// Stat keywords that mark where an ability name ends, longest first so that
/// "spirit damage scaling" matches before "damage".
const STAT_KEYWORDS: &[&str] = &[
    "spirit damage scaling",
    "damage spirit scaling",
    "base damage",
    "base health",
    "base regen",
    "base hp",
    "impact damage scaling",
    "damage scaling",
    "spirit scaling",
    "spirit damage",
    "wall stun",
    "stun duration",
    "silence duration",
    "damage",
    "dps",
    "duration",
    "cooldown",
    "radius",
    "health steal per sec",
    "health",
    "slow",
    "speed",
    "range",
    "distance",
    "width",
    "lifesteal",
    "scaling",
    "hp",
    "fire rate",
    "ammo",
    "falloff",
    "bonus damage",
    "heal",
    "shield",
];

/// Split an ability name from the stat description, e.g. "Afterburn DPS" →
/// ability "Afterburn", stat "DPS".
fn extract_ability_from_stat(change: &mut PatchChange) {
    if change.stat.is_empty() {
        return;
    }
    let stat_lower = change.stat.to_lowercase();
    // Hero base stats are not abilities.
    if stat_lower.starts_with("base ") || stat_lower.starts_with("gun ") || stat_lower.starts_with("bullet damage") {
        change.ability.clear();
        return;
    }
    for kw in STAT_KEYWORDS {
        let Some(idx) = stat_lower.find(kw).filter(|&i| i > 0 && change.stat.is_char_boundary(i)) else {
            continue;
        };
        let potential = change.stat[..idx].trim();
        if potential.chars().next().is_some_and(char::is_uppercase) {
            change.ability = potential.to_string();
            change.stat = change.stat[idx..].trim().to_string();
            return;
        }
    }
}

/// Parse raw patch note text (one change per line) into structured changes.
///
/// Lines look like `Hero: Ability stat increased from X to Y`.
pub fn parse_patch_notes(text: &str) -> Vec<PatchChange> {
    static FROM_TO: OnceLock<Regex> = OnceLock::new();
    static TIER: OnceLock<Regex> = OnceLock::new();
    let from_to_re = re(&FROM_TO, r"(?i)(?:increased|reduced|changed|went|rescaled)\s+from\s+(.+?)\s+to\s+(.+?)$");
    let tier_re = re(&TIER, r"(?i)^T([123])\s+");

    let mut changes = Vec::new();
    for raw_line in text.trim().split('\n') {
        let raw_line = raw_line.trim();
        if raw_line.is_empty() {
            continue;
        }
        let mut change = PatchChange { raw_line: raw_line.to_string(), ..Default::default() };

        let Some(colon_idx) = raw_line.find(": ") else {
            change.change_type = "unknown".into();
            changes.push(change);
            continue;
        };
        let entity = raw_line[..colon_idx].trim();
        let description = raw_line[colon_idx + 2..].trim();
        // Entities default to heroes; diff_patch reclassifies item names.
        change.hero = hero_alias(entity).to_string();

        let tier_match = tier_re.captures(description);
        if let Some(t) = &tier_match {
            change.upgrade_tier = t[1].parse().unwrap_or(0);
        }

        let lower = description.to_lowercase();
        if let Some(ft) = from_to_re.captures(description) {
            let whole = ft.get(0).expect("match");
            change.old_value = ft[1].trim().to_string();
            change.new_value = ft[2].trim().to_string();
            change.old_numeric = try_parse_numeric(&change.old_value);
            change.new_numeric = try_parse_numeric(&change.new_value);

            if let Some(t) = &tier_match {
                let tier_span = t.get(0).expect("match");
                change.ability = description[..tier_span.start()].trim().to_string();
                change.stat = description[tier_span.end().min(whole.start())..whole.start()].trim().to_string();
            } else {
                change.stat = description[..whole.start()].trim().to_string();
                extract_ability_from_stat(&mut change);
            }
            change.change_type =
                if change.old_numeric.is_some() && change.new_numeric.is_some() { "numeric" } else { "description" }
                    .into();
        } else {
            change.change_type = if lower.contains("now ") || lower.contains("reworked") {
                "mechanical"
            } else if lower.contains("changed from") {
                "description"
            } else {
                "unknown"
            }
            .into();
            change.stat = description.to_string();
            if change.change_type != "unknown" {
                extract_ability_from_stat(&mut change);
            }
        }
        changes.push(change);
    }
    changes
}

// ── Diffing against current data ──────────────────────────────────

/// Format a number for reports: integral values without a trailing `.0`.
fn fmt_num(v: f64) -> String {
    if v.is_finite() && v == v.trunc() && v.abs() < 1e15 {
        format!("{}", v as i64)
    } else {
        format!("{v}")
    }
}

/// Patch note stat keywords → hero stat fields.
fn hero_stat_field(stat_lower: &str) -> Option<&'static str> {
    Some(match stat_lower {
        "base health regen" | "base regen" => "base_regen",
        "base health" | "base hp" => "base_hp",
        "base bullet damage" | "bullet damage" => "base_bullet_damage",
        "base ammo" => "base_ammo",
        "light melee damage" => "light_melee_damage",
        "heavy melee damage" => "heavy_melee_damage",
        "base move speed" => "base_move_speed",
        "base sprint" => "base_sprint",
        _ => return None,
    })
}

fn hero_field(hero: &HeroStats, field: &str) -> f64 {
    match field {
        "base_regen" => hero.base_regen,
        "base_hp" => hero.base_hp,
        "base_bullet_damage" => hero.base_bullet_damage,
        "base_ammo" => hero.base_ammo as f64,
        "light_melee_damage" => hero.light_melee_damage,
        "heavy_melee_damage" => hero.heavy_melee_damage,
        "base_move_speed" => hero.base_move_speed,
        "base_sprint" => hero.base_sprint,
        _ => 0.0,
    }
}

fn set_hero_field(hero: &mut HeroStats, field: &str, v: f64) {
    match field {
        "base_regen" => hero.base_regen = v,
        "base_hp" => hero.base_hp = v,
        "base_bullet_damage" => hero.base_bullet_damage = v,
        "base_ammo" => hero.base_ammo = v as i64,
        "light_melee_damage" => hero.light_melee_damage = v,
        "heavy_melee_damage" => hero.heavy_melee_damage = v,
        "base_move_speed" => hero.base_move_speed = v,
        "base_sprint" => hero.base_sprint = v,
        _ => {}
    }
}

/// A current value found for a change: numeric when comparable, otherwise text.
enum Current {
    Num(f64),
    Text(String),
}

impl Current {
    fn display(&self) -> String {
        match self {
            Current::Num(v) => fmt_num(*v),
            Current::Text(s) => s.clone(),
        }
    }
    fn as_number(&self) -> Option<f64> {
        match self {
            Current::Num(v) => Some(*v),
            Current::Text(s) => s.trim().parse().ok(),
        }
    }
}

/// Look up the current value of a stat for diffing.
fn find_hero_current_value(hero: &HeroStats, change: &PatchChange) -> Option<Current> {
    let stat_lower = change.stat.to_lowercase().trim().to_string();

    if change.ability.is_empty() {
        if let Some(field) = hero_stat_field(&stat_lower) {
            return Some(Current::Num(hero_field(hero, field)));
        }
        if stat_lower.contains("falloff") {
            return Some(Current::Text(format!(
                "{}->{}",
                fmt_num(hero.falloff_range_min),
                fmt_num(hero.falloff_range_max)
            )));
        }
        // "Bullet damage rescaled from X+Y to X+Y" — base + per-boon gain.
        if stat_lower.contains("rescaled") || (stat_lower.contains("bullet") && stat_lower.contains("damage")) {
            return Some(Current::Text(format!("{}+{}", fmt_num(hero.base_bullet_damage), fmt_num(hero.damage_gain))));
        }
        return None;
    }

    let ab = hero.abilities.iter().find(|ab| ab.name.to_lowercase() == change.ability.to_lowercase())?;
    if change.upgrade_tier > 0 {
        return ab
            .upgrades
            .iter()
            .find(|u| u.tier == change.upgrade_tier)
            .map(|u| Current::Text(u.description.clone()));
    }
    // "damage scaling" contains "damage" but refers to spirit scaling, so check it first.
    if stat_lower.contains("scaling") {
        return Some(Current::Num(ab.spirit_scaling));
    }
    if stat_lower.contains("damage") || stat_lower.contains("dps") {
        return Some(Current::Num(ab.base_damage));
    }
    if stat_lower.contains("cooldown") {
        return Some(Current::Num(ab.cooldown));
    }
    if stat_lower.contains("duration") {
        return Some(Current::Num(ab.duration));
    }
    // The first raw property whose key matches decides the answer, even if it has no value.
    let prop_current = |matches: &dyn Fn(&str) -> bool| -> Option<Option<Current>> {
        ab.properties.iter().find(|(key, prop)| prop.is_object() && matches(&key.to_lowercase())).map(|(_, prop)| {
            prop.get("value").filter(|v| !v.is_null()).map(|v| match v.as_f64() {
                Some(n) => Current::Num(n),
                None => Current::Text(text(v)),
            })
        })
    };
    const SIZE_WORDS: [&str; 3] = ["radius", "range", "distance"];
    if SIZE_WORDS.iter().any(|kw| stat_lower.contains(kw)) {
        if let Some(found) = prop_current(&|key| SIZE_WORDS.iter().any(|kw| key.contains(kw))) {
            return found;
        }
    }
    let needle = stat_lower.replace(' ', "");
    prop_current(&|key| key.contains(&needle)).flatten()
}

/// Compare parsed patch changes against currently loaded data.
///
/// Changes whose entity is an item name are reclassified from hero to item.
pub fn diff_patch(
    changes: &mut [PatchChange],
    heroes: &IndexMap<String, HeroStats>,
    items: Option<&IndexMap<String, Item>>,
) -> PatchReport {
    let mut report = PatchReport { total_changes: changes.len(), ..Default::default() };

    for change in changes.iter_mut() {
        if items.is_some_and(|it| it.contains_key(&change.hero)) {
            change.item = std::mem::take(&mut change.hero);
        }
        let mut entry = PatchDiffEntry::default();

        match change.change_type.as_str() {
            "mechanical" => {
                entry.status = "manual_review".into();
                entry.notes = "Mechanical change requires manual implementation".into();
            }
            "unknown" => {
                entry.status = "manual_review".into();
                entry.notes = "Could not parse this change".into();
            }
            _ => {
                if let Some(hero) = heroes.get(&change.hero).filter(|_| !change.hero.is_empty()) {
                    match find_hero_current_value(hero, change) {
                        Some(current) => {
                            entry.current_value = current.display();
                            match (change.new_numeric, current.as_number()) {
                                (Some(new), Some(cur)) if (cur - new).abs() < 0.01 => {
                                    entry.status = "already_applied".into();
                                }
                                (Some(_), Some(_)) => {
                                    entry.status = "needs_update".into();
                                    entry.notes =
                                        format!("Current={}, Patch wants={}", entry.current_value, change.new_value);
                                }
                                (Some(_), None) => entry.status = "manual_review".into(),
                                (None, _) => {
                                    entry.status = "manual_review".into();
                                    entry.notes = "Non-numeric change".into();
                                }
                            }
                        }
                        None => {
                            entry.status = "not_modeled".into();
                            entry.notes = "Stat not tracked in simulator".into();
                        }
                    }
                } else if !change.hero.is_empty() {
                    entry.status = "manual_review".into();
                    entry.notes = format!("Hero '{}' not found in loaded data", change.hero);
                } else if !change.item.is_empty() {
                    entry.status = "not_modeled".into();
                    entry.notes = "Item changes not yet auto-applied".into();
                } else {
                    entry.status = "manual_review".into();
                }
            }
        }
        entry.change = change.clone();
        report.entries.push(entry);
    }
    report
}

// ── Applying changes ───────────────────────────────────────────────

/// Apply parsed numeric patch changes to loaded hero data in place.
///
/// Only changes with a clear mapping are applied. Returns a log line per change.
/// With `dry_run`, reports what would be applied without mutating.
pub fn apply_patch(changes: &[PatchChange], heroes: &mut IndexMap<String, HeroStats>, dry_run: bool) -> Vec<String> {
    let mut applied = Vec::new();

    for change in changes {
        let Some(new) = change.new_numeric.filter(|_| change.change_type == "numeric") else { continue };
        let Some(hero) = heroes.get_mut(&change.hero).filter(|_| !change.hero.is_empty()) else { continue };
        let stat_lower = change.stat.to_lowercase().trim().to_string();

        if change.ability.is_empty() {
            // Hero base stat changes.
            if let Some(field) = hero_stat_field(&stat_lower) {
                applied.push(format!(
                    "{}: {field} {} -> {}",
                    change.hero,
                    fmt_num(hero_field(hero, field)),
                    fmt_num(new)
                ));
                if !dry_run {
                    set_hero_field(hero, field, new);
                }
            } else if stat_lower.contains("falloff") && change.new_value.contains("->") {
                let parts: Vec<&str> = change.new_value.split("->").collect();
                if let [min, max] = parts[..] {
                    if let (Ok(new_min), Ok(new_max)) = (min.trim().parse::<f64>(), max.trim().parse::<f64>()) {
                        applied.push(format!(
                            "{}: falloff {}->{} -> {}->{}",
                            change.hero,
                            fmt_num(hero.falloff_range_min),
                            fmt_num(hero.falloff_range_max),
                            fmt_num(new_min),
                            fmt_num(new_max)
                        ));
                        if !dry_run {
                            hero.falloff_range_min = new_min;
                            hero.falloff_range_max = new_max;
                        }
                    }
                }
            }
            continue;
        }

        // Ability stat changes.
        let ability_lower = change.ability.to_lowercase();
        let Some(ab) = hero.abilities.iter_mut().find(|ab| ab.name.to_lowercase() == ability_lower) else {
            continue;
        };
        if change.upgrade_tier > 0 {
            applied.push(format!(
                "{}: {} T{} {} -> {} (upgrade, logged only)",
                change.hero, ab.name, change.upgrade_tier, change.stat, change.new_value
            ));
            continue;
        }
        // Scaling first: "damage scaling" refers to spirit scaling.
        let target: Option<(&str, &mut f64)> = if stat_lower.contains("scaling") {
            Some(("spirit_scaling", &mut ab.spirit_scaling))
        } else if stat_lower.contains("damage") || stat_lower.contains("dps") {
            Some(("base_damage", &mut ab.base_damage))
        } else if stat_lower.contains("cooldown") {
            Some(("cooldown", &mut ab.cooldown))
        } else if stat_lower.contains("duration") {
            Some(("duration", &mut ab.duration))
        } else {
            None
        };
        match target {
            Some((field, slot)) => {
                applied.push(format!("{}: {} {field} {} -> {}", change.hero, ab.name, fmt_num(*slot), fmt_num(new)));
                if !dry_run {
                    *slot = new;
                }
            }
            None => applied
                .push(format!("{}: {} {} -> {} (unmapped stat)", change.hero, ab.name, change.stat, change.new_value)),
        }
    }
    applied
}

// ── Saving / loading patches ──────────────────────────────────────

fn patch_dir() -> PathBuf {
    data_dir().join("patches")
}

/// Save raw patch text to `data/patches/` for reference.
pub fn save_patch(date_str: &str, text: &str, url: &str) -> Result<PathBuf, String> {
    let dir = patch_dir();
    fs::create_dir_all(&dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    let path = dir.join(format!("{date_str}.txt"));
    fs::write(&path, format!("# Source: {url}\n\n{text}"))
        .map_err(|e| format!("cannot write {}: {e}", path.display()))?;
    Ok(path)
}

/// Load a previously saved patch by date string.
pub fn load_saved_patch(date_str: &str) -> Option<String> {
    // Dates are file stems; refuse anything that could escape the patch directory.
    if date_str.is_empty() || !date_str.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return None;
    }
    fs::read_to_string(patch_dir().join(format!("{date_str}.txt"))).ok()
}

/// Saved patch text without the `# Source:` header lines.
pub fn patch_body(saved: &str) -> String {
    saved.lines().filter(|l| !l.starts_with('#')).collect::<Vec<_>>().join("\n")
}

/// Date strings of all saved patches, sorted.
pub fn list_saved_patches() -> Vec<String> {
    let mut out: Vec<String> = fs::read_dir(patch_dir())
        .map(|rd| {
            rd.filter_map(|e| e.ok())
                .map(|e| e.path())
                .filter(|p| p.extension().is_some_and(|x| x == "txt"))
                .filter_map(|p| p.file_stem().map(|s| s.to_string_lossy().into_owned()))
                .collect()
        })
        .unwrap_or_default();
    out.sort();
    out
}

// ── Pretty printing ───────────────────────────────────────────────

/// Format a [`PatchReport`] as human-readable text.
pub fn format_report(report: &PatchReport) -> String {
    let mut lines = vec![
        format!("Patch: {}", report.patch_date),
        format!("URL: {}", report.patch_url),
        format!("Total changes: {}", report.total_changes),
        String::new(),
    ];

    let applied = report.already_applied();
    if !applied.is_empty() {
        lines.push(format!("=== ALREADY APPLIED ({}) ===", applied.len()));
        for e in applied {
            let c = &e.change;
            let who = if c.hero.is_empty() { &c.item } else { &c.hero };
            lines.push(format!("  [OK] {who}: {} {} = {}", c.ability, c.stat, e.current_value));
        }
        lines.push(String::new());
    }

    let needs = report.needs_update();
    if !needs.is_empty() {
        lines.push(format!("=== NEEDS UPDATE ({}) ===", needs.len()));
        for e in needs {
            lines.push(format!("  [!!] {}", e.change.raw_line));
            lines.push(format!("       {}", e.notes));
        }
        lines.push(String::new());
    }

    let manual = report.manual_review();
    if !manual.is_empty() {
        lines.push(format!("=== MANUAL REVIEW ({}) ===", manual.len()));
        for e in manual {
            lines.push(format!("  [??] {}", e.change.raw_line));
            if !e.notes.is_empty() {
                lines.push(format!("       {}", e.notes));
            }
        }
        lines.push(String::new());
    }
    lines.join("\n")
}
