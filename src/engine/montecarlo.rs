//! Monte Carlo time-to-kill: roll every shot for hit and headshot instead of
//! using expected values, to show how much a duel can swing.

use serde::Serialize;

use crate::models::{CombatConfig, HeroStats};

use super::damage::calculate_bullet;
use super::heroes::ttk;
use super::primitives::falloff_multiplier;

/// xoshiro256** seeded through SplitMix64: small, fast and reproducible.
#[derive(Debug, Clone)]
pub struct Rng([u64; 4]);

impl Rng {
    pub fn new(seed: u64) -> Self {
        let mut z = seed;
        let mut next = || {
            z = z.wrapping_add(0x9E37_79B9_7F4A_7C15);
            let mut x = z;
            x = (x ^ (x >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
            x = (x ^ (x >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
            x ^ (x >> 31)
        };
        Rng([next(), next(), next(), next()])
    }

    pub fn next_u64(&mut self) -> u64 {
        let s = &mut self.0;
        let result = s[1].wrapping_mul(5).rotate_left(7).wrapping_mul(9);
        let t = s[1] << 17;
        s[2] ^= s[0];
        s[3] ^= s[1];
        s[1] ^= s[2];
        s[0] ^= s[3];
        s[2] ^= t;
        s[3] = s[3].rotate_left(45);
        result
    }

    /// Uniform float in [0, 1).
    pub fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }
}

/// Monte Carlo run settings.
#[derive(Debug, Clone)]
pub struct MonteCarloParams {
    pub trials: usize,
    pub seed: u64,
    /// Trials that have not killed by this time count as failures.
    pub max_time: f64,
}

impl Default for MonteCarloParams {
    fn default() -> Self {
        MonteCarloParams { trials: 2000, seed: 0x0000_DEAD_10C5, max_time: 180.0 }
    }
}

/// Distribution of kill times across trials.
#[derive(Debug, Clone, Serialize)]
pub struct TtkDistribution {
    pub trials: usize,
    /// Trials that killed the target within the time limit.
    pub kills: usize,
    pub kill_rate: f64,
    /// Share of trials that killed without reloading.
    pub one_mag_rate: f64,
    pub mean: f64,
    pub std_dev: f64,
    pub min: f64,
    pub p10: f64,
    pub median: f64,
    pub p90: f64,
    pub max: f64,
    /// Kill time from the expected-value model, for reference.
    pub expected: f64,
    pub target_hp: f64,
    /// `(bucket start in seconds, trials)` over the kill times.
    pub histogram: Vec<(f64, usize)>,
}

const HISTOGRAM_BUCKETS: usize = 24;

fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let rank = p * (sorted.len() - 1) as f64;
    let lo = rank.floor() as usize;
    let hi = rank.ceil() as usize;
    sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo as f64)
}

/// Simulate `params.trials` gun duels with per-shot hit and headshot rolls.
///
/// Each shot is one roll (all pellets hit or miss together) and a reload
/// follows every emptied magazine.
pub fn monte_carlo_ttk(
    attacker: &HeroStats,
    defender: &HeroStats,
    config: &CombatConfig,
    params: &MonteCarloParams,
) -> TtkDistribution {
    let bullet = calculate_bullet(attacker, config);
    let reference = ttk(attacker, defender, config);
    let falloff = falloff_multiplier(config.distance, attacker.falloff_range_min, attacker.falloff_range_max);
    let body =
        bullet.damage_per_bullet * falloff * (1.0 + config.target_bullet_damage_amp) * (1.0 - bullet.final_resist);
    let head = body * config.headshot_multiplier;
    let target_hp = reference.target_hp;
    let interval = if bullet.bullets_per_second > 0.0 { 1.0 / bullet.bullets_per_second } else { 0.0 };
    let can_fire = body > 0.0 && interval > 0.0 && bullet.magazine_size > 0 && target_hp > 0.0;

    let mut rng = Rng::new(params.seed);
    let mut times: Vec<f64> = Vec::with_capacity(params.trials);
    let mut one_mag = 0usize;
    if can_fire {
        for _ in 0..params.trials {
            let mut hp = target_hp;
            let mut t = 0.0;
            let mut ammo = bullet.magazine_size;
            let mut reloaded = false;
            // Same timing convention as the expected-value TTK: the n-th shot lands at n × interval.
            while t <= params.max_time {
                t += interval;
                if rng.next_f64() < config.accuracy {
                    hp -= if rng.next_f64() < config.headshot_rate { head } else { body };
                    if hp <= 0.0 {
                        times.push(t);
                        one_mag += usize::from(!reloaded);
                        break;
                    }
                }
                ammo -= 1;
                if ammo == 0 {
                    ammo = bullet.magazine_size;
                    reloaded = true;
                    t += bullet.reload_time;
                }
            }
        }
    }

    times.sort_by(f64::total_cmp);
    let kills = times.len();
    let mean = if kills > 0 { times.iter().sum::<f64>() / kills as f64 } else { 0.0 };
    let variance =
        if kills > 1 { times.iter().map(|t| (t - mean).powi(2)).sum::<f64>() / (kills - 1) as f64 } else { 0.0 };
    let (min, max) = (times.first().copied().unwrap_or(0.0), times.last().copied().unwrap_or(0.0));

    let mut histogram = Vec::new();
    if kills > 0 {
        let width = ((max - min) / HISTOGRAM_BUCKETS as f64).max(1e-9);
        let mut counts = vec![0usize; HISTOGRAM_BUCKETS];
        for t in &times {
            let i = (((t - min) / width) as usize).min(HISTOGRAM_BUCKETS - 1);
            counts[i] += 1;
        }
        histogram = counts.into_iter().enumerate().map(|(i, c)| (min + i as f64 * width, c)).collect();
    }

    let trials = params.trials.max(1) as f64;
    TtkDistribution {
        trials: params.trials,
        kills,
        kill_rate: kills as f64 / trials,
        one_mag_rate: one_mag as f64 / trials,
        mean,
        std_dev: variance.sqrt(),
        min,
        p10: percentile(&times, 0.10),
        median: percentile(&times, 0.50),
        p90: percentile(&times, 0.90),
        max,
        expected: reference.realistic_ttk,
        target_hp,
        histogram,
    }
}
