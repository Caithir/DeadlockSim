//! Event-driven combat timeline simulation.
//!
//! Simulates a combat encounter with a priority queue of events: weapon fire,
//! reloads, item procs, DoTs, buildup mechanics, ability casts, melee and
//! cross-item interactions (stacking spirit amp, resist shred, ...).
//!
//! Supports unidirectional (attacker vs. passive target) and bidirectional
//! (both combatants attack) modes. Accuracy and headshots use an
//! expected-value model, so runs are fully deterministic.

use std::collections::{BTreeMap, HashMap};
use std::rc::Rc;
use std::sync::Arc;

use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::models::{Build, HeroStats, Item};

use super::builds::aggregate_stats;
use super::damage::{
    bullet_damage_at_boon, effective_magazine, effective_pellets, fire_rate_with_bonus, melee_damage_raw,
    AbilityUpgrades, UpgradedAbility, HEAVY_MELEE_CYCLE,
};
use super::primitives::{extract_item_damage, falloff_multiplier, prop_float, prop_scale, resist_after_shred};

// ── Enums ─────────────────────────────────────────────────────────

/// Damage type for resist calculations.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DamageType {
    Bullet,
    Spirit,
    Melee,
}

/// How an item participates in the simulation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ItemBehaviorType {
    ProcOnHit,
    Buildup,
    DotActive,
    PulsePassive,
    StackAmplifier,
    DebuffApplier,
}

/// Mechanic-based debuff categories. Any item can contribute to these pools.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DebuffType {
    SpiritResistShred,
    BulletResistShred,
    /// Stacks that amplify spirit damage taken (Escalating Exposure style).
    SpiritAmpStack,
    FireRateSlow,
    MoveSpeedSlow,
    HealReduction,
    /// Target takes more damage from all sources.
    DamageAmp,
}

/// A single debuff on a target, tracked by source and mechanic.
#[derive(Debug, Clone)]
pub struct DebuffInstance {
    pub debuff_type: DebuffType,
    pub source: String,
    pub value: f64,
    pub expire_time: f64,
    pub stacks: i64,
    pub max_stacks: i64,
}

// ── Configuration ─────────────────────────────────────────────────

/// Schedule entry for an active item activation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActiveUse {
    pub item_name: String,
    #[serde(default)]
    pub first_use: f64,
    #[serde(default = "yes")]
    pub use_on_cooldown: bool,
}

/// Schedule entry for a hero ability activation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AbilityUse {
    /// Index into `hero.abilities`.
    pub ability_index: usize,
    #[serde(default)]
    pub first_use: f64,
    #[serde(default = "yes")]
    pub use_on_cooldown: bool,
}

fn yes() -> bool {
    true
}

/// User-configurable simulation settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct SimSettings {
    /// Simulation length in seconds.
    pub duration: f64,
    /// Fraction of shots that land.
    pub accuracy: f64,
    /// Fraction of hits that are headshots.
    pub headshot_rate: f64,
    /// Unused by the engine: the attacker's own crit multiplier applies.
    pub headshot_multiplier: f64,
    /// Fraction of time actively shooting.
    pub weapon_uptime: f64,
    pub ability_uptime: f64,
    pub active_item_uptime: f64,
    /// Engagement range in meters, for damage falloff.
    pub distance: f64,
    pub weave_melee: bool,
    /// Heavy melee during the reload window.
    pub melee_after_reload: bool,
    /// Melee interrupts the reload, extending it.
    pub reload_cancel_melee: bool,
    pub attacker_boons: i64,
    pub defender_boons: i64,
    /// Seconds of continuous fire (100% accuracy) to fill each buildup item's
    /// meter; used to derive buildup per shot from the hero's fire rate.
    pub buildup_time_defaults: HashMap<String, f64>,
    /// Per-item buildup-per-shot overrides (% per bullet); takes precedence.
    pub buildup_overrides: HashMap<String, f64>,
    /// The defender also attacks.
    pub bidirectional: bool,
}

impl Default for SimSettings {
    fn default() -> Self {
        let buildup_time_defaults = [
            ("Toxic Bullets", 1.5),
            ("Slowing Bullets", 1.0),
            ("Weighted Shots", 1.0),
            ("Silencer", 1.0),
            ("Spiritual Overflow", 1.0),
            ("Inhibitor", 1.0),
            ("Glass Cannon", 1.0),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v))
        .collect();
        SimSettings {
            duration: 15.0,
            accuracy: 0.65,
            headshot_rate: 0.10,
            headshot_multiplier: 1.5,
            weapon_uptime: 1.0,
            ability_uptime: 1.0,
            active_item_uptime: 1.0,
            distance: 20.0,
            weave_melee: false,
            melee_after_reload: true,
            reload_cancel_melee: false,
            attacker_boons: 0,
            defender_boons: 0,
            buildup_time_defaults,
            buildup_overrides: HashMap::new(),
            bidirectional: false,
        }
    }
}

/// Full input configuration for a combat simulation.
#[derive(Debug, Clone, Default)]
pub struct SimConfig {
    pub attacker: HeroStats,
    pub attacker_build: Build,
    pub defender: HeroStats,
    pub defender_build: Build,
    pub settings: SimSettings,
    /// Active item schedule (auto-populated if empty).
    pub active_schedule: Vec<ActiveUse>,
    /// Ability schedule (auto-populated if empty).
    pub ability_schedule: Vec<AbilityUse>,
    pub attacker_ability_upgrades: AbilityUpgrades,
    pub defender_ability_upgrades: AbilityUpgrades,
    /// Defender schedules (only used when bidirectional).
    pub defender_active_schedule: Vec<ActiveUse>,
    pub defender_ability_schedule: Vec<AbilityUse>,
}

// ── Item behavior classification ──────────────────────────────────

/// A debuff an item applies on trigger: `(type, value per application, duration)`.
pub type OnHitDebuff = (DebuffType, f64, f64);

/// How a specific item participates in the simulation.
#[derive(Debug, Clone, Serialize)]
pub struct ItemBehavior {
    #[serde(skip)]
    pub item_name: String,
    pub behavior_type: ItemBehaviorType,
    pub damage_type: DamageType,

    // Proc items
    /// Percent chance (0-100).
    pub proc_chance: f64,
    pub proc_cooldown: f64,
    pub proc_damage: f64,
    pub spirit_scale: f64,
    pub boon_scale: f64,

    // Buildup items
    pub buildup_per_shot: f64,
    pub buildup_decay_time: f64,

    // DoT parameters
    pub dot_tick_rate: f64,
    pub dot_duration: f64,
    pub dot_dps: f64,
    pub dot_spirit_scale: f64,
    pub dot_is_percent_hp: bool,

    // Stack/debuff parameters
    pub stack_value: f64,
    pub max_stacks: i64,
    pub debuff_duration: f64,
    pub debuff_value: f64,
    pub on_hit_debuffs: Vec<OnHitDebuff>,

    // Pulse items
    pub pulse_damage: f64,
    pub pulse_cooldown: f64,
    pub pulse_spirit_scale: f64,

    pub active_cooldown: f64,
}

impl ItemBehavior {
    fn new(item: &Item, behavior_type: ItemBehaviorType, on_hit_debuffs: Vec<OnHitDebuff>) -> Self {
        ItemBehavior {
            item_name: item.name.clone(),
            behavior_type,
            damage_type: DamageType::Spirit,
            proc_chance: 100.0,
            proc_cooldown: 0.0,
            proc_damage: 0.0,
            spirit_scale: 0.0,
            boon_scale: 0.0,
            buildup_per_shot: 0.0,
            buildup_decay_time: 0.0,
            dot_tick_rate: 0.5,
            dot_duration: 0.0,
            dot_dps: 0.0,
            dot_spirit_scale: 0.0,
            dot_is_percent_hp: false,
            stack_value: 0.0,
            max_stacks: 0,
            debuff_duration: 0.0,
            debuff_value: 0.0,
            on_hit_debuffs,
            pulse_damage: 0.0,
            pulse_cooldown: 0.0,
            pulse_spirit_scale: 0.0,
            active_cooldown: 0.0,
        }
    }
}

/// All mechanic-based debuffs an item applies, from its properties.
fn collect_debuffs(props: &Map<String, Value>) -> Vec<OnHitDebuff> {
    let pf = |key: &str, default: f64| prop_float(props, key, default);
    let mut debuffs = Vec::new();
    // (property, debuff type, divisor, default duration)
    let simple = [
        ("TechArmorDamageReduction", DebuffType::SpiritResistShred, 100.0, pf("AbilityDuration", 7.0)),
        ("BulletArmorDamageReduction", DebuffType::BulletResistShred, 100.0, pf("AbilityDuration", 7.0)),
        ("FireRateSlow", DebuffType::FireRateSlow, 1.0, pf("AbilityDuration", 5.0)),
        ("SlowPercent", DebuffType::MoveSpeedSlow, 1.0, pf("SlowDuration", pf("AbilityDuration", 4.0))),
        ("HealAmpReceivePenaltyPercent", DebuffType::HealReduction, 1.0, pf("AbilityDuration", pf("DotDuration", 5.0))),
        ("DamageReceivedIncrease", DebuffType::DamageAmp, 1.0, pf("AbilityDuration", 5.0)),
    ];
    for (key, debuff_type, divisor, duration) in simple {
        if props.contains_key(key) {
            let val = pf(key, 0.0);
            if val != 0.0 {
                debuffs.push((debuff_type, val.abs() / divisor, duration.max(1.0)));
            }
        }
    }
    debuffs
}

/// Classify an item by its primary mechanic. Returns `None` for passive-stat-only items.
pub fn classify_item(item: &Item) -> Option<ItemBehavior> {
    let props = &item.raw_properties;
    if props.is_empty() {
        return None;
    }
    let pf = |key: &str, default: f64| prop_float(props, key, default);
    let spirit_scale_of = |key: &str| -> f64 {
        let (scale_type, scale) = prop_scale(props, key);
        if scale_type == "ETechPower" {
            scale
        } else {
            0.0
        }
    };
    let debuffs = collect_debuffs(props);

    // 1. Stack amplifiers (Escalating Exposure).
    if props.contains_key("MagicIncreasePerStack") && props.contains_key("MaxStacks") {
        let mut b = ItemBehavior::new(item, ItemBehaviorType::StackAmplifier, debuffs);
        b.stack_value = pf("MagicIncreasePerStack", 0.0);
        b.max_stacks = pf("MaxStacks", 0.0) as i64;
        b.debuff_duration = pf("AbilityDuration", 12.0);
        b.proc_cooldown = pf("ProcCooldown", 0.7);
        b.debuff_value = pf("TechArmorDamageReduction", 0.0);
        return Some(b);
    }

    // 2. Buildup items (Toxic Bullets and others with BuildUpPerShot).
    if props.contains_key("BuildUpPerShot") {
        let mut b = ItemBehavior::new(item, ItemBehaviorType::Buildup, debuffs);
        b.buildup_per_shot = pf("BuildUpPerShot", 0.0);
        b.buildup_decay_time = pf("BuildUpDuration", 5.0);
        b.dot_dps = pf("DotHealthPercent", 0.0);
        b.dot_spirit_scale = spirit_scale_of("DotHealthPercent");
        b.dot_duration = pf("DotDuration", 4.0);
        b.dot_tick_rate = pf("TickRate", 0.5);
        b.dot_is_percent_hp = b.dot_dps > 0.0 && b.dot_dps < 20.0;
        return Some(b);
    }

    // 3. Pulse items (Torment Pulse — auto-fires on cooldown).
    if props.contains_key("DamagePulseAmount") {
        let mut b = ItemBehavior::new(item, ItemBehaviorType::PulsePassive, debuffs);
        b.pulse_damage = pf("DamagePulseAmount", 0.0);
        b.pulse_cooldown = pf("AbilityCooldown", 1.4);
        b.pulse_spirit_scale = spirit_scale_of("DamagePulseAmount");
        return Some(b);
    }

    // 4. Active DoT items (Decay, Alchemical Fire).
    if item.is_active && (props.contains_key("DotHealthPercent") || props.contains_key("DPS")) {
        let dps_key = if props.contains_key("DPS") { "DPS" } else { "DotHealthPercent" };
        let mut b = ItemBehavior::new(item, ItemBehaviorType::DotActive, debuffs);
        b.dot_dps = pf(dps_key, 0.0);
        b.dot_spirit_scale = spirit_scale_of(dps_key);
        b.dot_duration = pf("AbilityDuration", 10.0);
        b.dot_tick_rate = pf("TickRate", 1.0);
        b.active_cooldown = pf("AbilityCooldown", 30.0);
        return Some(b);
    }

    // 5. Proc-on-hit items (Tesla Bullets, Mystic Shot, ...).
    if props.contains_key("ProcCooldown") {
        if let Some(info) = extract_item_damage(props) {
            let mut b = ItemBehavior::new(item, ItemBehaviorType::ProcOnHit, debuffs);
            let spirit = info.scale_type == "ETechPower";
            b.damage_type = if spirit { DamageType::Spirit } else { DamageType::Bullet };
            b.proc_chance = info.proc_chance;
            b.proc_cooldown = pf("ProcCooldown", 0.0);
            b.proc_damage = info.base_damage;
            b.spirit_scale = if spirit { info.stat_scale } else { 0.0 };
            b.boon_scale = if info.scale_type == "ELevelUpBoons" { info.stat_scale } else { 0.0 };
            return Some(b);
        }
    }

    // 6. Debuff-only items (Mystic Vulnerability, ...).
    if !debuffs.is_empty() {
        let duration = debuffs[0].2;
        let mut b = ItemBehavior::new(item, ItemBehaviorType::DebuffApplier, debuffs);
        b.debuff_duration = duration;
        b.proc_cooldown = pf("ProcCooldown", 0.0);
        return Some(b);
    }

    None
}

/// Classify all items in a build, keeping only those with simulation behaviors.
pub fn classify_build(build: &Build) -> Vec<ItemBehavior> {
    build.items.iter().filter_map(classify_item).collect()
}

// ── Events ────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
enum EventKind {
    BulletFire,
    ReloadStart,
    ReloadEnd,
    /// A DoT tick from an item, by item name.
    ItemDotTick,
    /// A DoT tick from an ability, with its pre-computed raw damage.
    AbilityDotTick {
        damage: f64,
    },
    ActiveUse {
        use_on_cooldown: bool,
    },
    AbilityUse {
        ability_index: usize,
        use_on_cooldown: bool,
    },
    MeleeHit {
        heavy: bool,
    },
    PulseTrigger,
    RegenTick,
    SimEnd,
}

/// An event in the queue, ordered by `(time, priority, combatant)`.
#[derive(Debug, Clone)]
struct SimEvent {
    time: f64,
    priority: i32,
    /// 0 = combatant A (attacker), 1 = combatant B (defender).
    combatant: usize,
    kind: EventKind,
    source: Arc<str>,
}

impl SimEvent {
    fn before(&self, other: &SimEvent) -> bool {
        (self.time, self.priority, self.combatant) < (other.time, other.priority, other.combatant)
    }
}

/// Binary min-heap with a fixed sift order, so that events with equal keys are
/// always processed in the same sequence for a given configuration.
#[derive(Default)]
struct EventQueue {
    heap: Vec<SimEvent>,
}

impl EventQueue {
    fn push(&mut self, event: SimEvent) {
        self.heap.push(event);
        let last = self.heap.len() - 1;
        self.sift_down(0, last);
    }

    fn pop(&mut self) -> Option<SimEvent> {
        let last = self.heap.pop()?;
        if self.heap.is_empty() {
            return Some(last);
        }
        let top = std::mem::replace(&mut self.heap[0], last);
        self.sift_up(0);
        Some(top)
    }

    /// Move the item at `pos` towards the root until its parent is not after it.
    fn sift_down(&mut self, start: usize, mut pos: usize) {
        let item = self.heap[pos].clone();
        while pos > start {
            let parent = (pos - 1) >> 1;
            if item.before(&self.heap[parent]) {
                self.heap[pos] = self.heap[parent].clone();
                pos = parent;
            } else {
                break;
            }
        }
        self.heap[pos] = item;
    }

    /// Bubble the smaller child up to a leaf, then sift the displaced item back.
    fn sift_up(&mut self, mut pos: usize) {
        let end = self.heap.len();
        let start = pos;
        let item = self.heap[pos].clone();
        let mut child = 2 * pos + 1;
        while child < end {
            let right = child + 1;
            if right < end && !self.heap[child].before(&self.heap[right]) {
                child = right;
            }
            self.heap[pos] = self.heap[child].clone();
            pos = child;
            child = 2 * pos + 1;
        }
        self.heap[pos] = item;
        self.sift_down(start, pos);
    }
}

// ── Mutable combat state ─────────────────────────────────────────

/// Defensive state of a combatant: HP, shields, regen, and debuffs applied by the opponent.
#[derive(Debug, Clone, Default)]
struct TargetState {
    hp: f64,
    max_hp: f64,
    bullet_shield: f64,
    spirit_shield: f64,
    hp_regen: f64,
    base_bullet_resist: f64,
    base_spirit_resist: f64,
    debuffs: Vec<DebuffInstance>,
}

impl TargetState {
    /// Sum of all active debuff values of a type (additive, stacks multiply).
    fn total_for(&self, debuff_type: DebuffType, time: f64) -> f64 {
        let mut total = 0.0;
        for d in &self.debuffs {
            if d.debuff_type == debuff_type && d.expire_time > time {
                total += d.value * d.stacks as f64;
            }
        }
        total
    }

    fn effective_bullet_resist(&self, time: f64) -> f64 {
        let shred = self.total_for(DebuffType::BulletResistShred, time).min(1.0);
        resist_after_shred(self.base_bullet_resist, shred)
    }

    fn effective_spirit_resist(&self, time: f64) -> f64 {
        let shred = self.total_for(DebuffType::SpiritResistShred, time).min(1.0);
        resist_after_shred(self.base_spirit_resist, shred)
    }

    fn effective_spirit_amp(&self, time: f64) -> f64 {
        self.total_for(DebuffType::SpiritAmpStack, time) / 100.0
    }

    fn effective_damage_amp(&self, time: f64) -> f64 {
        self.total_for(DebuffType::DamageAmp, time) / 100.0
    }

    fn effective_heal_reduction(&self, time: f64) -> f64 {
        (self.total_for(DebuffType::HealReduction, time) / 100.0).min(1.0)
    }

    fn effective_fire_rate_slow(&self, time: f64) -> f64 {
        self.total_for(DebuffType::FireRateSlow, time) / 100.0
    }

    /// Apply or refresh a debuff. Stacking debuffs gain a stack on reapplication.
    fn apply_debuff(
        &mut self,
        debuff_type: DebuffType,
        source: &str,
        value: f64,
        duration: f64,
        time: f64,
        max_stacks: i64,
    ) {
        let expire = time + duration;
        if let Some(d) = self.debuffs.iter_mut().find(|d| d.debuff_type == debuff_type && d.source == source) {
            if max_stacks > 1 {
                d.stacks = (d.stacks + 1).min(max_stacks);
            }
            d.expire_time = expire;
            return;
        }
        self.debuffs.push(DebuffInstance {
            debuff_type,
            source: source.to_string(),
            value,
            expire_time: expire,
            stacks: 1,
            max_stacks,
        });
    }

    fn cleanup_expired(&mut self, time: f64) {
        self.debuffs.retain(|d| d.expire_time > time);
    }
}

/// Offensive state of a combatant.
#[derive(Debug, Clone, Default)]
struct AttackerState {
    ammo_remaining: i64,
    /// Per-shot damage after boons, pellets and item bonuses.
    weapon_damage: f64,
    fire_rate: f64,
    magazine_size: i64,
    reload_time: f64,
    light_melee_damage: f64,
    heavy_melee_damage: f64,
    spirit_power: f64,
    spirit_amp: f64,
    cooldown_reduction: f64,
    item_cooldown_reduction: f64,
    /// Distance falloff multiplier, precomputed from hero range + engagement distance.
    falloff: f64,
    bullet_lifesteal: f64,
    spirit_lifesteal: f64,
    /// item name → (current buildup %, last shot time)
    buildup_trackers: HashMap<String, (f64, f64)>,
    /// item name → next available time
    proc_cooldowns: HashMap<String, f64>,
    /// ability index → next available time
    ability_cooldowns: HashMap<usize, f64>,
}

/// Full state of a combatant: offensive + defensive.
#[derive(Debug, Clone, Default)]
struct CombatantState {
    attack: AttackerState,
    defense: TargetState,
    hero: Rc<HeroStats>,
    boons: i64,
    behaviors: Rc<Vec<ItemBehavior>>,
    // Indices into `behaviors`.
    proc_items: Rc<Vec<usize>>,
    buildup_items: Rc<Vec<usize>>,
    stack_amplifiers: Rc<Vec<usize>>,
    debuff_items: Rc<Vec<usize>>,
    pulse_items: Rc<Vec<usize>>,
    bullets_fired: i64,
    headshots: i64,
    reloads: i64,
    procs: IndexMap<String, i64>,
}

// ── Simulation output ─────────────────────────────────────────────

/// A single damage instance logged in the timeline.
#[derive(Debug, Clone, Serialize)]
pub struct DamageEntry {
    pub time: f64,
    /// "weapon", item name, ability name, "light_melee", "heavy_melee"
    pub source: Arc<str>,
    /// After resist/amp.
    pub damage: f64,
    pub damage_type: DamageType,
    /// "a" (attacker) or "b" (defender).
    pub combatant: &'static str,
    pub is_headshot: bool,
}

/// Full output of a combat simulation.
#[derive(Debug, Clone, Default, Serialize)]
pub struct SimResult {
    pub timeline: Vec<DamageEntry>,

    // Totals (attacker / combatant A perspective)
    pub total_damage: f64,
    pub total_duration: f64,
    pub overall_dps: f64,

    pub damage_by_source: IndexMap<String, f64>,
    pub dps_by_source: IndexMap<String, f64>,

    pub bullet_damage: f64,
    pub spirit_damage: f64,
    pub melee_damage: f64,

    pub bullets_fired: i64,
    pub headshots: i64,
    pub reloads: i64,
    pub procs_triggered: IndexMap<String, i64>,

    /// `None` if the target survived.
    pub kill_time: Option<f64>,
    pub target_hp_remaining: f64,

    // Bidirectional fields (`None` when unidirectional)
    pub defender_total_damage: Option<f64>,
    pub defender_dps: Option<f64>,
    pub defender_damage_by_source: Option<IndexMap<String, f64>>,
    pub defender_dps_by_source: Option<IndexMap<String, f64>>,
    pub defender_bullet_damage: Option<f64>,
    pub defender_spirit_damage: Option<f64>,
    pub defender_melee_damage: Option<f64>,
    pub defender_bullets_fired: Option<i64>,
    pub defender_headshots: Option<i64>,
    pub defender_reloads: Option<i64>,
    pub defender_procs_triggered: Option<IndexMap<String, i64>>,
    pub defender_kill_time: Option<f64>,
    pub attacker_hp_remaining: Option<f64>,
    /// "a", "b", or `None` (draw / nobody died).
    pub winner: Option<String>,
}

// ── Combat simulator ──────────────────────────────────────────────

const CID: [&str; 2] = ["a", "b"];
/// Safety cap on processed events.
const MAX_EVENTS: usize = 100_000;
/// Period of the on/off cycle used to model partial weapon uptime.
const UPTIME_CYCLE: f64 = 2.0;
/// Lowest fire rate a slowed weapon can reach (shots per second).
const MIN_FIRE_RATE: f64 = 0.1;
const MIN_ITEM_COOLDOWN: f64 = 0.5;
const MIN_ABILITY_COOLDOWN: f64 = 0.1;
/// Reload time assumed for heroes without reload data.
const DEFAULT_RELOAD: f64 = 1.0;

struct Simulator<'a> {
    config: &'a SimConfig,
    queue: EventQueue,
    timeline: Vec<DamageEntry>,
    weapon: Arc<str>,
    regen: Arc<str>,
}

/// Run a full combat simulation and return the results.
pub fn run_simulation(config: &SimConfig) -> SimResult {
    let mut sim = Simulator {
        config,
        queue: EventQueue::default(),
        timeline: Vec::new(),
        weapon: Arc::from("weapon"),
        regen: Arc::from("regen"),
    };
    let s = &config.settings;
    let mut c = [
        sim.build_combatant(&config.attacker, &config.attacker_build, s.attacker_boons),
        sim.build_combatant(&config.defender, &config.defender_build, s.defender_boons),
    ];

    sim.seed_combatant_events(0, &c[0], &config.active_schedule, &config.ability_schedule);
    if s.bidirectional {
        sim.seed_combatant_events(1, &c[1], &config.defender_active_schedule, &config.defender_ability_schedule);
    }
    if c[1].defense.hp_regen > 0.0 {
        let src = sim.regen.clone();
        sim.push(1.0, 20, 1, EventKind::RegenTick, src);
    }
    if s.bidirectional && c[0].defense.hp_regen > 0.0 {
        let src = sim.regen.clone();
        sim.push(1.0, 20, 0, EventKind::RegenTick, src);
    }
    // Initial HP pools including shields, captured before shields are consumed.
    let pool = |d: &TargetState| d.max_hp + d.bullet_shield + d.spirit_shield;
    let (a_pool, b_pool) = (pool(&c[0].defense), pool(&c[1].defense));
    sim.push(s.duration, 100, 0, EventKind::SimEnd, Arc::from("sim"));

    sim.execute(&mut c);
    sim.build_result(&c, a_pool, b_pool)
}

impl Simulator<'_> {
    fn push(&mut self, time: f64, priority: i32, combatant: usize, kind: EventKind, source: Arc<str>) {
        self.queue.push(SimEvent { time, priority, combatant, kind, source });
    }

    /// Build a full combatant state from hero + build + boons.
    fn build_combatant(&self, hero: &HeroStats, build: &Build, boons: i64) -> CombatantState {
        let s = &self.config.settings;
        let stats = aggregate_stats(build, None);

        let weapon_bonus = stats.weapon_damage_pct;
        let dmg_per_bullet = bullet_damage_at_boon(hero, boons) * effective_pellets(hero) as f64 * (1.0 + weapon_bonus);
        let fire_rate = fire_rate_with_bonus(hero, stats.fire_rate_pct);
        let mag_size = effective_magazine(hero, stats.ammo_pct, stats.ammo_flat);
        let spirit_power = (hero.spirit_gain * boons as f64 + stats.spirit_power) * (1.0 + stats.spirit_power_pct);
        let (light_melee, heavy_melee) =
            melee_damage_raw(hero, boons, weapon_bonus, stats.melee_damage_pct, stats.heavy_melee_damage_pct);

        let attack = AttackerState {
            ammo_remaining: mag_size,
            weapon_damage: dmg_per_bullet,
            fire_rate,
            magazine_size: mag_size,
            reload_time: if hero.reload_duration > 0.0 { hero.reload_duration } else { DEFAULT_RELOAD },
            light_melee_damage: light_melee,
            heavy_melee_damage: heavy_melee,
            spirit_power,
            spirit_amp: stats.spirit_amp_pct,
            cooldown_reduction: stats.cooldown_reduction,
            item_cooldown_reduction: stats.item_cooldown_reduction,
            falloff: falloff_multiplier(s.distance, hero.falloff_range_min, hero.falloff_range_max),
            bullet_lifesteal: stats.bullet_lifesteal,
            spirit_lifesteal: stats.spirit_lifesteal,
            ..Default::default()
        };

        let total_hp = hero.hp_at(boons) * (1.0 + stats.base_hp_pct) + stats.bonus_hp;
        let defense = TargetState {
            hp: total_hp,
            max_hp: total_hp,
            bullet_shield: stats.bullet_shield,
            spirit_shield: stats.spirit_shield,
            hp_regen: hero.base_regen + stats.hp_regen,
            base_bullet_resist: stats.bullet_resist_pct,
            base_spirit_resist: stats.spirit_resist_pct,
            debuffs: Vec::new(),
        };

        let mut behaviors = classify_build(build);
        let (mut procs, mut buildups, mut stackers, mut debuffers, mut pulses) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new());
        for (i, b) in behaviors.iter_mut().enumerate() {
            match b.behavior_type {
                ItemBehaviorType::ProcOnHit => procs.push(i),
                ItemBehaviorType::Buildup => {
                    // Scale the buildup rate to the hero's fire rate.
                    if let Some(&v) = s.buildup_overrides.get(&b.item_name) {
                        b.buildup_per_shot = v;
                    } else if let Some(&secs) = s.buildup_time_defaults.get(&b.item_name) {
                        if fire_rate > 0.0 {
                            let shots = fire_rate * secs;
                            if shots > 0.0 {
                                b.buildup_per_shot = 100.0 / shots;
                            }
                        }
                    }
                    buildups.push(i);
                }
                ItemBehaviorType::StackAmplifier => stackers.push(i),
                ItemBehaviorType::PulsePassive => pulses.push(i),
                _ => {}
            }
            if !b.on_hit_debuffs.is_empty() {
                debuffers.push(i);
            }
        }

        CombatantState {
            attack,
            defense,
            hero: Rc::new(hero.clone()),
            boons,
            behaviors: Rc::new(behaviors),
            proc_items: Rc::new(procs),
            buildup_items: Rc::new(buildups),
            stack_amplifiers: Rc::new(stackers),
            debuff_items: Rc::new(debuffers),
            pulse_items: Rc::new(pulses),
            ..Default::default()
        }
    }

    /// Seed weapon, pulse, active, and ability events for a combatant.
    fn seed_combatant_events(
        &mut self,
        cid: usize,
        combatant: &CombatantState,
        active_schedule: &[ActiveUse],
        ability_schedule: &[AbilityUse],
    ) {
        let weapon = self.weapon.clone();
        self.push(0.0, 0, cid, EventKind::BulletFire, weapon);

        for &i in combatant.pulse_items.iter() {
            self.push(0.0, 5, cid, EventKind::PulseTrigger, Arc::from(combatant.behaviors[i].item_name.as_str()));
        }

        // Active items: default to using every active DoT item on cooldown.
        let mut schedule = active_schedule.to_vec();
        if schedule.is_empty() {
            for b in combatant.behaviors.iter().filter(|b| b.behavior_type == ItemBehaviorType::DotActive) {
                schedule.push(ActiveUse { item_name: b.item_name.clone(), first_use: 0.5, use_on_cooldown: true });
            }
        }
        let uptime = self.config.settings.active_item_uptime;
        for u in schedule {
            let t = if uptime > 0.0 { u.first_use / uptime } else { u.first_use };
            self.push(
                t,
                3,
                cid,
                EventKind::ActiveUse { use_on_cooldown: u.use_on_cooldown },
                Arc::from(u.item_name.as_str()),
            );
        }

        // Abilities: default to casting every damaging ability on cooldown.
        let mut ab_schedule = ability_schedule.to_vec();
        if ab_schedule.is_empty() {
            for (i, ability) in combatant.hero.abilities.iter().enumerate() {
                if ability.base_damage > 0.0 && ability.cooldown > 0.0 {
                    ab_schedule.push(AbilityUse {
                        ability_index: i,
                        first_use: 0.1 * (i as f64 + 1.0),
                        use_on_cooldown: true,
                    });
                }
            }
        }
        for u in ab_schedule {
            self.push(
                u.first_use,
                4,
                cid,
                EventKind::AbilityUse { ability_index: u.ability_index, use_on_cooldown: u.use_on_cooldown },
                Arc::from(format!("ability_{}", u.ability_index).as_str()),
            );
        }
    }

    // ── Weapon firing & reload ────────────────────────────────

    /// Fire a bullet, apply damage, trigger on-hit items, schedule the next shot.
    fn handle_bullet_fire(&mut self, ev: &SimEvent, actor: &mut CombatantState, opponent: &mut CombatantState) {
        let t = ev.time;
        let cid = ev.combatant;
        let s = &self.config.settings;
        let weapon = self.weapon.clone();

        // Partial uptime: skip to the next active window.
        if s.weapon_uptime < 1.0 {
            let active_window = UPTIME_CYCLE * s.weapon_uptime;
            if (t % UPTIME_CYCLE) >= active_window {
                let next_active = t + (UPTIME_CYCLE - (t % UPTIME_CYCLE));
                self.push(next_active, 1, cid, EventKind::BulletFire, weapon);
                return;
            }
        }

        if actor.attack.ammo_remaining <= 0 {
            self.push(t, 2, cid, EventKind::ReloadStart, weapon);
            return;
        }
        actor.attack.ammo_remaining -= 1;
        actor.bullets_fired += 1;

        // Accuracy and headshots: expected-value model.
        let is_hs = s.headshot_rate > 0.0;
        let hs_mult = if is_hs { 1.0 + s.headshot_rate * (actor.hero.crit_bonus_start - 1.0) } else { 1.0 };

        let resist = opponent.defense.effective_bullet_resist(t);
        let damage_amp = opponent.defense.effective_damage_amp(t);
        let raw_dmg = actor.attack.weapon_damage * s.accuracy * hs_mult;
        let final_dmg = raw_dmg * actor.attack.falloff * (1.0 + damage_amp) * (1.0 - resist);

        if final_dmg > 0.0 {
            self.apply_damage(t, weapon.clone(), final_dmg, DamageType::Bullet, cid, actor, opponent, is_hs);
        }
        if is_hs {
            actor.headshots += 1;
        }

        self.on_bullet_hit(t, actor, opponent, cid);
        self.on_bullet_damage(t, actor, opponent);

        // Schedule the next bullet, slowed by fire-rate debuffs on the actor.
        if actor.attack.fire_rate > 0.0 {
            let slow = actor.defense.effective_fire_rate_slow(t);
            let effective_fire_rate = (actor.attack.fire_rate * (1.0 - slow)).max(MIN_FIRE_RATE);
            self.push(t + 1.0 / effective_fire_rate, 1, cid, EventKind::BulletFire, weapon);
        }
    }

    /// Begin a reload, optionally weaving a heavy melee hit.
    fn handle_reload_start(&mut self, ev: &SimEvent, actor: &mut CombatantState) {
        let t = ev.time;
        actor.reloads += 1;
        let s = &self.config.settings;
        let mut reload_extension = 0.0;
        if s.melee_after_reload {
            self.push(t + 0.1, 2, ev.combatant, EventKind::MeleeHit { heavy: true }, Arc::from("heavy_melee"));
            if s.reload_cancel_melee {
                reload_extension = HEAVY_MELEE_CYCLE;
            }
        }
        let weapon = self.weapon.clone();
        self.push(t + actor.attack.reload_time + reload_extension, 1, ev.combatant, EventKind::ReloadEnd, weapon);
    }

    /// Process on-hit effects from all proc and buildup items.
    fn on_bullet_hit(&mut self, t: f64, actor: &mut CombatantState, opponent: &mut CombatantState, cid: usize) {
        let behaviors = actor.behaviors.clone();
        for &i in actor.proc_items.clone().iter() {
            let b = &behaviors[i];
            if t < actor.attack.proc_cooldowns.get(&b.item_name).copied().unwrap_or(0.0) {
                continue;
            }
            let chance = (b.proc_chance / 100.0).min(1.0);
            if chance <= 0.0 {
                continue;
            }
            self.fire_proc(t, b, chance, actor, opponent, cid);
            actor.attack.proc_cooldowns.insert(b.item_name.clone(), t + b.proc_cooldown);
        }
        for &i in actor.buildup_items.clone().iter() {
            self.advance_buildup(t, &behaviors[i], actor, cid);
        }
    }

    /// Fire a proc item's damage (expected-value scaled by chance).
    fn fire_proc(
        &mut self,
        t: f64,
        b: &ItemBehavior,
        chance: f64,
        actor: &mut CombatantState,
        opponent: &mut CombatantState,
        cid: usize,
    ) {
        let mut base = b.proc_damage;
        if b.spirit_scale > 0.0 {
            base += b.spirit_scale * actor.attack.spirit_power;
        }
        if b.boon_scale > 0.0 {
            base += b.boon_scale * actor.boons as f64;
        }
        let scaled = base * chance;
        let name: Arc<str> = Arc::from(b.item_name.as_str());

        if b.damage_type == DamageType::Spirit {
            self.apply_spirit_damage(t, name, scaled, actor, opponent, cid);
        } else {
            let resist = opponent.defense.effective_bullet_resist(t);
            let final_dmg = scaled * (1.0 - resist);
            if final_dmg > 0.0 {
                self.apply_damage(t, name, final_dmg, DamageType::Bullet, cid, actor, opponent, false);
            }
        }
        *actor.procs.entry(b.item_name.clone()).or_insert(0) += 1;
    }

    /// Add buildup from a bullet hit; trigger the DoT at 100%.
    fn advance_buildup(&mut self, t: f64, b: &ItemBehavior, actor: &mut CombatantState, cid: usize) {
        let (mut current, last_time) = actor.attack.buildup_trackers.get(&b.item_name).copied().unwrap_or((0.0, 0.0));
        if last_time > 0.0 && (t - last_time) > b.buildup_decay_time {
            current = 0.0;
        }
        current += b.buildup_per_shot;
        if current >= 100.0 {
            current = 0.0;
            self.start_dot(t, b, cid);
        }
        actor.attack.buildup_trackers.insert(b.item_name.clone(), (current, t));
    }

    /// Start a DoT effect by scheduling its tick events.
    fn start_dot(&mut self, t: f64, b: &ItemBehavior, cid: usize) {
        if b.dot_tick_rate <= 0.0 || b.dot_duration <= 0.0 {
            return;
        }
        let num_ticks = (b.dot_duration / b.dot_tick_rate) as i64;
        let name: Arc<str> = Arc::from(b.item_name.as_str());
        for i in 0..num_ticks {
            let tick_time = t + b.dot_tick_rate * (i as f64 + 1.0);
            self.push(tick_time, 6, cid, EventKind::ItemDotTick, name.clone());
        }
    }

    /// Process a single item DoT tick.
    fn handle_item_dot_tick(&mut self, ev: &SimEvent, actor: &mut CombatantState, opponent: &mut CombatantState) {
        let behaviors = actor.behaviors.clone();
        let Some(b) = behaviors.iter().find(|b| *b.item_name == *ev.source) else { return };
        let mut base_dps = b.dot_dps;
        if b.dot_spirit_scale > 0.0 {
            base_dps += b.dot_spirit_scale * actor.attack.spirit_power;
        }
        let tick_dmg = if b.dot_is_percent_hp {
            (base_dps / 100.0) * opponent.defense.max_hp * b.dot_tick_rate
        } else {
            base_dps * b.dot_tick_rate
        };
        self.apply_spirit_damage(ev.time, ev.source.clone(), tick_dmg, actor, opponent, ev.combatant);
    }

    // ── Damage application & cross-interactions ───────────────

    /// Record damage, reduce opponent HP (shields first), apply lifesteal.
    #[allow(clippy::too_many_arguments)]
    fn apply_damage(
        &mut self,
        t: f64,
        source: Arc<str>,
        damage: f64,
        damage_type: DamageType,
        cid: usize,
        actor: &mut CombatantState,
        opponent: &mut CombatantState,
        is_headshot: bool,
    ) {
        let mut remaining = damage;
        let shield = match damage_type {
            DamageType::Bullet => Some(&mut opponent.defense.bullet_shield),
            DamageType::Spirit => Some(&mut opponent.defense.spirit_shield),
            DamageType::Melee => None,
        };
        if let Some(shield) = shield {
            if *shield > 0.0 {
                let absorbed = shield.min(remaining);
                *shield -= absorbed;
                remaining -= absorbed;
            }
        }
        opponent.defense.hp -= remaining;

        self.timeline.push(DamageEntry { time: t, source, damage, damage_type, combatant: CID[cid], is_headshot });

        let ls_rate = match damage_type {
            DamageType::Bullet | DamageType::Melee => actor.attack.bullet_lifesteal,
            DamageType::Spirit => actor.attack.spirit_lifesteal,
        };
        if ls_rate > 0.0 && remaining > 0.0 {
            let heal = remaining * ls_rate * (1.0 - actor.defense.effective_heal_reduction(t));
            if heal > 0.0 {
                actor.defense.hp = actor.defense.max_hp.min(actor.defense.hp + heal);
            }
        }
    }

    /// Apply spirit damage with all mechanic-based modifiers.
    fn apply_spirit_damage(
        &mut self,
        t: f64,
        source: Arc<str>,
        raw_damage: f64,
        actor: &mut CombatantState,
        opponent: &mut CombatantState,
        cid: usize,
    ) {
        let total_amp = actor.attack.spirit_amp + opponent.defense.effective_spirit_amp(t);
        let resist = opponent.defense.effective_spirit_resist(t);
        let damage_amp = opponent.defense.effective_damage_amp(t);
        let final_dmg = raw_damage * (1.0 + total_amp) * (1.0 + damage_amp) * (1.0 - resist);
        if final_dmg > 0.0 {
            self.apply_damage(t, source, final_dmg, DamageType::Spirit, cid, actor, opponent, false);
        }
        self.on_spirit_damage(t, actor, opponent);
    }

    /// Apply an item's on-hit debuffs, respecting its proc cooldown.
    fn apply_item_debuffs(t: f64, b: &ItemBehavior, actor: &mut CombatantState, opponent: &mut CombatantState) {
        if b.proc_cooldown > 0.0 {
            if t < actor.attack.proc_cooldowns.get(&b.item_name).copied().unwrap_or(0.0) {
                return;
            }
            actor.attack.proc_cooldowns.insert(b.item_name.clone(), t + b.proc_cooldown);
        }
        let max_stacks = if b.max_stacks > 0 { b.max_stacks } else { 1 };
        for &(debuff_type, value, duration) in &b.on_hit_debuffs {
            opponent.defense.apply_debuff(debuff_type, &b.item_name, value, duration, t, max_stacks);
        }
    }

    /// Called after any spirit damage: apply spirit-triggered stacks and debuffs.
    fn on_spirit_damage(&mut self, t: f64, actor: &mut CombatantState, opponent: &mut CombatantState) {
        let behaviors = actor.behaviors.clone();
        for &i in actor.stack_amplifiers.clone().iter() {
            let b = &behaviors[i];
            if t < actor.attack.proc_cooldowns.get(&b.item_name).copied().unwrap_or(0.0) {
                continue;
            }
            opponent.defense.apply_debuff(
                DebuffType::SpiritAmpStack,
                &b.item_name,
                b.stack_value,
                b.debuff_duration,
                t,
                b.max_stacks,
            );
            actor.attack.proc_cooldowns.insert(b.item_name.clone(), t + b.proc_cooldown);
        }
        for &i in actor.debuff_items.clone().iter() {
            Self::apply_item_debuffs(t, &behaviors[i], actor, opponent);
        }
    }

    /// Called after bullet damage: apply bullet-triggered debuffs.
    fn on_bullet_damage(&mut self, t: f64, actor: &mut CombatantState, opponent: &mut CombatantState) {
        let behaviors = actor.behaviors.clone();
        for &i in actor.debuff_items.clone().iter() {
            let b = &behaviors[i];
            if matches!(b.behavior_type, ItemBehaviorType::DebuffApplier | ItemBehaviorType::Buildup) {
                Self::apply_item_debuffs(t, b, actor, opponent);
            }
        }
    }

    // ── Active items, pulses, abilities, melee, regen ─────────

    /// Activate an active DoT item.
    fn handle_active_use(&mut self, ev: &SimEvent, use_on_cooldown: bool, actor: &mut CombatantState) {
        let behaviors = actor.behaviors.clone();
        let Some(b) = behaviors.iter().find(|b| *b.item_name == *ev.source) else { return };
        self.start_dot(ev.time, b, ev.combatant);

        let mut cd = b.active_cooldown;
        if actor.attack.item_cooldown_reduction > 0.0 {
            cd = (cd * (1.0 - actor.attack.item_cooldown_reduction)).max(MIN_ITEM_COOLDOWN);
        }
        if use_on_cooldown {
            self.push(ev.time + cd, 3, ev.combatant, ev.kind.clone(), ev.source.clone());
        }
    }

    /// Fire a pulse item (auto-damage on cooldown).
    fn handle_pulse_trigger(&mut self, ev: &SimEvent, actor: &mut CombatantState, opponent: &mut CombatantState) {
        let behaviors = actor.behaviors.clone();
        let Some(b) = behaviors.iter().find(|b| *b.item_name == *ev.source) else { return };
        let mut base = b.pulse_damage;
        if b.pulse_spirit_scale > 0.0 {
            base += b.pulse_spirit_scale * actor.attack.spirit_power;
        }
        self.apply_spirit_damage(ev.time, ev.source.clone(), base, actor, opponent, ev.combatant);
        *actor.procs.entry(b.item_name.clone()).or_insert(0) += 1;
        if b.pulse_cooldown > 0.0 {
            self.push(ev.time + b.pulse_cooldown, 5, ev.combatant, EventKind::PulseTrigger, ev.source.clone());
        }
    }

    /// Cast a hero ability.
    fn handle_ability_use(
        &mut self,
        ev: &SimEvent,
        idx: usize,
        use_on_cooldown: bool,
        actor: &mut CombatantState,
        opponent: &mut CombatantState,
    ) {
        let t = ev.time;
        let cid = ev.combatant;
        let hero = actor.hero.clone();
        let Some(ability) = hero.abilities.get(idx) else { return };
        if ability.base_damage <= 0.0 {
            return;
        }

        let next_avail = actor.attack.ability_cooldowns.get(&idx).copied().unwrap_or(0.0);
        if t < next_avail {
            if use_on_cooldown {
                self.push(next_avail, 4, cid, ev.kind.clone(), ev.source.clone());
            }
            return;
        }

        let upgrades =
            if cid == 0 { &self.config.attacker_ability_upgrades } else { &self.config.defender_ability_upgrades };
        let u = UpgradedAbility::of(ability, upgrades.get(&idx));
        let raw = u.base_damage + u.spirit_scaling * actor.attack.spirit_power;
        let name: Arc<str> = Arc::from(ability.name.as_str());

        if u.duration > 0.0 {
            // Spread the damage over one tick per second of duration.
            let num_ticks = u.duration as i64;
            let dmg_per_tick = if num_ticks > 0 { raw / num_ticks as f64 } else { raw };
            for i in 0..num_ticks {
                self.push(
                    t + (i as f64 + 1.0),
                    6,
                    cid,
                    EventKind::AbilityDotTick { damage: dmg_per_tick },
                    name.clone(),
                );
            }
        } else {
            self.apply_spirit_damage(t, name, raw, actor, opponent, cid);
        }

        let mut cd = u.cooldown;
        if actor.attack.cooldown_reduction > 0.0 {
            cd = (cd * (1.0 - actor.attack.cooldown_reduction)).max(MIN_ABILITY_COOLDOWN);
        }
        actor.attack.ability_cooldowns.insert(idx, t + cd);
        if use_on_cooldown {
            self.push(t + cd, 4, cid, ev.kind.clone(), ev.source.clone());
        }
    }

    /// Process a melee hit (light or heavy).
    fn handle_melee_hit(
        &mut self,
        ev: &SimEvent,
        heavy: bool,
        actor: &mut CombatantState,
        opponent: &mut CombatantState,
    ) {
        let raw = if heavy { actor.attack.heavy_melee_damage } else { actor.attack.light_melee_damage };
        let resist = opponent.defense.effective_bullet_resist(ev.time);
        let damage_amp = opponent.defense.effective_damage_amp(ev.time);
        let final_dmg = raw * (1.0 + damage_amp) * (1.0 - resist);
        if final_dmg > 0.0 {
            self.apply_damage(
                ev.time,
                ev.source.clone(),
                final_dmg,
                DamageType::Melee,
                ev.combatant,
                actor,
                opponent,
                false,
            );
        }
    }

    /// Heal a combatant by their regen amount (once per second).
    fn handle_regen_tick(&mut self, ev: &SimEvent, actor: &mut CombatantState) {
        let t = ev.time;
        let target = &mut actor.defense;
        if target.hp <= 0.0 {
            return;
        }
        let heal = target.hp_regen * (1.0 - target.effective_heal_reduction(t));
        target.hp = target.max_hp.min(target.hp + heal);
        target.cleanup_expired(t);
        if t + 1.0 <= self.config.settings.duration {
            self.push(t + 1.0, 20, ev.combatant, EventKind::RegenTick, ev.source.clone());
        }
    }

    // ── Main loop ─────────────────────────────────────────────

    /// Process events until the sim ends or the event cap is reached.
    fn execute(&mut self, c: &mut [CombatantState; 2]) {
        let mut processed = 0;
        while processed < MAX_EVENTS {
            let Some(ev) = self.queue.pop() else { break };
            if ev.time > self.config.settings.duration || matches!(ev.kind, EventKind::SimEnd) {
                break;
            }
            let (left, right) = c.split_at_mut(1);
            let (actor, opponent) =
                if ev.combatant == 0 { (&mut left[0], &mut right[0]) } else { (&mut right[0], &mut left[0]) };

            // Dead combatants neither act nor regenerate, and nobody attacks a corpse.
            if actor.defense.hp <= 0.0 {
                continue;
            }
            if !matches!(ev.kind, EventKind::RegenTick) && opponent.defense.hp <= 0.0 {
                continue;
            }

            match ev.kind {
                EventKind::BulletFire => self.handle_bullet_fire(&ev, actor, opponent),
                EventKind::ReloadStart => self.handle_reload_start(&ev, actor),
                EventKind::ReloadEnd => {
                    actor.attack.ammo_remaining = actor.attack.magazine_size;
                    let weapon = self.weapon.clone();
                    self.push(ev.time, 1, ev.combatant, EventKind::BulletFire, weapon);
                }
                EventKind::ItemDotTick => self.handle_item_dot_tick(&ev, actor, opponent),
                EventKind::AbilityDotTick { damage } => {
                    self.apply_spirit_damage(ev.time, ev.source.clone(), damage, actor, opponent, ev.combatant)
                }
                EventKind::ActiveUse { use_on_cooldown } => self.handle_active_use(&ev, use_on_cooldown, actor),
                EventKind::AbilityUse { ability_index, use_on_cooldown } => {
                    self.handle_ability_use(&ev, ability_index, use_on_cooldown, actor, opponent)
                }
                EventKind::MeleeHit { heavy } => self.handle_melee_hit(&ev, heavy, actor, opponent),
                EventKind::PulseTrigger => self.handle_pulse_trigger(&ev, actor, opponent),
                EventKind::RegenTick => self.handle_regen_tick(&ev, actor),
                EventKind::SimEnd => {}
            }
            processed += 1;
        }
    }

    // ── Result builder ────────────────────────────────────────

    /// Time at which a combatant's cumulative damage reached the target's initial pool.
    fn find_kill_time(&self, cid: usize, effective_hp: f64) -> Option<f64> {
        let mut running = 0.0;
        for entry in self.timeline.iter().filter(|e| e.combatant == CID[cid]) {
            running += entry.damage;
            if running >= effective_hp {
                return Some(entry.time);
            }
        }
        None
    }

    fn build_result(self, c: &[CombatantState; 2], a_pool: f64, b_pool: f64) -> SimResult {
        let bidirectional = self.config.settings.bidirectional;
        let a_kill = self.find_kill_time(0, b_pool);
        let b_kill = if bidirectional { self.find_kill_time(1, a_pool) } else { None };

        // Effective duration: first death, or the configured duration.
        let mut first_death = self.config.settings.duration;
        for k in [a_kill, b_kill].into_iter().flatten() {
            first_death = first_death.min(k);
        }
        let duration = first_death.max(0.01);

        let winner = match (a_kill, b_kill) {
            _ if !bidirectional => None,
            (Some(a), b) if b.is_none_or(|b| a <= b) => Some("a".to_string()),
            (_, Some(_)) => Some("b".to_string()),
            _ => None,
        };

        let a = SideTotals::of(&self.timeline, CID[0], duration);
        let mut result = SimResult {
            total_damage: a.total,
            total_duration: duration,
            overall_dps: a.total / duration,
            damage_by_source: a.by_source,
            dps_by_source: a.dps_by_source,
            bullet_damage: a.bullet,
            spirit_damage: a.spirit,
            melee_damage: a.melee,
            bullets_fired: c[0].bullets_fired,
            headshots: c[0].headshots,
            reloads: c[0].reloads,
            procs_triggered: c[0].procs.clone(),
            kill_time: a_kill,
            target_hp_remaining: c[1].defense.hp.max(0.0),
            ..Default::default()
        };

        if bidirectional {
            let b = SideTotals::of(&self.timeline, CID[1], duration);
            result.defender_total_damage = Some(b.total);
            result.defender_dps = Some(b.total / duration);
            result.defender_damage_by_source = Some(b.by_source);
            result.defender_dps_by_source = Some(b.dps_by_source);
            result.defender_bullet_damage = Some(b.bullet);
            result.defender_spirit_damage = Some(b.spirit);
            result.defender_melee_damage = Some(b.melee);
            result.defender_bullets_fired = Some(c[1].bullets_fired);
            result.defender_headshots = Some(c[1].headshots);
            result.defender_reloads = Some(c[1].reloads);
            result.defender_procs_triggered = Some(c[1].procs.clone());
            result.defender_kill_time = b_kill;
            result.attacker_hp_remaining = Some(c[0].defense.hp.max(0.0));
            result.winner = winner;
        }
        result.timeline = self.timeline;
        result
    }
}

/// Aggregated timeline totals for one combatant.
struct SideTotals {
    total: f64,
    bullet: f64,
    spirit: f64,
    melee: f64,
    by_source: IndexMap<String, f64>,
    dps_by_source: IndexMap<String, f64>,
}

impl SideTotals {
    fn of(timeline: &[DamageEntry], cid: &str, duration: f64) -> SideTotals {
        let mut t = SideTotals {
            total: 0.0,
            bullet: 0.0,
            spirit: 0.0,
            melee: 0.0,
            by_source: IndexMap::new(),
            dps_by_source: IndexMap::new(),
        };
        for e in timeline.iter().filter(|e| e.combatant == cid) {
            t.total += e.damage;
            match t.by_source.get_mut(&*e.source) {
                Some(v) => *v += e.damage,
                None => {
                    t.by_source.insert(e.source.to_string(), e.damage);
                }
            }
            match e.damage_type {
                DamageType::Bullet => t.bullet += e.damage,
                DamageType::Spirit => t.spirit += e.damage,
                DamageType::Melee => t.melee += e.damage,
            }
        }
        t.dps_by_source = t.by_source.iter().map(|(k, v)| (k.clone(), v / duration)).collect();
        t
    }
}

/// Convert `{index: [tiers]}` with string keys (as JSON delivers it) into [`AbilityUpgrades`].
pub fn upgrades_from_json(v: &Value) -> AbilityUpgrades {
    let mut out = BTreeMap::new();
    if let Some(obj) = v.as_object() {
        for (k, tiers) in obj {
            if let (Ok(idx), Some(list)) = (k.parse::<usize>(), tiers.as_array()) {
                out.insert(idx, list.iter().filter_map(Value::as_i64).collect());
            }
        }
    }
    out
}
