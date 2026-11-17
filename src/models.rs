//! Data models for Deadlock heroes, items, and combat state.

use std::sync::Arc;

use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// An upgrade tier for a hero ability (T1/T2/T3).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AbilityUpgrade {
    pub tier: i64,
    pub description: String,
    pub property_upgrades: Vec<Value>,
}

/// A hero ability with its properties and upgrades.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct HeroAbility {
    pub name: String,
    pub class_name: String,
    /// innate, signature, ultimate, weapon
    pub ability_type: String,
    pub description: String,
    pub image_url: String,
    pub cooldown: f64,
    pub duration: f64,
    pub base_damage: f64,
    /// Spirit power coefficient.
    pub spirit_scaling: f64,
    /// Fraction of light melee damage used as base (0 = normal ability).
    pub melee_scale: f64,
    /// True when `base_damage` was derived from a DPS property (pre-multiplied by duration).
    pub is_dps: bool,
    pub upgrades: Vec<AbilityUpgrade>,
    /// All raw properties from the API (shared, so clones stay cheap).
    pub properties: Arc<Map<String, Value>>,
}

/// Base stats for a Deadlock hero, loaded from data.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct HeroStats {
    pub name: String,
    pub hero_id: i64,
    pub class_name: String,

    // Gun stats
    pub base_bullet_damage: f64,
    pub pellets: i64,
    pub base_ammo: i64,
    pub base_fire_rate: f64,
    pub base_dps: f64,
    pub base_dpm: f64,
    pub falloff_range_min: f64,
    pub falloff_range_max: f64,

    // Alt fire
    pub alt_fire_type: String,
    pub alt_fire_pellets: i64,

    /// Max pellets that can hit a single target per shot (0 = no cap).
    pub max_pellets_per_target: i64,

    // Melee
    pub light_melee_damage: f64,
    pub heavy_melee_damage: f64,

    // Survivability
    pub base_hp: f64,
    pub base_regen: f64,
    pub base_move_speed: f64,
    pub base_sprint: f64,
    pub base_stamina: i64,

    // Per-boon scaling
    pub damage_gain: f64,
    pub hp_gain: f64,
    pub spirit_gain: f64,

    // Max-level projections
    pub max_level_hp: f64,
    pub max_gun_damage: f64,
    pub max_gun_dps: f64,

    pub hero_labs: bool,

    pub icon_url: String,
    pub hero_card_url: String,
    pub minimap_url: String,

    pub lore: String,
    pub role: String,
    pub playstyle: String,

    pub abilities: Vec<HeroAbility>,

    pub weapon_class_name: String,
    pub reload_duration: f64,
    /// Headshot multiplier (default 1.65; reduced for some heroes, 1.0 = cannot crit).
    pub crit_bonus_start: f64,
    pub cycle_time: f64,
}

impl Default for HeroStats {
    fn default() -> Self {
        HeroStats {
            name: String::new(),
            hero_id: 0,
            class_name: String::new(),
            base_bullet_damage: 0.0,
            pellets: 1,
            base_ammo: 0,
            base_fire_rate: 0.0,
            base_dps: 0.0,
            base_dpm: 0.0,
            falloff_range_min: 0.0,
            falloff_range_max: 0.0,
            alt_fire_type: String::new(),
            alt_fire_pellets: 1,
            max_pellets_per_target: 0,
            light_melee_damage: 0.0,
            heavy_melee_damage: 0.0,
            base_hp: 0.0,
            base_regen: 0.0,
            base_move_speed: 0.0,
            base_sprint: 0.0,
            base_stamina: 0,
            damage_gain: 0.0,
            hp_gain: 0.0,
            spirit_gain: 0.0,
            max_level_hp: 0.0,
            max_gun_damage: 0.0,
            max_gun_dps: 0.0,
            hero_labs: false,
            icon_url: String::new(),
            hero_card_url: String::new(),
            minimap_url: String::new(),
            lore: String::new(),
            role: String::new(),
            playstyle: String::new(),
            abilities: Vec::new(),
            weapon_class_name: String::new(),
            reload_duration: 0.0,
            crit_bonus_start: 1.65,
            cycle_time: 0.0,
        }
    }
}

impl HeroStats {
    /// A featureless target dummy with a fixed HP pool.
    pub fn dummy(name: &str, hp: f64) -> Self {
        HeroStats { name: name.to_string(), base_hp: hp, ..Default::default() }
    }

    /// HP at a boon level, before items.
    pub fn hp_at(&self, boons: i64) -> f64 {
        self.base_hp + self.hp_gain * boons as f64
    }
}

/// Configurable parameters for a damage/TTK calculation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct CombatConfig {
    pub boons: i64,
    pub weapon_damage_bonus: f64,
    pub flat_weapon_bonus: f64,
    pub fire_rate_bonus: f64,
    pub ammo_increase: f64,
    pub ammo_flat: i64,
    pub shred: Vec<f64>,
    pub current_spirit: i64,
    pub spirit_amp: f64,
    pub accuracy: f64,
    pub headshot_rate: f64,
    pub headshot_multiplier: f64,
    pub enemy_bullet_resist: f64,
    pub enemy_spirit_resist: f64,
    pub enemy_hp: f64,
    pub enemy_bonus_hp: f64,
    /// Engagement range in meters (0 = point blank).
    pub distance: f64,
    pub target_bullet_damage_amp: f64,
    pub golden_buffs_count: i64,
    pub golden_weapon_total: f64,
    pub golden_spirit_total: f64,
    pub golden_vitality_total: f64,
    pub berserker_stacks: i64,
    pub intensifying_mag_pct: f64,
    pub opening_rounds_active: bool,
    pub close_range_active: bool,
    pub long_range_active: bool,
}

impl Default for CombatConfig {
    fn default() -> Self {
        CombatConfig {
            boons: 0,
            weapon_damage_bonus: 0.0,
            flat_weapon_bonus: 0.0,
            fire_rate_bonus: 0.0,
            ammo_increase: 0.0,
            ammo_flat: 0,
            shred: Vec::new(),
            current_spirit: 0,
            spirit_amp: 0.0,
            accuracy: 1.0,
            headshot_rate: 0.0,
            headshot_multiplier: 1.65,
            enemy_bullet_resist: 0.0,
            enemy_spirit_resist: 0.0,
            enemy_hp: 0.0,
            enemy_bonus_hp: 0.0,
            distance: 20.0,
            target_bullet_damage_amp: 0.0,
            golden_buffs_count: 0,
            golden_weapon_total: 0.0,
            golden_spirit_total: 0.0,
            golden_vitality_total: 0.0,
            berserker_stacks: 0,
            intensifying_mag_pct: 0.0,
            opening_rounds_active: false,
            close_range_active: false,
            long_range_active: false,
        }
    }
}

/// Configuration for a spirit/ability damage calculation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AbilityConfig {
    pub base_damage: f64,
    pub spirit_multiplier: f64,
    pub current_spirit: f64,
    pub cooldown: f64,
    pub ability_duration: f64,
    pub bonus_duration: f64,
    pub enemy_spirit_resist: f64,
    pub resist_shred: f64,
    pub mystic_vuln: f64,
    pub spirit_amp: f64,
    pub escalating_exposure_stacks: i64,
    pub ee_per_stack: f64,
    pub crippling: f64,
    pub soulshredder: f64,
}

impl Default for AbilityConfig {
    fn default() -> Self {
        AbilityConfig {
            base_damage: 0.0,
            spirit_multiplier: 0.0,
            current_spirit: 0.0,
            cooldown: 0.0,
            ability_duration: 0.0,
            bonus_duration: 0.0,
            enemy_spirit_resist: 0.0,
            resist_shred: 0.0,
            mystic_vuln: 0.0,
            spirit_amp: 0.0,
            escalating_exposure_stacks: 0,
            ee_per_stack: 0.06,
            crippling: 0.0,
            soulshredder: 0.0,
        }
    }
}

/// Shop bonus at a given cost threshold.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct ShopTier {
    pub cost: i64,
    pub weapon_bonus: i64,
    pub vitality_bonus: i64,
    pub spirit_bonus: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct BulletResult {
    pub damage_per_bullet: f64,
    pub bullets_per_second: f64,
    /// Before resist (burst, no reload).
    pub raw_dps: f64,
    /// After resist/shred (burst, no reload).
    pub final_dps: f64,
    /// After resist, including reload downtime.
    pub sustained_dps: f64,
    pub magazine_size: i64,
    pub damage_per_magazine: f64,
    pub magdump_time: f64,
    pub reload_time: f64,
    pub total_shred: f64,
    pub final_resist: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SpiritResult {
    pub raw_damage: f64,
    pub modified_damage: f64,
    pub spirit_contribution: f64,
    pub dps: f64,
    pub total_dot_damage: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TtkResult {
    pub ttk_seconds: f64,
    pub realistic_ttk: f64,
    pub magazines_needed: i64,
    pub can_one_mag: bool,
    pub effective_dps: f64,
    pub realistic_dps: f64,
    pub target_hp: f64,
    pub damage_per_magazine: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct MeleeResult {
    pub light_damage: f64,
    pub heavy_damage: f64,
    pub light_dps: f64,
    pub heavy_dps: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct ItemDamageResult {
    pub item_name: String,
    pub damage_per_hit: f64,
    pub dps: f64,
    /// "spirit", "bullet", or "melee"
    pub damage_type: String,
    /// "spirit", "boons", "weapon" or "none"
    pub scaled_from: String,
    pub spirit_contribution: f64,
    pub boon_contribution: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct AbilityDamageResult {
    pub ability_name: String,
    pub raw_damage: f64,
    pub modified_damage: f64,
    pub spirit_contribution: f64,
    pub dps: f64,
    pub effective_cooldown: f64,
    pub boons: i64,
    pub current_spirit: f64,
}

/// Hero stats at a specific boon level.
#[derive(Debug, Clone, Serialize)]
pub struct ScalingSnapshot {
    pub boon_level: i64,
    pub bullet_damage: f64,
    pub hp: f64,
    pub spirit: f64,
    pub dps: f64,
    pub dpm: f64,
}

/// A purchasable Deadlock item with combat-relevant stats.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Item {
    pub name: String,
    /// "weapon", "vitality", "spirit"
    pub category: String,
    pub tier: i64,
    pub cost: i64,

    pub item_id: i64,
    pub class_name: String,
    pub image_url: String,
    pub description: String,
    pub is_active: bool,

    pub weapon_damage_pct: f64,
    pub fire_rate_pct: f64,
    pub ammo_flat: i64,
    pub ammo_pct: f64,
    pub bullet_resist_pct: f64,
    pub spirit_resist_pct: f64,
    pub bonus_hp: f64,
    pub spirit_power: f64,
    pub bullet_lifesteal: f64,
    pub spirit_lifesteal: f64,
    pub hp_regen: f64,
    pub move_speed: f64,
    pub sprint_speed: f64,
    pub bullet_shield: f64,
    pub spirit_shield: f64,
    pub headshot_bonus: f64,
    pub bullet_resist_shred: f64,
    pub spirit_resist_shred: f64,
    pub cooldown_reduction: f64,
    pub item_cooldown_reduction: f64,
    pub spirit_amp_pct: f64,
    /// % multiplier on total spirit power (e.g. Boundless Spirit).
    pub spirit_power_pct: f64,
    pub melee_damage_pct: f64,
    pub heavy_melee_damage_pct: f64,

    /// Optional condition describing when the stat applies.
    pub condition: String,
    /// Stats only active under specific triggers; keys are stat field names.
    pub conditional_stats: IndexMap<String, f64>,
    /// All raw properties from the API (shared, so clones stay cheap).
    pub raw_properties: Arc<Map<String, Value>>,

    pub activation: String,
    pub tooltip_sections: Arc<Vec<Value>>,
    /// Name of the item this upgrades into.
    pub upgrades_to: String,
    /// Names of the items this is built from.
    pub component_names: Vec<String>,
}

/// Names of every numeric stat field on [`Item`], in display order.
pub const ITEM_STAT_FIELDS: &[&str] = &[
    "weapon_damage_pct",
    "fire_rate_pct",
    "ammo_flat",
    "ammo_pct",
    "bullet_resist_pct",
    "spirit_resist_pct",
    "bonus_hp",
    "spirit_power",
    "bullet_lifesteal",
    "spirit_lifesteal",
    "hp_regen",
    "move_speed",
    "sprint_speed",
    "bullet_shield",
    "spirit_shield",
    "headshot_bonus",
    "bullet_resist_shred",
    "spirit_resist_shred",
    "cooldown_reduction",
    "item_cooldown_reduction",
    "spirit_amp_pct",
    "spirit_power_pct",
    "melee_damage_pct",
    "heavy_melee_damage_pct",
];

impl Item {
    /// Read a stat by field name. Unknown names read as 0.
    pub fn stat(&self, field: &str) -> f64 {
        match field {
            "weapon_damage_pct" => self.weapon_damage_pct,
            "fire_rate_pct" => self.fire_rate_pct,
            "ammo_flat" => self.ammo_flat as f64,
            "ammo_pct" => self.ammo_pct,
            "bullet_resist_pct" => self.bullet_resist_pct,
            "spirit_resist_pct" => self.spirit_resist_pct,
            "bonus_hp" => self.bonus_hp,
            "spirit_power" => self.spirit_power,
            "bullet_lifesteal" => self.bullet_lifesteal,
            "spirit_lifesteal" => self.spirit_lifesteal,
            "hp_regen" => self.hp_regen,
            "move_speed" => self.move_speed,
            "sprint_speed" => self.sprint_speed,
            "bullet_shield" => self.bullet_shield,
            "spirit_shield" => self.spirit_shield,
            "headshot_bonus" => self.headshot_bonus,
            "bullet_resist_shred" => self.bullet_resist_shred,
            "spirit_resist_shred" => self.spirit_resist_shred,
            "cooldown_reduction" => self.cooldown_reduction,
            "item_cooldown_reduction" => self.item_cooldown_reduction,
            "spirit_amp_pct" => self.spirit_amp_pct,
            "spirit_power_pct" => self.spirit_power_pct,
            "melee_damage_pct" => self.melee_damage_pct,
            "heavy_melee_damage_pct" => self.heavy_melee_damage_pct,
            _ => 0.0,
        }
    }

    pub(crate) fn set_stat(&mut self, field: &str, v: f64) {
        match field {
            "weapon_damage_pct" => self.weapon_damage_pct = v,
            "fire_rate_pct" => self.fire_rate_pct = v,
            "ammo_flat" => self.ammo_flat = v as i64,
            "ammo_pct" => self.ammo_pct = v,
            "bullet_resist_pct" => self.bullet_resist_pct = v,
            "spirit_resist_pct" => self.spirit_resist_pct = v,
            "bonus_hp" => self.bonus_hp = v,
            "spirit_power" => self.spirit_power = v,
            "bullet_lifesteal" => self.bullet_lifesteal = v,
            "spirit_lifesteal" => self.spirit_lifesteal = v,
            "hp_regen" => self.hp_regen = v,
            "move_speed" => self.move_speed = v,
            "sprint_speed" => self.sprint_speed = v,
            "bullet_shield" => self.bullet_shield = v,
            "spirit_shield" => self.spirit_shield = v,
            "headshot_bonus" => self.headshot_bonus = v,
            "bullet_resist_shred" => self.bullet_resist_shred = v,
            "spirit_resist_shred" => self.spirit_resist_shred = v,
            "cooldown_reduction" => self.cooldown_reduction = v,
            "item_cooldown_reduction" => self.item_cooldown_reduction = v,
            "spirit_amp_pct" => self.spirit_amp_pct = v,
            "spirit_power_pct" => self.spirit_power_pct = v,
            "melee_damage_pct" => self.melee_damage_pct = v,
            "heavy_melee_damage_pct" => self.heavy_melee_damage_pct = v,
            _ => {}
        }
    }
}

/// A set of items constituting a hero build.
#[derive(Debug, Clone, Default, Serialize)]
pub struct Build {
    pub items: Vec<Item>,
}

impl Build {
    pub fn new(items: Vec<Item>) -> Self {
        Build { items }
    }
    pub fn total_cost(&self) -> i64 {
        self.items.iter().map(|i| i.cost).sum()
    }
    pub fn item_names(&self) -> Vec<String> {
        self.items.iter().map(|i| i.name.clone()).collect()
    }
    /// The build with one more item appended.
    pub fn with(&self, item: &Item) -> Build {
        let mut items = self.items.clone();
        items.push(item.clone());
        Build { items }
    }
}

/// Aggregated combat stats from a build's items.
#[derive(Debug, Clone, Default, Serialize)]
pub struct BuildStats {
    pub weapon_damage_pct: f64,
    pub fire_rate_pct: f64,
    pub ammo_flat: i64,
    pub ammo_pct: f64,
    pub bullet_resist_pct: f64,
    pub spirit_resist_pct: f64,
    pub bonus_hp: f64,
    /// Vitality shop tier bonus (% multiplier on base+boon HP).
    pub base_hp_pct: f64,
    pub spirit_power: f64,
    pub bullet_lifesteal: f64,
    pub spirit_lifesteal: f64,
    pub hp_regen: f64,
    pub bullet_shield: f64,
    pub spirit_shield: f64,
    pub headshot_bonus: f64,
    pub bullet_resist_shred: f64,
    pub spirit_resist_shred: f64,
    pub cooldown_reduction: f64,
    pub item_cooldown_reduction: f64,
    pub spirit_amp_pct: f64,
    pub spirit_power_pct: f64,
    pub melee_damage_pct: f64,
    pub heavy_melee_damage_pct: f64,
    pub total_cost: i64,
    pub weapon_cost: i64,
    pub vitality_cost: i64,
    pub spirit_cost: i64,
}

impl BuildStats {
    /// Add `v` to an additive stat by field name. Returns false for unknown fields.
    pub(crate) fn add_stat(&mut self, field: &str, v: f64) -> bool {
        match field {
            "weapon_damage_pct" => self.weapon_damage_pct += v,
            "fire_rate_pct" => self.fire_rate_pct += v,
            "ammo_flat" => self.ammo_flat += v as i64,
            "ammo_pct" => self.ammo_pct += v,
            "bullet_resist_pct" => self.bullet_resist_pct += v,
            "spirit_resist_pct" => self.spirit_resist_pct += v,
            "bonus_hp" => self.bonus_hp += v,
            "base_hp_pct" => self.base_hp_pct += v,
            "spirit_power" => self.spirit_power += v,
            "bullet_lifesteal" => self.bullet_lifesteal += v,
            "spirit_lifesteal" => self.spirit_lifesteal += v,
            "hp_regen" => self.hp_regen += v,
            "bullet_shield" => self.bullet_shield += v,
            "spirit_shield" => self.spirit_shield += v,
            "headshot_bonus" => self.headshot_bonus += v,
            "bullet_resist_shred" => self.bullet_resist_shred += v,
            "spirit_resist_shred" => self.spirit_resist_shred += v,
            "cooldown_reduction" => self.cooldown_reduction += v,
            "item_cooldown_reduction" => self.item_cooldown_reduction += v,
            "spirit_amp_pct" => self.spirit_amp_pct += v,
            "spirit_power_pct" => self.spirit_power_pct += v,
            "melee_damage_pct" => self.melee_damage_pct += v,
            "heavy_melee_damage_pct" => self.heavy_melee_damage_pct += v,
            "total_cost" => self.total_cost += v as i64,
            "weapon_cost" => self.weapon_cost += v as i64,
            "vitality_cost" => self.vitality_cost += v as i64,
            "spirit_cost" => self.spirit_cost += v as i64,
            _ => return false,
        }
        true
    }
}

/// Result of evaluating a build for a hero.
#[derive(Debug, Clone, Serialize)]
pub struct BuildResult {
    pub hero_name: String,
    pub build: Build,
    pub build_stats: BuildStats,
    pub bullet_result: BulletResult,
    pub ttk_result: Option<TtkResult>,
    pub spirit_dps: f64,
    pub combined_dps: f64,
    pub effective_hp: f64,
}

// ── JSON helpers that mirror how loosely typed API values are read ──

/// Read a JSON value as a number: numbers, numeric strings and booleans convert;
/// everything else (including unit-suffixed strings like `"5m"`) is `None`.
pub fn num(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => {
            let t = s.trim();
            if t.is_empty() {
                None
            } else {
                t.parse::<f64>().ok()
            }
        }
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        _ => None,
    }
}

/// Whether a JSON value is "truthy" (non-null, non-zero, non-empty).
pub fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(false),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Render a scalar JSON value as display text.
pub fn text(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

/// String field of an object, or "".
pub fn str_of<'a>(obj: &'a Value, key: &str) -> &'a str {
    obj.get(key).and_then(Value::as_str).unwrap_or("")
}
