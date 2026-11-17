//! Presentation helpers shared by the web UI and the CLI: number formatting,
//! item tooltips, and the per-build stat sheet.

use std::sync::OnceLock;

use regex::Regex;
use serde::Serialize;
use serde_json::Value;

use crate::engine::analysis::{summarize, BuildContext, BuildSummary};
use crate::engine::builds::{build_to_attacker_config, AttackerOptions};
use crate::engine::builds::{stat_breakdown, StatBreakdown};
use crate::engine::damage::dps_with_accuracy;
use crate::models::{num, text, truthy, Build, Item};

// ── Formatting ─────────────────────────────────────────────────────

/// Integer with thousands separators: `12345` → `12,345`.
pub fn commas(n: i64) -> String {
    let digits = n.abs().to_string();
    let mut out = String::new();
    for (i, ch) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(ch);
    }
    if n < 0 {
        format!("-{out}")
    } else {
        out
    }
}

/// Fraction as a whole percentage: `0.35` → `35%`.
pub fn pct(v: f64) -> String {
    format!("{:.0}%", v * 100.0)
}

/// Escape text for inclusion in HTML.
pub fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

/// How a stat value is displayed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Fmt {
    Num,
    Pct,
    Int,
}

impl Fmt {
    /// Signed display of a single contribution.
    fn signed(self, v: f64) -> String {
        let sign = if v > 0.0 { "+" } else { "" };
        match self {
            Fmt::Pct => format!("{sign}{}", pct(v)),
            Fmt::Int => format!("{sign}{}", commas(v as i64)),
            Fmt::Num => format!("{sign}{v:.1}"),
        }
    }
    fn plain(self, v: f64) -> String {
        match self {
            Fmt::Pct => pct(v),
            Fmt::Int => commas(v as i64),
            Fmt::Num => format!("{v:.1}"),
        }
    }
}

// ── Item tooltips ──────────────────────────────────────────────────

/// One property as tooltip text: prefix + value + postfix + label. Empty for hidden values.
pub fn prop_display(prop: &Value) -> String {
    let val = prop.get("value").map(text).unwrap_or_default();
    if matches!(val.as_str(), "0" | "-1" | "-1.0" | "0.0" | "") {
        return String::new();
    }
    let field = |k: &str| prop.get(k).map(text).unwrap_or_default();
    let (label, postfix, mut prefix) = (field("label"), field("postfix"), field("prefix"));
    if prefix == "{s:sign}" {
        prefix = match val.trim_end_matches('m').trim().parse::<f64>() {
            Ok(v) if v < 0.0 => String::new(),
            _ => "+".to_string(),
        };
    }
    let val_str = if postfix == "m" { val.trim_end_matches('m') } else { val.as_str() };
    let postvalue = field("postvalue_label");
    let tail = if !postvalue.is_empty() { postvalue } else { label };
    if tail.is_empty() {
        format!("{prefix}{val_str}{postfix}")
    } else {
        format!("{prefix}{val_str}{postfix} {tail}")
    }
}

/// Tooltip tone for a property, from the API's css class.
fn prop_tone(prop: &Value) -> &'static str {
    match prop.get("css_class").and_then(Value::as_str).unwrap_or("") {
        "bullet_damage" | "fire_rate" | "clipsize" | "reload_speed" | "bullet_armor_down" => "weapon",
        "health" | "combat_barrier" | "healing" | "move_speed" | "movement_speed" | "melee_damage" | "slow"
        | "bullet_armor_up" | "tech_armor_up" => "vitality",
        "tech_power" | "spirit" | "tech_damage" | "tech_armor_down" | "cooldown" | "cast" | "duration"
        | "charge_cooldown" => "spirit",
        _ => "plain",
    }
}

fn is_conditional(prop: &Value) -> bool {
    prop.get("conditional").is_some_and(truthy)
        || prop
            .get("usage_flags")
            .and_then(Value::as_array)
            .is_some_and(|f| f.iter().any(|x| x.as_str() == Some("ConditionallyApplied")))
}

fn strip_svg(s: &str) -> String {
    static SVG: OnceLock<Regex> = OnceLock::new();
    SVG.get_or_init(|| Regex::new(r"(?s)<svg[^>]*>.*?</svg>").expect("valid regex"))
        .replace_all(s, "")
        .trim()
        .to_string()
}

fn prop_line(prop: &Value, important: bool) -> String {
    let txt = prop_display(prop);
    if txt.is_empty() {
        return String::new();
    }
    let cond = is_conditional(prop);
    let tone = if cond && important { "cond" } else { prop_tone(prop) };
    let class = if important { "tt-prop tt-important" } else { "tt-prop" };
    let note = if cond && important { r#"<div class="tt-note">Conditional</div>"# } else { "" };
    format!(r#"<div class="{class} tone-{tone}">{}{note}</div>"#, esc(&txt))
}

/// Rich tooltip HTML for an item, in the style of the in-game tooltip.
///
/// Description strings come from the game API and contain markup, so they are
/// inserted as-is; everything else is escaped.
pub fn item_tooltip_html(item: &Item) -> String {
    let props = &item.raw_properties;
    let mut html = format!(
        r#"<div class="tt cat-{}"><div class="tt-name">{}</div><div class="tt-cost">{} souls · Tier {}</div>"#,
        esc(&item.category),
        esc(&item.name),
        commas(item.cost),
        item.tier
    );

    let names = |attrs: &Value, key: &str| -> Vec<String> {
        attrs
            .get(key)
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default()
    };

    if item.tooltip_sections.is_empty() {
        // No structured sections: list every displayable property.
        for p in props.values().filter(|p| p.is_object()) {
            html += &prop_line(p, is_conditional(p));
        }
    }
    for section in item.tooltip_sections.iter() {
        let sec_type = section.get("section_type").and_then(Value::as_str).unwrap_or("");
        let attrs_list: &[Value] =
            section.get("section_attributes").and_then(Value::as_array).map(|v| v.as_slice()).unwrap_or(&[]);
        for attrs in attrs_list {
            match sec_type {
                "innate" => {
                    for name in names(attrs, "properties").into_iter().chain(names(attrs, "elevated_properties")) {
                        if let Some(p) = props.get(&name) {
                            html += &prop_line(p, false);
                        }
                    }
                }
                "passive" | "active" | "" => {
                    let label = if sec_type == "active" { "Active" } else { "Passive" };
                    html += &format!(r#"<div class="tt-section">{label}</div>"#);
                    let loc = strip_svg(attrs.get("loc_string").and_then(Value::as_str).unwrap_or(""));
                    if !loc.is_empty() {
                        html += &format!(r#"<div class="tt-desc">{loc}</div>"#);
                    }
                    for name in names(attrs, "important_properties") {
                        if let Some(p) = props.get(&name) {
                            html += &prop_line(p, true);
                        }
                    }
                    for name in names(attrs, "properties") {
                        if let Some(p) = props.get(&name) {
                            html += &prop_line(p, false);
                        }
                    }
                }
                _ => {}
            }
        }
    }

    if !item.component_names.is_empty() {
        html += &format!(
            r#"<div class="tt-foot"><span class="tt-foot-label">Built from</span> {}</div>"#,
            esc(&item.component_names.join(", "))
        );
    }
    if !item.upgrades_to.is_empty() {
        html += &format!(
            r#"<div class="tt-foot"><span class="tt-foot-label">Upgrades to</span> {}</div>"#,
            esc(&item.upgrades_to)
        );
    }
    html + "</div>"
}

/// Plain-text numeric value of an ability/item property, for display.
pub fn prop_number(prop: &Value) -> Option<f64> {
    prop.get("value").and_then(num)
}

// ── Stat sheet ─────────────────────────────────────────────────────

/// One contribution to a stat.
#[derive(Debug, Clone, Serialize)]
pub struct Source {
    pub source: String,
    pub value: String,
}

/// A row of the stat sheet.
#[derive(Debug, Clone, Default, Serialize)]
pub struct StatRow {
    pub label: String,
    pub value: String,
    /// Bonus over the hero's base, e.g. `+35`.
    pub bonus: String,
    /// Value gained per 1,000 souls invested, e.g. `4.2/k`.
    pub per_k: String,
    /// Where the value comes from; empty when there is nothing to break down.
    pub breakdown: Vec<Source>,
    /// Total line for the breakdown (shown when there are several sources).
    pub total: String,
}

/// A headline tile.
#[derive(Debug, Clone, Serialize)]
pub struct Tile {
    pub label: String,
    pub value: String,
    pub per_k: String,
    /// weapon / spirit / vitality / regen
    pub tone: &'static str,
}

/// A titled column of rows.
#[derive(Debug, Clone, Serialize)]
pub struct Column {
    pub title: &'static str,
    pub tone: &'static str,
    pub rows: Vec<StatRow>,
    /// Shown instead of rows when the column has nothing to report.
    pub empty_note: &'static str,
}

/// The full calculated-stats panel for a build.
#[derive(Debug, Clone, Serialize)]
pub struct StatSheet {
    pub tiles: Vec<Tile>,
    pub columns: Vec<Column>,
    pub footer: Vec<StatRow>,
}

struct RowBuilder {
    total_souls: i64,
}

impl RowBuilder {
    /// Per-1000-souls text for a delta, or "" when it is negligible.
    fn per_k(&self, delta: f64, fmt: Fmt) -> String {
        if self.total_souls <= 0 || delta.abs() < 0.01 {
            return String::new();
        }
        let v = delta / self.total_souls as f64 * 1000.0;
        match fmt {
            Fmt::Pct if v.abs() >= 0.0005 => format!("{:.1}%/k", v * 100.0),
            Fmt::Pct => String::new(),
            _ if v.abs() >= 0.05 => format!("{v:.1}/k"),
            _ => String::new(),
        }
    }

    fn row(
        &self,
        label: &str,
        value: String,
        bonus: String,
        breakdown: Vec<(String, f64)>,
        fmt: Fmt,
        delta: Option<f64>,
    ) -> StatRow {
        let total: f64 = breakdown.iter().map(|(_, v)| v).sum();
        StatRow {
            label: label.to_string(),
            value,
            bonus,
            per_k: delta.map(|d| self.per_k(d, fmt)).unwrap_or_default(),
            total: if breakdown.len() > 1 { fmt.plain(total) } else { String::new() },
            breakdown: breakdown.into_iter().map(|(source, v)| Source { source, value: fmt.signed(v) }).collect(),
        }
    }
}

fn plus(d: f64) -> String {
    if d > 0.5 {
        format!("+{d:.0}")
    } else {
        String::new()
    }
}

/// Build the stat sheet for a context, comparing against the same hero with no items.
pub fn stat_sheet(ctx: &BuildContext, s: &BuildSummary) -> StatSheet {
    let hero = ctx.hero;
    let boons = s.boons;
    let bs = &s.stats;
    let br = &s.bullet;
    let base = summarize(&BuildContext { boons_override: Some(boons), ..ctx.with_items(Vec::new()) });
    let bbr = &base.bullet;
    let bd: StatBreakdown = stat_breakdown(&Build::new(ctx.items.clone()), ctx.conditionals.as_ref());
    let of = |field: &str| -> Vec<(String, f64)> { bd.get(field).cloned().unwrap_or_default() };
    let rb = RowBuilder { total_souls: s.total_souls };

    let realistic = dps_with_accuracy(
        hero,
        &build_to_attacker_config(
            bs,
            &AttackerOptions {
                boons,
                spirit_gain: hero.spirit_gain,
                accuracy: ctx.accuracy,
                headshot_rate: ctx.headshot_rate,
                headshot_multiplier: hero.crit_bonus_start,
                ..Default::default()
            },
        ),
    );

    let tiles = vec![
        Tile {
            label: "Gun DPS".into(),
            value: format!("{:.1}", s.gun_dps),
            per_k: rb.per_k(s.gun_dps - base.gun_dps, Fmt::Num),
            tone: "weapon",
        },
        Tile {
            label: "Spirit DPS".into(),
            value: format!("{:.1}", s.spirit_dps),
            per_k: rb.per_k(s.spirit_dps - base.spirit_dps, Fmt::Num),
            tone: "spirit",
        },
        Tile {
            label: "EHP".into(),
            value: format!("{:.0}", s.effective_hp),
            per_k: rb.per_k(s.effective_hp - base.effective_hp, Fmt::Num),
            tone: "ehp",
        },
        Tile {
            label: "Regen".into(),
            value: format!("{:.1}/s", s.hp_regen),
            per_k: rb.per_k(bs.hp_regen, Fmt::Num),
            tone: "vitality",
        },
    ];

    // ── Weapon ──
    let mut weapon = Vec::new();
    if br.raw_dps > 0.0 {
        let mut dps_bd = vec![("Hero Base DPS".to_string(), bbr.sustained_dps)];
        if bs.weapon_damage_pct != 0.0 || bs.fire_rate_pct != 0.0 {
            dps_bd.push(("Item Bonus".to_string(), br.sustained_dps - bbr.sustained_dps));
        }
        if dps_bd.len() < 2 {
            dps_bd.clear();
        }
        weapon.push(rb.row(
            "Sustained DPS",
            format!("{:.1}", br.sustained_dps),
            plus(br.sustained_dps - bbr.sustained_dps),
            dps_bd,
            Fmt::Num,
            Some(br.sustained_dps - bbr.sustained_dps),
        ));
        weapon.push(rb.row(
            "Burst DPS",
            format!("{:.1}", br.final_dps),
            plus(br.final_dps - bbr.final_dps),
            vec![],
            Fmt::Num,
            Some(br.final_dps - bbr.final_dps),
        ));
        weapon.push(rb.row(
            "Realistic DPS",
            format!("{realistic:.1}"),
            format!("{} acc · {} HS", pct(ctx.accuracy), pct(ctx.headshot_rate)),
            vec![],
            Fmt::Num,
            None,
        ));
        let mut dmg_bd = vec![("Hero Base".to_string(), bbr.damage_per_bullet)];
        dmg_bd.extend(of("weapon_damage_pct").into_iter().map(|(src, v)| (src, v * bbr.damage_per_bullet)));
        if dmg_bd.len() < 2 {
            dmg_bd.clear();
        }
        weapon.push(rb.row(
            "Bullet Damage",
            format!("{:.1}", br.damage_per_bullet),
            plus(br.damage_per_bullet - bbr.damage_per_bullet),
            dmg_bd,
            Fmt::Num,
            Some(br.damage_per_bullet - bbr.damage_per_bullet),
        ));
        let mut shots = rb.row(
            "Shots/s",
            format!("{:.2}", br.bullets_per_second),
            String::new(),
            of("fire_rate_pct"),
            Fmt::Pct,
            None,
        );
        shots.per_k = rb.per_k(br.bullets_per_second - bbr.bullets_per_second, Fmt::Num);
        shots.total = if shots.breakdown.len() > 1 { pct(bs.fire_rate_pct) } else { String::new() };
        weapon.push(shots);
        let mut ammo_bd = of("ammo_flat");
        ammo_bd.extend(
            of("ammo_pct")
                .into_iter()
                .map(|(src, v)| (format!("{src} (+{})", pct(v)), (hero.base_ammo as f64 * v).ceil())),
        );
        let ammo_bonus = if bs.ammo_flat != 0 {
            format!("+{}", bs.ammo_flat)
        } else if bs.ammo_pct != 0.0 {
            format!("+{}", pct(bs.ammo_pct))
        } else {
            String::new()
        };
        weapon.push(rb.row(
            "Ammo",
            br.magazine_size.to_string(),
            ammo_bonus,
            ammo_bd,
            Fmt::Int,
            Some((br.magazine_size - bbr.magazine_size) as f64),
        ));
        if br.reload_time > 0.0 {
            weapon.push(rb.row("Reload", format!("{:.2}s", br.reload_time), String::new(), vec![], Fmt::Num, None));
        }
        for (label, v, field) in [
            ("Bullet Lifesteal", bs.bullet_lifesteal, "bullet_lifesteal"),
            ("Bullet Shred", bs.bullet_resist_shred, "bullet_resist_shred"),
        ] {
            if v != 0.0 {
                weapon.push(rb.row(label, pct(v), String::new(), of(field), Fmt::Pct, Some(v)));
            }
        }
        if bs.melee_damage_pct != 0.0 {
            weapon.push(rb.row(
                "Melee Damage",
                format!("+{}", pct(bs.melee_damage_pct)),
                String::new(),
                of("melee_damage_pct"),
                Fmt::Pct,
                Some(bs.melee_damage_pct),
            ));
        }
    }

    // ── Vitality ──
    let mut vitality = Vec::new();
    let base_hp = hero.hp_at(boons);
    let boon_hp = hero.hp_gain * boons as f64;
    let mut pool_bd = vec![("Base HP".to_string(), hero.base_hp)];
    if boons != 0 && hero.hp_gain != 0.0 {
        pool_bd.push(("Boon Scaling".to_string(), boon_hp));
    }
    if bs.base_hp_pct != 0.0 {
        pool_bd.push(("Vitality Shop Bonus".to_string(), base_hp * bs.base_hp_pct));
    }
    pool_bd.extend(of("bonus_hp"));
    pool_bd.extend(of("bullet_shield").into_iter().map(|(src, v)| (format!("{src} (Bullet Shield)"), v)));
    pool_bd.extend(of("spirit_shield").into_iter().map(|(src, v)| (format!("{src} (Spirit Shield)"), v)));
    vitality.push(rb.row(
        "Effective HP",
        format!("{:.0}", s.effective_hp),
        plus(s.effective_hp - base.effective_hp),
        vec![],
        Fmt::Num,
        Some(s.effective_hp - base.effective_hp),
    ));
    vitality.push(rb.row(
        "HP + Shields",
        format!("{:.0}", s.hp_pool),
        plus(s.hp_pool - base.hp_pool),
        pool_bd,
        Fmt::Num,
        Some(s.hp_pool - base.hp_pool),
    ));
    let mut basehp_bd = vec![("Hero Base".to_string(), hero.base_hp)];
    if boons != 0 && hero.hp_gain != 0.0 {
        basehp_bd.push(("Boon Scaling".to_string(), boon_hp));
    }
    if basehp_bd.len() < 2 {
        basehp_bd.clear();
    }
    vitality.push(rb.row("Base HP", format!("{base_hp:.0}"), String::new(), basehp_bd, Fmt::Num, None));
    if bs.bonus_hp != 0.0 {
        vitality.push(rb.row(
            "Bonus HP",
            format!("+{:.0}", bs.bonus_hp),
            String::new(),
            of("bonus_hp"),
            Fmt::Num,
            Some(bs.bonus_hp),
        ));
    }
    if bs.bullet_shield != 0.0 || bs.spirit_shield != 0.0 {
        let mut shield_bd: Vec<(String, f64)> =
            of("bullet_shield").into_iter().map(|(src, v)| (format!("{src} (Bullet)"), v)).collect();
        shield_bd.extend(of("spirit_shield").into_iter().map(|(src, v)| (format!("{src} (Spirit)"), v)));
        vitality.push(rb.row(
            "Shields",
            format!("B:{:.0} S:{:.0}", bs.bullet_shield, bs.spirit_shield),
            String::new(),
            shield_bd,
            Fmt::Num,
            Some(bs.bullet_shield + bs.spirit_shield),
        ));
    }
    let mut regen_bd = vec![("Hero Base".to_string(), hero.base_regen)];
    regen_bd.extend(of("hp_regen"));
    if bs.hp_regen == 0.0 {
        regen_bd.clear();
    }
    vitality.push(rb.row(
        "HP Regen",
        format!("+{:.1}/s", s.hp_regen),
        if bs.hp_regen != 0.0 { format!("+{:.1}", bs.hp_regen) } else { String::new() },
        regen_bd,
        Fmt::Num,
        Some(bs.hp_regen),
    ));
    for (label, v, field) in [
        ("Bullet Resist", bs.bullet_resist_pct, "bullet_resist_pct"),
        ("Spirit Resist", bs.spirit_resist_pct, "spirit_resist_pct"),
    ] {
        if v != 0.0 {
            let mut r = rb.row(label, pct(v), String::new(), of(field), Fmt::Pct, Some(v));
            // Resists multiply rather than add, so the total is the aggregate.
            if r.breakdown.len() > 1 {
                r.total = format!("{} (multiplicative)", pct(v));
            }
            vitality.push(r);
        }
    }

    // ── Spirit ──
    let mut spirit = Vec::new();
    let boon_spirit = hero.spirit_gain * boons as f64;
    let mut sp_bd = of("spirit_power");
    if boons != 0 && hero.spirit_gain != 0.0 {
        sp_bd.push(("Boon Scaling".to_string(), boon_spirit));
    }
    if bs.spirit_power_pct != 0.0 {
        sp_bd.push((
            format!("Spirit Power % (+{})", pct(bs.spirit_power_pct)),
            (bs.spirit_power + boon_spirit) * bs.spirit_power_pct,
        ));
    }
    spirit.push(rb.row(
        "Spirit Power",
        s.spirit_power.to_string(),
        if bs.spirit_power != 0.0 { format!("(+{:.0} items)", bs.spirit_power) } else { String::new() },
        sp_bd,
        Fmt::Num,
        Some((s.spirit_power - base.spirit_power) as f64),
    ));
    for (label, v, field, signed) in [
        ("Spirit Power %", bs.spirit_power_pct, "spirit_power_pct", true),
        ("Spirit Amp", bs.spirit_amp_pct, "spirit_amp_pct", true),
        ("Spirit Lifesteal", bs.spirit_lifesteal, "spirit_lifesteal", false),
        ("Cooldown Reduction", bs.cooldown_reduction, "cooldown_reduction", false),
        ("Spirit Shred", bs.spirit_resist_shred, "spirit_resist_shred", false),
    ] {
        if v != 0.0 {
            let value = if signed { format!("+{}", pct(v)) } else { pct(v) };
            spirit.push(rb.row(label, value, String::new(), of(field), Fmt::Pct, Some(v)));
        }
    }
    spirit.push(rb.row(
        "Spirit DPS",
        if s.spirit_dps > 0.0 { format!("{:.1}", s.spirit_dps) } else { "-".into() },
        plus(s.spirit_dps - base.spirit_dps),
        vec![],
        Fmt::Num,
        Some(s.spirit_dps - base.spirit_dps),
    ));

    // ── Footer ──
    let mut combo_bd = Vec::new();
    if s.gun_dps > 0.0 {
        combo_bd.push(("Gun DPS".to_string(), s.gun_dps));
    }
    if s.spirit_dps > 0.0 {
        combo_bd.push(("Spirit DPS".to_string(), s.spirit_dps));
    }
    if combo_bd.len() < 2 {
        combo_bd.clear();
    }
    let footer = vec![
        rb.row(
            "Combined DPS",
            format!("{:.1}", s.combined_dps),
            String::new(),
            combo_bd,
            Fmt::Num,
            Some(s.combined_dps - base.combined_dps),
        ),
        rb.row(
            "Total Cost",
            format!("{} souls", commas(bs.total_cost)),
            String::new(),
            ctx.items.iter().map(|i| (i.name.clone(), i.cost as f64)).collect(),
            Fmt::Int,
            None,
        ),
    ];

    StatSheet {
        tiles,
        columns: vec![
            Column {
                title: "Weapon",
                tone: "weapon",
                empty_note: if weapon.is_empty() { "No gun data" } else { "" },
                rows: weapon,
            },
            Column { title: "Vitality", tone: "vitality", empty_note: "", rows: vitality },
            Column { title: "Spirit", tone: "spirit", empty_note: "", rows: spirit },
        ],
        footer,
    }
}
