//! Compact, URL-safe build codes for sharing builds.
//!
//! Format: `v1-<hero id>-<extra souls>-<ability tiers>-<item id>.<item id>...`
//! with numbers in base 36 and one digit (0-3) per ability.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::data::GameData;

/// A build as it is shared and saved: names only, no derived numbers.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct SharedBuild {
    pub hero: String,
    pub items: Vec<String>,
    pub extra_souls: i64,
    /// Ability index → highest purchased tier (1-3).
    pub ability_upgrades: BTreeMap<usize, i64>,
}

const VERSION: &str = "v1";

fn to_base36(mut n: u64) -> String {
    if n == 0 {
        return "0".into();
    }
    let mut digits = Vec::new();
    while n > 0 {
        digits.push(char::from_digit((n % 36) as u32, 36).expect("digit"));
        n /= 36;
    }
    digits.iter().rev().collect()
}

fn from_base36(s: &str) -> Option<u64> {
    if s.is_empty() || s.len() > 13 {
        return None;
    }
    u64::from_str_radix(s, 36).ok()
}

/// Encode a build as a share code. Unknown hero or item names are an error.
pub fn encode(build: &SharedBuild, data: &GameData) -> Result<String, String> {
    let hero = data.hero_or_err(&build.hero)?;
    let tiers: String = (0..hero.abilities.len())
        .map(|i| char::from_digit(build.ability_upgrades.get(&i).copied().unwrap_or(0).clamp(0, 3) as u32, 10).unwrap())
        .collect();
    let items: Vec<String> = data.resolve_items(&build.items)?.iter().map(|i| to_base36(i.item_id as u64)).collect();
    Ok(format!(
        "{VERSION}-{}-{}-{}-{}",
        to_base36(hero.hero_id as u64),
        to_base36(build.extra_souls.max(0) as u64),
        if tiers.is_empty() { "0".to_string() } else { tiers },
        items.join(".")
    ))
}

/// Decode a share code. Items that no longer exist are skipped and reported.
pub fn decode(code: &str, data: &GameData) -> Result<(SharedBuild, Vec<String>), String> {
    let parts: Vec<&str> = code.trim().split('-').collect();
    let [version, hero_id, souls, tiers, item_ids] = parts[..] else {
        return Err("Build code is malformed (expected 5 dash-separated parts).".into());
    };
    if version != VERSION {
        return Err(format!("Unsupported build code version '{version}'."));
    }
    let hero_id = from_base36(hero_id).ok_or("Build code has an invalid hero id.")? as i64;
    let hero = data
        .heroes
        .values()
        .find(|h| h.hero_id == hero_id)
        .ok_or("Build code refers to a hero that is not in the loaded data.")?;
    let extra_souls = from_base36(souls).ok_or("Build code has an invalid soul count.")?.min(1_000_000) as i64;

    let mut ability_upgrades = BTreeMap::new();
    for (i, ch) in tiers.chars().enumerate().take(hero.abilities.len()) {
        match ch.to_digit(10) {
            Some(t @ 1..=3) => {
                ability_upgrades.insert(i, t as i64);
            }
            Some(0) => {}
            _ => return Err("Build code has invalid ability tiers.".into()),
        }
    }

    let mut items = Vec::new();
    let mut warnings = Vec::new();
    for id in item_ids.split('.').filter(|s| !s.is_empty()) {
        let id = from_base36(id).ok_or("Build code has an invalid item id.")? as i64;
        match data.items.values().find(|i| i.item_id == id) {
            Some(item) if !items.contains(&item.name) => items.push(item.name.clone()),
            Some(_) => {}
            None => warnings.push(format!("Item id {id} is not in the loaded data and was skipped.")),
        }
    }
    Ok((SharedBuild { hero: hero.name.clone(), items, extra_souls, ability_upgrades }, warnings))
}
