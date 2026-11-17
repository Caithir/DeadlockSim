//! Item component rules: buying an upgrade consumes the components you own
//! and is discounted by their cost.

use indexmap::IndexMap;

use crate::models::Item;

use super::builds::MAX_ITEMS;

/// All items `item` is built from, directly or through intermediate upgrades.
pub fn component_closure(item: &Item, items: &IndexMap<String, Item>) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut stack: Vec<&str> = item.component_names.iter().map(String::as_str).collect();
    while let Some(name) = stack.pop() {
        if out.iter().any(|n| n == name) {
            continue;
        }
        out.push(name.to_string());
        if let Some(c) = items.get(name) {
            stack.extend(c.component_names.iter().map(String::as_str));
        }
    }
    out
}

/// What it costs to buy `item` given the items already owned: its price minus
/// the price of each owned component that the purchase consumes.
pub fn purchase_cost(item: &Item, owned: &[Item], items: &IndexMap<String, Item>) -> i64 {
    let closure = component_closure(item, items);
    let credit: i64 = owned.iter().filter(|o| closure.contains(&o.name)).map(|o| o.cost).sum();
    (item.cost - credit).max(0)
}

/// Result of trying to add an item to a build.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AddOutcome {
    /// Added; lists the owned components that were consumed.
    Added { consumed: Vec<String> },
    /// The item is already in the build.
    Duplicate,
    /// No free slot, even after consuming components.
    Full,
    /// The build already holds an upgrade this item is a component of.
    Superseded { by: String },
}

/// Add `item` to `build`, consuming owned components and enforcing slot limits.
pub fn add_item(build: &mut Vec<Item>, item: &Item, items: &IndexMap<String, Item>) -> AddOutcome {
    if build.iter().any(|i| i.name == item.name) {
        return AddOutcome::Duplicate;
    }
    if let Some(owner) = build.iter().find(|o| component_closure(o, items).contains(&item.name)) {
        return AddOutcome::Superseded { by: owner.name.clone() };
    }
    let closure = component_closure(item, items);
    let consumed: Vec<String> = build.iter().filter(|o| closure.contains(&o.name)).map(|o| o.name.clone()).collect();
    if build.len() - consumed.len() >= MAX_ITEMS {
        return AddOutcome::Full;
    }
    // The upgrade takes the slot of the first consumed component.
    let slot = build.iter().position(|o| consumed.contains(&o.name));
    build.retain(|o| !consumed.contains(&o.name));
    match slot {
        Some(i) => build.insert(i.min(build.len()), item.clone()),
        None => build.push(item.clone()),
    }
    AddOutcome::Added { consumed }
}

/// Collapse a list of items so that no item coexists with one of its upgrades.
pub fn normalize_build(names: &[Item], items: &IndexMap<String, Item>) -> Vec<Item> {
    let mut build = Vec::new();
    for item in names {
        add_item(&mut build, item, items);
    }
    build
}
