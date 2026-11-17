//! Shared damage primitives: pure math with no dependencies on other engine modules.

use serde_json::{Map, Value};

use crate::models::num;

/// Effective resist after shred: `clamp(base_resist * (1 - clamp(shred)))`.
pub fn resist_after_shred(base_resist: f64, total_shred: f64) -> f64 {
    let clamped_shred = total_shred.clamp(0.0, 1.0);
    (base_resist * (1.0 - clamped_shred)).clamp(0.0, 1.0)
}

/// Lowest fraction of damage dealt at or beyond the falloff end range.
pub const MIN_FALLOFF_FRACTION: f64 = 0.1;

/// Damage falloff multiplier for a distance.
///
/// Full damage within `falloff_min`, linear interpolation down to
/// [`MIN_FALLOFF_FRACTION`] at `falloff_max`; no falloff if the range is invalid.
pub fn falloff_multiplier(distance: f64, falloff_min: f64, falloff_max: f64) -> f64 {
    if falloff_max <= falloff_min || falloff_max <= 0.0 {
        return 1.0;
    }
    if distance <= falloff_min {
        return 1.0;
    }
    if distance >= falloff_max {
        return MIN_FALLOFF_FRACTION;
    }
    let t = (distance - falloff_min) / (falloff_max - falloff_min);
    1.0 - t * (1.0 - MIN_FALLOFF_FRACTION)
}

/// `base_damage * (1 + spirit_amp) * (1 + damage_amp)`.
pub fn apply_amplifiers(base_damage: f64, spirit_amp: f64, damage_amp: f64) -> f64 {
    base_damage * (1.0 + spirit_amp) * (1.0 + damage_amp)
}

/// Damage information extracted from an item's raw properties.
#[derive(Debug, Clone, PartialEq)]
pub struct ItemDamageInfo {
    pub base_damage: f64,
    /// API scale type, e.g. `ETechPower`, `ELevelUpBoons`.
    pub scale_type: String,
    pub stat_scale: f64,
    pub is_dps: bool,
    pub proc_cooldown: f64,
    /// Percent chance (0-100).
    pub proc_chance: f64,
}

/// Property keys that indicate damage output, ordered by priority.
const DAMAGE_KEYS: &[&str] = &[
    "DPS",
    "DPSMax",
    "ProcBonusMagicDamage",
    "DamagePerChain",
    "AbilityDamage",
    "TechDamage",
    "DotHealthPercent",
    "BulletDamage",
    "HeadShotBonusDamage",
    "BonusDamage",
    "Damage",
];

/// Extract damage info from item raw properties, or `None` if the item deals no damage.
pub fn extract_item_damage(props: &Map<String, Value>) -> Option<ItemDamageInfo> {
    let (key, prop, base_damage) = DAMAGE_KEYS.iter().find_map(|key| {
        let prop = props.get(*key)?.as_object()?;
        let v = num(prop.get("value")?)?;
        Some((*key, prop, v))
    })?;

    let scale_fn = prop.get("scale_function").and_then(Value::as_object);
    let scale_type = scale_fn
        .and_then(|sf| sf.get("specific_stat_scale_type"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let stat_scale = scale_fn.and_then(|sf| sf.get("stat_scale")).and_then(num).unwrap_or(0.0);

    let nonempty = |k: &str| props.get(k).filter(|v| crate::models::truthy(v));
    let proc_cooldown = nonempty("ProcCooldown")
        .or_else(|| props.get("AbilityCooldown"))
        .and_then(Value::as_object)
        .map(|p| match p.get("value") {
            None => 0.0,
            Some(v) => num(v).unwrap_or(0.0),
        })
        .unwrap_or(0.0);
    let proc_chance = props
        .get("ProcChance")
        .and_then(Value::as_object)
        .map(|p| match p.get("value") {
            None => 100.0,
            Some(v) => num(v).unwrap_or(100.0),
        })
        .unwrap_or(100.0);

    Some(ItemDamageInfo {
        base_damage,
        scale_type,
        stat_scale,
        is_dps: matches!(key, "DPS" | "DPSMax" | "DotHealthPercent"),
        proc_cooldown,
        proc_chance,
    })
}

/// Float value of a property, or `default` when absent/non-numeric.
pub fn prop_float(props: &Map<String, Value>, key: &str, default: f64) -> f64 {
    match props.get(key).and_then(Value::as_object) {
        None => default,
        Some(p) => match p.get("value") {
            None => default,
            Some(v) => num(v).unwrap_or(default),
        },
    }
}

/// `(scale type, coefficient)` of a property's scale function.
pub fn prop_scale(props: &Map<String, Value>, key: &str) -> (String, f64) {
    let Some(sf) = props
        .get(key)
        .and_then(Value::as_object)
        .and_then(|p| p.get("scale_function"))
        .and_then(Value::as_object)
    else {
        return (String::new(), 0.0);
    };
    (
        sf.get("specific_stat_scale_type").and_then(Value::as_str).unwrap_or("").to_string(),
        sf.get("stat_scale").and_then(num).unwrap_or(0.0),
    )
}
