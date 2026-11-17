//! Data loading from the API cache.
//!
//! Hero and item data comes exclusively from the Deadlock Assets API
//! (assets.deadlock-api.com), cached locally under `data/api_cache/`.

use indexmap::IndexMap;
use serde::Serialize;
use serde_json::{Map, Value};

use crate::api_client;
use crate::models::{num, str_of, text, truthy, AbilityUpgrade, HeroAbility, HeroStats, Item, ShopTier};

/// A recoverable issue encountered while parsing API data.
#[derive(Debug, Clone, Default, Serialize)]
pub struct ParseWarning {
    pub entity: String,
    pub field: String,
    pub message: String,
}

/// Everything the simulator needs, loaded once and shared read-only.
#[derive(Debug, Clone, Default)]
pub struct GameData {
    pub heroes: IndexMap<String, HeroStats>,
    pub items: IndexMap<String, Item>,
    pub warnings: Vec<ParseWarning>,
}

impl GameData {
    /// Load heroes and items from the on-disk API cache.
    pub fn load() -> Result<GameData, String> {
        let heroes = load_heroes()?;
        let items = load_items()?;
        let warnings = sanity_warnings(&heroes);
        Ok(GameData { heroes, items, warnings })
    }

    pub fn hero_names(&self) -> Vec<String> {
        let mut v: Vec<String> = self.heroes.keys().cloned().collect();
        v.sort();
        v
    }

    pub fn item_names(&self) -> Vec<String> {
        let mut v: Vec<String> = self.items.keys().cloned().collect();
        v.sort();
        v
    }

    /// Case-insensitive hero lookup: exact, then prefix, then substring.
    pub fn resolve_hero(&self, name: &str) -> Option<&HeroStats> {
        resolve(&self.heroes, name)
    }

    /// Case-insensitive item lookup: exact, then prefix, then substring.
    pub fn resolve_item(&self, name: &str) -> Option<&Item> {
        resolve(&self.items, name)
    }

    /// Resolve a list of item names, failing on the first unknown one.
    pub fn resolve_items(&self, names: &[String]) -> Result<Vec<Item>, String> {
        names
            .iter()
            .map(|n| {
                self.resolve_item(n).cloned().ok_or_else(|| format!("Item '{n}' not found.{}", suggest(&self.items, n)))
            })
            .collect()
    }

    pub fn hero_or_err(&self, name: &str) -> Result<&HeroStats, String> {
        self.resolve_hero(name).ok_or_else(|| format!("Hero '{name}' not found.{}", suggest(&self.heroes, name)))
    }
}

fn resolve<'a, T>(map: &'a IndexMap<String, T>, name: &str) -> Option<&'a T> {
    if name.is_empty() {
        return None;
    }
    if let Some(v) = map.get(name) {
        return Some(v);
    }
    let lower = name.to_lowercase();
    map.iter()
        .find(|(k, _)| k.to_lowercase() == lower)
        .or_else(|| map.iter().find(|(k, _)| k.to_lowercase().starts_with(&lower)))
        .or_else(|| map.iter().find(|(k, _)| k.to_lowercase().contains(&lower)))
        .map(|(_, v)| v)
}

/// " Did you mean: A, B?" for the closest names by edit distance, or "".
pub fn suggest<T>(map: &IndexMap<String, T>, name: &str) -> String {
    let lower = name.to_lowercase();
    let mut scored: Vec<(usize, &String)> = map
        .keys()
        .map(|k| (edit_distance(&lower, &k.to_lowercase()), k))
        .filter(|(d, k)| *d <= (k.len().max(lower.len()) / 2).max(2))
        .collect();
    scored.sort();
    let names: Vec<&str> = scored.iter().take(3).map(|(_, k)| k.as_str()).collect();
    if names.is_empty() {
        String::new()
    } else {
        format!(" Did you mean: {}?", names.join(", "))
    }
}

fn edit_distance(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    for i in 1..=a.len() {
        let mut cur = vec![i; b.len() + 1];
        for j in 1..=b.len() {
            let sub = prev[j - 1] + usize::from(a[i - 1] != b[j - 1]);
            cur[j] = sub.min(prev[j] + 1).min(cur[j - 1] + 1);
        }
        prev = cur;
    }
    prev[b.len()]
}

// ── Property name mapping from API to our stat fields ──────────────

fn upgrade_prop_field(key: &str) -> Option<&'static str> {
    Some(match key {
        "BonusWeaponPower" | "BaseAttackDamagePercent" => "weapon_damage_pct",
        "BonusFireRate" => "fire_rate_pct",
        "BonusClipSize" => "ammo_flat",
        "BonusClipSizePercent" => "ammo_pct",
        "BulletResist" | "BonusBulletArmorDamageReduction" => "bullet_resist_pct",
        "TechResist" | "BonusTechArmorDamageReduction" => "spirit_resist_pct",
        "BonusHealth" => "bonus_hp",
        "TechPower" | "SpiritPower" | "BonusSpirit" | "BonusTechPower" => "spirit_power",
        "TechPowerPercent" => "spirit_power_pct",
        "BulletLifestealPercent" | "BonusBulletLifesteal" => "bullet_lifesteal",
        "AbilityLifestealPercentHero" | "AbilityLifestealPercentHeroPassive" | "BonusTechLifesteal" => {
            "spirit_lifesteal"
        }
        "BonusHealthRegen" => "hp_regen",
        "BonusMoveSpeed" => "move_speed",
        "BonusSprintSpeed" => "sprint_speed",
        "BonusBulletShieldHealth" | "CombatBarrier" => "bullet_shield",
        "BonusTechShieldHealth" => "spirit_shield",
        "HeadShotBonusDamage" => "headshot_bonus",
        "BulletArmorReduction" | "BonusBulletArmorReduction" | "BulletResistReduction" => "bullet_resist_shred",
        "BonusTechArmorReduction" | "MagicResistReduction" | "TechArmorDamageReduction" => "spirit_resist_shred",
        "CooldownReduction" | "AbilityCooldownReduction" | "TechCooldownReduction" => "cooldown_reduction",
        "ItemCooldownReduction" => "item_cooldown_reduction",
        "BonusSpiritAmp" => "spirit_amp_pct",
        "BonusMeleeDamagePercent" => "melee_damage_pct",
        "BonusHeavyMeleeDamage" => "heavy_melee_damage_pct",
        _ => return None,
    })
}

/// Fields that are whole-number percentages in the API but stored as fractions.
const PCT_FIELDS: &[&str] = &[
    "weapon_damage_pct",
    "fire_rate_pct",
    "ammo_pct",
    "bullet_resist_pct",
    "spirit_resist_pct",
    "bullet_lifesteal",
    "spirit_lifesteal",
    "cooldown_reduction",
    "item_cooldown_reduction",
    "spirit_amp_pct",
    "bullet_resist_shred",
    "spirit_resist_shred",
    "spirit_power_pct",
    "melee_damage_pct",
    "heavy_melee_damage_pct",
];

/// API properties whose values must be negated (shred is stored negative).
const NEGATE_PROPS: &[&str] = &[
    "BulletArmorReduction",
    "BonusBulletArmorReduction",
    "BulletResistReduction",
    "BonusTechArmorReduction",
    "MagicResistReduction",
    "TechArmorDamageReduction",
];

// ── Shop tier bonuses ──────────────────────────────────────────────

/// (cost, weapon_bonus %, vitality_bonus %, spirit_bonus flat) per total category spend.
pub const SHOP_TIER_DATA: &[(i64, i64, i64, i64)] = &[
    (800, 7, 8, 7),
    (1600, 9, 10, 11),
    (2400, 13, 13, 15),
    (3200, 20, 17, 19),
    (4800, 49, 34, 38),
    (7200, 60, 39, 48),
    (9600, 80, 44, 57),
    (16000, 95, 48, 66),
    (22400, 115, 52, 75),
    (28800, 135, 56, 100),
];

// ── Soul level thresholds ──────────────────────────────────────────

/// (threshold_souls, cumulative_boons, cumulative_ability_points).
/// Source: https://deadlock.wiki/Leveling_Up
pub const SOUL_LEVEL_TABLE: &[(i64, i64, i64)] = &[
    (600, 0, 0),
    (900, 1, 1),
    (1200, 2, 1),
    (1500, 3, 2),
    (2100, 4, 2),
    (2800, 5, 3),
    (3600, 6, 3),
    (4400, 7, 4),
    (5200, 8, 5),
    (6000, 9, 6),
    (6800, 10, 7),
    (7700, 11, 8),
    (8600, 12, 9),
    (9600, 13, 10),
    (10600, 14, 11),
    (11600, 15, 12),
    (12600, 16, 13),
    (13800, 17, 14),
    (15600, 18, 15),
    (17600, 19, 16),
    (19600, 20, 17),
    (21600, 21, 18),
    (23600, 22, 19),
    (25600, 23, 20),
    (27600, 24, 21),
    (29600, 25, 22),
    (31600, 26, 23),
    (33600, 27, 24),
    (35600, 28, 25),
    (37600, 29, 26),
    (39600, 30, 27),
    (41600, 31, 28),
    (43600, 32, 29),
    (45600, 33, 30),
    (47600, 34, 31),
    (49600, 35, 32),
];

/// Ability point costs per upgrade tier (T1, T2, T3).
pub const ABILITY_TIER_COSTS: [i64; 3] = [1, 2, 5];

/// Game distance units (inches) per meter. Weapon ranges in the API are in game units.
pub const UNITS_PER_METER: f64 = 39.37;

/// Highest boon count reachable through souls.
pub const MAX_BOONS: i64 = 35;

/// Cumulative boon count for a given soul total.
pub fn souls_to_boons(total_souls: i64) -> i64 {
    SOUL_LEVEL_TABLE.iter().take_while(|r| total_souls >= r.0).last().map(|r| r.1).unwrap_or(0)
}

/// Cumulative ability points for a given soul total.
pub fn souls_to_ability_points(total_souls: i64) -> i64 {
    SOUL_LEVEL_TABLE.iter().take_while(|r| total_souls >= r.0).last().map(|r| r.2).unwrap_or(0)
}

/// Minimum soul total needed to reach a boon count (0 for boon 0).
pub fn boons_to_souls(boons: i64) -> i64 {
    if boons <= 0 {
        return 0;
    }
    SOUL_LEVEL_TABLE.iter().find(|r| r.1 >= boons).map(|r| r.0).unwrap_or_else(|| SOUL_LEVEL_TABLE.last().unwrap().0)
}

/// Shop bonus tiers (game constants).
pub fn load_shop_tiers() -> Vec<ShopTier> {
    SHOP_TIER_DATA
        .iter()
        .map(|&(cost, w, v, s)| ShopTier { cost, weapon_bonus: w, vitality_bonus: v, spirit_bonus: s })
        .collect()
}

// ── Per-hero overrides ─────────────────────────────────────────────

/// Wiki-documented crit bonus scale reductions. Multiplier = 1 + 0.65 × scale.
/// Source: https://deadlock.wiki/Weapon_Damage#Crit_Multiplier
fn crit_bonus_override(name: &str) -> Option<f64> {
    Some(match name {
        "Billy" | "Rem" => 1.0 + 0.65 * 0.80,
        "Celeste" | "The Doorman" | "Kelvin" => 1.0 + 0.65 * 0.75,
        "Drifter" => 1.0 + 0.65 * 0.55,
        "Vyper" => 1.0 + 0.65 * 0.70,
        "Graves" => 1.0,
        _ => return None,
    })
}

/// Heroes whose pellets spread across targets rather than all landing on one.
fn pellet_cap_override(name: &str) -> i64 {
    match name {
        "Drifter" => 1,
        _ => 0,
    }
}

// ── API parsing ────────────────────────────────────────────────────

fn obj<'a>(v: &'a Value, key: &str) -> Option<&'a Map<String, Value>> {
    v.get(key).and_then(Value::as_object)
}

/// `d.get(a) or d.get(b, "")` over string fields.
fn first_str(v: &Value, keys: &[&str]) -> String {
    keys.iter().filter_map(|k| v.get(*k)).find(|x| truthy(x)).map(text).unwrap_or_default()
}

fn weapon_num(wi: &Value, key: &str, default: f64) -> f64 {
    match wi.get(key) {
        Some(v) if truthy(v) => num(v).unwrap_or(default),
        _ => default,
    }
}

/// Parse a hero from the API JSON.
pub fn parse_hero_from_api(hero_data: &Value, hero_items: Option<&Value>, weapons_list: &[Value]) -> HeroStats {
    let name = hero_data.get("name").map(text).unwrap_or_else(|| "Unknown".to_string());
    let images = hero_data.get("images").cloned().unwrap_or(Value::Null);
    let desc = hero_data.get("description").cloned().unwrap_or(Value::Null);

    let stat_val = |key: &str| -> f64 {
        obj(hero_data, "starting_stats")
            .and_then(|s| s.get(key))
            .and_then(|s| s.as_object())
            .and_then(|s| s.get("value"))
            .and_then(num)
            .unwrap_or(0.0)
    };

    let weapon_class = obj(hero_data, "items").and_then(|m| m.get("weapon_primary")).map(text).unwrap_or_default();

    let hero_id_str = hero_data.get("id").map(text).unwrap_or_default();
    let h_items: &[Value] =
        hero_items.and_then(|hi| hi.get(&hero_id_str)).and_then(Value::as_array).map(|v| v.as_slice()).unwrap_or(&[]);

    // Look for the weapon in the per-hero items first, then the global weapons list.
    let mut weapon_source: Option<&Value> =
        h_items.iter().find(|it| str_of(it, "type") == "weapon" && str_of(it, "class_name") == weapon_class);
    if weapon_source.is_none() && !weapon_class.is_empty() {
        weapon_source = weapons_list.iter().find(|w| str_of(w, "class_name") == weapon_class);
    }

    let mut base_bullet_damage = 0.0;
    let mut pellets = 1i64;
    let mut base_ammo = 0i64;
    let mut fire_rate = 0.0;
    let mut falloff_start = 0.0;
    let mut falloff_end = 0.0;
    let mut reload_dur = 0.0;
    let mut cycle_time = 0.0;
    let mut can_zoom = false;
    let mut crit_bonus_start = 1.65;

    if let Some(wi) = weapon_source.and_then(|w| w.get("weapon_info")).filter(|wi| truthy(wi)) {
        base_bullet_damage = weapon_num(wi, "bullet_damage", 0.0);
        pellets = weapon_num(wi, "bullets", 1.0) as i64;
        base_ammo = weapon_num(wi, "clip_size", 0.0) as i64;
        cycle_time = weapon_num(wi, "cycle_time", 0.0);
        if cycle_time > 0.0 {
            fire_rate = 1.0 / cycle_time;
        }
        // Stored in meters so they compare directly with engagement distances.
        falloff_start = weapon_num(wi, "damage_falloff_start_range", 0.0) / UNITS_PER_METER;
        falloff_end = weapon_num(wi, "damage_falloff_end_range", 0.0) / UNITS_PER_METER;
        reload_dur = weapon_num(wi, "reload_duration", 0.0);
        can_zoom = wi.get("can_zoom").map(truthy).unwrap_or(false);
        crit_bonus_start = weapon_num(wi, "crit_bonus_start", 1.65);
    }

    let base_dps = base_bullet_damage * pellets as f64 * fire_rate;
    let base_dpm = base_bullet_damage * pellets as f64 * base_ammo as f64;

    // Per-boon scaling: try both short and long key formats.
    let level_up = |short: &str, long: &str| -> f64 {
        let ups = obj(hero_data, "standard_level_up_upgrades");
        [short, long]
            .iter()
            .filter_map(|k| ups.and_then(|u| u.get(*k)))
            .find(|v| truthy(v))
            .and_then(num)
            .unwrap_or(0.0)
    };
    let damage_gain = level_up("EBulletDamage", "MODIFIER_VALUE_BASE_BULLET_DAMAGE_FROM_LEVEL");
    let hp_gain = level_up("EMaxHealth", "MODIFIER_VALUE_BASE_HEALTH_FROM_LEVEL");
    let spirit_gain = level_up("EAbilityPoint", "MODIFIER_VALUE_TECH_POWER");

    let base_hp = stat_val("max_health");
    // Max-level projections (assuming ~48 boons at max level).
    let max_boons = 48.0;
    let max_gun_damage = base_bullet_damage * (1.0 + damage_gain * max_boons);

    let abilities: Vec<HeroAbility> =
        h_items.iter().filter(|it| str_of(it, "type") == "ability").map(parse_ability).collect();

    let flag = |k: &str| hero_data.get(k).map(truthy).unwrap_or(false);
    let desc_field = |k: &str| {
        if desc.is_object() {
            desc.get(k).filter(|v| truthy(v)).map(text).unwrap_or_default()
        } else {
            String::new()
        }
    };

    HeroStats {
        hero_id: hero_data.get("id").and_then(Value::as_i64).unwrap_or(0),
        class_name: str_of(hero_data, "class_name").to_string(),
        base_bullet_damage,
        pellets,
        base_ammo,
        base_fire_rate: fire_rate,
        base_dps,
        base_dpm,
        falloff_range_min: falloff_start,
        falloff_range_max: falloff_end,
        alt_fire_type: if can_zoom { "zoom".into() } else { String::new() },
        alt_fire_pellets: 1,
        light_melee_damage: stat_val("light_melee_damage"),
        heavy_melee_damage: stat_val("heavy_melee_damage"),
        hero_labs: flag("in_development") || flag("needs_testing"),
        base_hp,
        base_regen: stat_val("base_health_regen"),
        base_move_speed: stat_val("max_move_speed"),
        base_sprint: stat_val("sprint_speed"),
        base_stamina: stat_val("stamina") as i64,
        damage_gain,
        hp_gain,
        spirit_gain,
        max_level_hp: base_hp + hp_gain * max_boons,
        max_gun_damage,
        max_gun_dps: max_gun_damage * pellets as f64 * fire_rate,
        icon_url: first_str(&images, &["icon_hero_card_webp", "icon_hero_card"]),
        hero_card_url: first_str(&images, &["top_bar_vertical_image_webp", "top_bar_vertical_image"]),
        minimap_url: first_str(&images, &["minimap_image_webp", "minimap_image"]),
        lore: desc_field("lore"),
        role: desc_field("role"),
        playstyle: desc_field("playstyle"),
        abilities,
        weapon_class_name: weapon_class,
        reload_duration: reload_dur,
        crit_bonus_start: crit_bonus_override(&name).unwrap_or(crit_bonus_start),
        cycle_time,
        max_pellets_per_target: pellet_cap_override(&name),
        name,
    }
}

/// Numeric `value` of a property object, if the property is an object with a numeric value.
fn prop_value(prop: &Value) -> Option<f64> {
    prop.as_object().and_then(|p| p.get("value")).and_then(num)
}

/// Fraction of light melee damage an ability uses as its base (0 = not melee-scaled).
fn parse_melee_scale(props: &Map<String, Value>) -> f64 {
    for key in ["LightMeleeScalePct", "LightMeleeScale"] {
        if let Some(v) = props.get(key).and_then(prop_value) {
            return v / 100.0;
        }
    }
    if let Some(v) = props.get("CountsAsLightMelee").and_then(prop_value) {
        if v >= 1.0 {
            return 1.0;
        }
    }
    0.0
}

/// Priority-ordered keys that indicate ability damage output.
const ABILITY_DAMAGE_KEYS: &[&str] = &[
    "AbilityDamage",
    "Damage",
    "DPS",
    "DamagePerSecond",
    "DamagePerProjectile",
    "DamagePerRocket",
    "ExplodeDamage",
    "StompDamage",
    "TurretDPS",
    "SummonDPS",
    "SummonMeleeDamage",
    "BleedDPSPerStack",
    "TechDamage",
    "BulletDamage",
    "BonusDamage",
    "CurrentHealthDamage",
    "MaxHealthDamage",
];

/// Parse an ability from the API item data.
pub fn parse_ability(item_data: &Value) -> HeroAbility {
    let desc = item_data.get("description").cloned().unwrap_or(Value::Null);
    let desc_text = if desc.is_object() { first_str(&desc, &["desc", "active", "passive"]) } else { String::new() };
    let image_url = first_str(item_data, &["image_webp", "image"]);

    let props: Map<String, Value> = obj(item_data, "properties").cloned().unwrap_or_default();
    let mut base_damage = 0.0;
    let mut cooldown = 0.0;
    let mut duration = 0.0;
    let mut spirit_scaling = 0.0;
    let mut is_dps = false;

    for (key, prop) in &props {
        let Some(fval) = prop_value(prop) else { continue };
        let key_lower = key.to_lowercase();
        if key_lower.contains("cooldown") && cooldown == 0.0 {
            cooldown = fval;
        } else if (key == "AbilityDuration" || key == "AbilityChannelTime") && fval > 0.0 && duration == 0.0 {
            // Primary duration sources — the ability's own effect window.
            duration = fval;
        }
        if let Some(scale) = prop
            .get("scale_function")
            .and_then(Value::as_object)
            .filter(|sf| !sf.is_empty())
            .and_then(|sf| sf.get("stat_scale"))
            .and_then(num)
        {
            spirit_scaling = scale;
        }
    }

    // Damage from the priority-ordered key list.
    for dkey in ABILITY_DAMAGE_KEYS {
        if let Some(v) = props.get(*dkey).and_then(prop_value) {
            base_damage = v;
            // A DPS property with a duration is converted to total damage; its
            // spirit scaling applies per second too, so scale it the same way.
            is_dps = dkey.contains("DPS");
            if is_dps && duration > 0.0 {
                base_damage *= duration;
                if spirit_scaling > 0.0 {
                    spirit_scaling *= duration;
                }
            }
            break;
        }
    }

    if base_damage == 0.0 {
        // Fallback: any property with "damage" in the name.
        for (key, prop) in &props {
            let key_lower = key.to_lowercase();
            if key_lower.contains("damage") && !key_lower.contains("reduction") {
                if let Some(v) = prop_value(prop) {
                    base_damage = v;
                    break;
                }
            }
        }
    }

    // Human-readable tier descriptions from the description dict.
    let tier_desc = |tier: i64| -> String {
        if !desc.is_object() {
            return String::new();
        }
        desc.get(format!("t{tier}_desc")).filter(|v| truthy(v)).map(text).unwrap_or_default()
    };

    let mut upgrades = Vec::new();
    let raw_upgrades: &[Value] =
        item_data.get("upgrades").and_then(Value::as_array).map(|v| v.as_slice()).unwrap_or(&[]);
    for (i, upg) in raw_upgrades.iter().enumerate() {
        if !upg.is_object() {
            continue;
        }
        let tier = i as i64 + 1;
        let prop_upgrades: Vec<Value> =
            upg.get("property_upgrades").and_then(Value::as_array).cloned().unwrap_or_default();
        let mut upg_desc = tier_desc(tier);
        if upg_desc.is_empty() {
            upg_desc = upg.get("description").filter(|v| truthy(v)).map(text).unwrap_or_default();
        }
        if upg_desc.is_empty() {
            // Last resort: build from property_upgrades.
            let parts: Vec<String> = prop_upgrades
                .iter()
                .filter_map(|pu| {
                    let pname = str_of(pu, "name");
                    let bonus = pu.get("bonus").map(text).unwrap_or_default();
                    (!pname.is_empty() && !bonus.is_empty()).then(|| format!("{pname}: {bonus}"))
                })
                .collect();
            upg_desc = parts.join(", ");
        }
        if !upg_desc.is_empty() {
            upgrades.push(AbilityUpgrade { tier, description: upg_desc, property_upgrades: prop_upgrades });
        }
    }
    if upgrades.is_empty() {
        for tier in 1..=3 {
            let d = tier_desc(tier);
            if !d.is_empty() {
                upgrades.push(AbilityUpgrade { tier, description: d, property_upgrades: Vec::new() });
            }
        }
    }

    HeroAbility {
        name: str_of(item_data, "name").to_string(),
        class_name: str_of(item_data, "class_name").to_string(),
        ability_type: str_of(item_data, "ability_type").to_string(),
        description: desc_text,
        image_url,
        cooldown,
        duration,
        base_damage,
        spirit_scaling,
        melee_scale: parse_melee_scale(&props),
        is_dps,
        upgrades,
        properties: props.into(),
    }
}

fn item_tier(item_data: &Value, default: i64) -> i64 {
    match item_data.get("item_tier") {
        Some(Value::Number(n)) => n.as_i64().unwrap_or(default),
        Some(Value::String(s)) => s.trim().parse().unwrap_or(default),
        _ => default,
    }
}

/// Parse a shop upgrade item from API data. Returns `None` for non-upgrades and free items.
pub fn parse_upgrade_item(item_data: &Value) -> Option<Item> {
    if str_of(item_data, "type") != "upgrade" {
        return None;
    }
    let cost = item_data.get("cost").and_then(num).unwrap_or(0.0) as i64;
    if cost == 0 {
        return None;
    }
    let slot = item_data.get("item_slot_type").and_then(Value::as_str).unwrap_or("weapon");
    let category = match slot {
        "spirit" => "spirit",
        "vitality" => "vitality",
        _ => "weapon",
    };

    let desc = item_data.get("description").cloned().unwrap_or(Value::Null);
    let description = if desc.is_object() { first_str(&desc, &["desc", "active", "passive"]) } else { String::new() };

    let props: Map<String, Value> = obj(item_data, "properties").cloned().unwrap_or_default();
    let mut item = Item {
        name: str_of(item_data, "name").to_string(),
        category: category.to_string(),
        tier: item_tier(item_data, 1),
        cost,
        item_id: item_data.get("id").and_then(Value::as_i64).unwrap_or(0),
        class_name: str_of(item_data, "class_name").to_string(),
        image_url: first_str(item_data, &["shop_image_small_webp", "shop_image_webp", "image_webp", "image"]),
        description,
        is_active: item_data.get("is_active_item").map(truthy).unwrap_or(false),
        activation: str_of(item_data, "activation").to_string(),
        tooltip_sections: item_data
            .get("tooltip_sections")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
            .into(),
        ..Default::default()
    };

    let mut stats: IndexMap<&'static str, f64> = IndexMap::new();
    let mut raw_properties: Map<String, Value> = Map::new();
    for (key, prop) in &props {
        let Some(p) = prop.as_object() else { continue };
        let Some(val) = p.get("value").filter(|v| !v.is_null()) else { continue };
        raw_properties.insert(key.clone(), prop.clone());

        if let Some(cond) = p.get("conditional").filter(|c| truthy(c)) {
            item.condition = text(cond);
        }

        let Some(mapped) = upgrade_prop_field(key) else { continue };
        let is_conditional = p
            .get("usage_flags")
            .and_then(Value::as_array)
            .is_some_and(|f| f.iter().any(|x| x.as_str() == Some("ConditionallyApplied")));
        // When an item has both lifesteal variants, the "Hero" one is the active boost.
        if key == "AbilityLifestealPercentHero" && props.contains_key("AbilityLifestealPercentHeroPassive") {
            continue;
        }
        let Some(mut fval) = num(val) else { continue };
        if mapped == "ammo_flat" {
            fval = fval.trunc();
        }
        if NEGATE_PROPS.contains(&key.as_str()) {
            fval = -fval;
        }
        if PCT_FIELDS.contains(&mapped) {
            fval /= 100.0;
        }
        if is_conditional {
            *item.conditional_stats.entry(mapped.to_string()).or_insert(0.0) += fval;
        } else {
            *stats.entry(mapped).or_insert(0.0) += fval;
        }
    }
    item.raw_properties = raw_properties.into();
    for (field, v) in stats {
        item.set_stat(field, v);
    }
    Some(item)
}

// ── Public API ─────────────────────────────────────────────────────

const NO_CACHE: &str = "No API cache found. Run `deadlock-sim refresh` to fetch data.";

/// Parse heroes from raw API payloads.
pub fn heroes_from(
    heroes_data: &Value,
    hero_items_data: Option<&Value>,
    weapons_data: Option<&Value>,
) -> Result<IndexMap<String, HeroStats>, String> {
    let list = heroes_data.as_array().filter(|a| !a.is_empty()).ok_or("heroes cache is empty or corrupt.")?;
    let weapons: &[Value] = weapons_data.and_then(Value::as_array).map(|v| v.as_slice()).unwrap_or(&[]);
    let mut heroes = IndexMap::new();
    for h in list {
        if !h.get("player_selectable").map(truthy).unwrap_or(true) {
            continue;
        }
        if h.get("disabled").map(truthy).unwrap_or(false) || h.get("in_development").map(truthy).unwrap_or(false) {
            continue;
        }
        let hero = parse_hero_from_api(h, hero_items_data, weapons);
        heroes.insert(hero.name.clone(), hero);
    }
    Ok(heroes)
}

/// Load heroes from the API cache.
pub fn load_heroes() -> Result<IndexMap<String, HeroStats>, String> {
    if !api_client::is_cache_available() {
        return Err(NO_CACHE.into());
    }
    let heroes = api_client::load_cache("heroes").ok_or("heroes cache is empty or corrupt.")?;
    let hero_items = api_client::load_cache("hero_items");
    let weapons = api_client::load_cache("weapons");
    heroes_from(&heroes, hero_items.as_ref(), weapons.as_ref())
}

fn is_shop_upgrade(i: &Value) -> bool {
    str_of(i, "type") == "upgrade" && i.get("shopable").map(truthy).unwrap_or(false)
}

/// Parse shop upgrade items from the raw API payload.
pub fn items_from(items_data: &Value) -> Result<IndexMap<String, Item>, String> {
    let list = items_data.as_array().filter(|a| !a.is_empty()).ok_or("items cache is empty or corrupt.")?;
    let mut items: IndexMap<String, Item> = IndexMap::new();
    for i in list.iter().filter(|i| is_shop_upgrade(i)) {
        if let Some(item) = parse_upgrade_item(i) {
            items.insert(item.name.clone(), item);
        }
    }

    // Component graph: which items a given item is built from / upgrades into.
    let class_to_name: IndexMap<String, String> =
        items.values().map(|it| (it.class_name.clone(), it.name.clone())).collect();
    let mut upgrades_map: IndexMap<String, Vec<(i64, String)>> = IndexMap::new();
    for i in list.iter().filter(|i| is_shop_upgrade(i)) {
        let target_name = str_of(i, "name");
        if !items.contains_key(target_name) {
            continue;
        }
        let target_tier = item_tier(i, 99);
        let comps: Vec<String> = i
            .get("component_items")
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|c| c.as_str()).filter_map(|c| class_to_name.get(c).cloned()).collect())
            .unwrap_or_default();
        for source in &comps {
            upgrades_map.entry(source.clone()).or_default().push((target_tier, target_name.to_string()));
        }
        if !comps.is_empty() {
            items[target_name].component_names = comps;
        }
    }
    for (source, mut targets) in upgrades_map {
        // Pick the lowest-tier target (closest upgrade).
        targets.sort_by_key(|t| t.0);
        items[&source].upgrades_to = targets[0].1.clone();
    }
    Ok(items)
}

/// Load shop upgrade items from the API cache.
pub fn load_items() -> Result<IndexMap<String, Item>, String> {
    if !api_client::is_cache_available() {
        return Err(NO_CACHE.into());
    }
    let items = api_client::load_cache("items").ok_or("items cache is empty or corrupt.")?;
    items_from(&items)
}

/// Flag heroes with suspicious data.
pub fn sanity_warnings(heroes: &IndexMap<String, HeroStats>) -> Vec<ParseWarning> {
    let mut warnings = Vec::new();
    for (name, hero) in heroes {
        if hero.base_bullet_damage == 0.0 && hero.base_fire_rate == 0.0 {
            warnings.push(ParseWarning {
                entity: format!("hero:{name}"),
                field: "weapon".into(),
                message: "Hero has zero bullet damage and fire rate — weapon data may be missing".into(),
            });
        }
        if hero.base_hp == 0.0 {
            warnings.push(ParseWarning {
                entity: format!("hero:{name}"),
                field: "base_hp".into(),
                message: "Hero has zero base HP".into(),
            });
        }
    }
    warnings
}
