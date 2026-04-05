# TODO: Simulation & Missing Mechanics Gaps

Mechanics documented on the Deadlock wiki that are **not implemented** in the simulation engine.
Organized by priority for combat simulation accuracy.

---

## HIGH PRIORITY — Affects Core Damage Accuracy

### ~~TODO-SIM1: Lifesteal Not Applied~~ — DEFERRED
- **Status**: DEFERRED — Attacker has no HP in current one-directional model.
  Lifesteal has no effect until bidirectional combat is implemented.

### ~~TODO-SIM2: Spirit Shield Absorption Not Functional~~ ✅ ALREADY IMPLEMENTED
- **Status**: RESOLVED — `_apply_damage` already absorbs spirit damage via `spirit_shield`
  (lines 987-989). Original assessment was incorrect.

### ~~TODO-SIM3: Melee 50% Weapon Damage Scaling in Simulation~~ ✅ FIXED
- **Status**: RESOLVED — Simulation now uses `DamageCalculator.MELEE_WEAPON_SCALE` (0.5)
  for melee weapon bonus calculation.

### ~~TODO-SIM4: Resistance Stacking Should Be Multiplicative~~ ✅ FIXED
- **Status**: RESOLVED — `BuildEngine.aggregate_stats` now uses multiplicative resist stacking.
  Simulation inherits correct values via build stats.

---

## MEDIUM PRIORITY — Missing Combat Mechanics

### ~~TODO-SIM5: Damage Falloff Over Distance~~ ✅ FIXED
- **Status**: RESOLVED — Added `distance` field to `SimSettings` (default=20). Falloff
  multiplier precomputed during `_initialize` from hero's `falloff_range_min`/`max`
  and applied in `_handle_bullet_fire`. Shares `falloff_multiplier` primitive with
  `DamageCalculator.calculate_bullet` (TODO-W3).

### ~~TODO-SIM6: Parry System Not Modeled~~ — CLOSED
- **Status**: CLOSED — Out of scope. Parry is player-skill-dependent and cannot be
  meaningfully modeled in a DPS/TTK simulator without arbitrary assumptions.

### ~~TODO-SIM7: Reload Cancellation via Melee/Abilities~~ ✅ FIXED
- **Status**: RESOLVED — Added `reload_cancel_melee` flag to `SimSettings` (default=False).
  When enabled, melee during reload extends reload time by `HEAVY_MELEE_CYCLE` (1.0s)
  to model the animation freezing the reload timer.

### ~~TODO-SIM8: Fire Rate Slow Debuff Not Applied to Defender~~ — CLOSED
- **Status**: CLOSED — Blocked on bidirectional combat. Defender doesn't attack in
  the current one-directional model, so fire rate slow has no effect to apply.

### ~~TODO-SIM9: Attacker Healing/Regen Not Modeled~~ — CLOSED
- **Status**: CLOSED — Blocked on bidirectional combat. Attacker has no HP tracking
  in the current one-directional model. Revisit alongside SIM1 if bidirectional is implemented.

---

## LOW PRIORITY — Edge Cases & Advanced Mechanics

### ~~TODO-SIM10: Projectile Travel Time~~ — CLOSED
- **Status**: CLOSED — Out of scope. Minimal impact for 1v1 DPS/TTK simulation.

### ~~TODO-SIM11: Movement / Positioning~~ — CLOSED
- **Status**: CLOSED — Out of scope for a stationary 1v1 DPS/TTK simulator.

### ~~TODO-SIM12: Enemy Defensive Abilities / Counterattack~~ — CLOSED
- **Status**: CLOSED — Blocked on bidirectional combat. Revisit alongside SIM1.

### ~~TODO-SIM13: Ability Interaction Chains~~ — CLOSED
- **Status**: CLOSED — Out of scope. Would require AI/combo logic beyond DPS/TTK simulation.

### ~~TODO-SIM14: Consumables / Temporary Buffs~~ — CLOSED
- **Status**: CLOSED — Out of scope for build/item-focused DPS simulation.

### ~~TODO-SIM15: Multi-Target / Team Combat~~ — CLOSED
- **Status**: CLOSED — Out of scope. Simulator is designed for 1v1 analysis.

### ~~TODO-SIM16: Crit Bonus Scale Per Hero~~ ✅ FIXED
- **Status**: RESOLVED — `crit_bonus_start` added to `HeroStats` with wiki-accurate overrides.
  Builds pass hero-specific headshot multiplier through `evaluate_build` and `build_to_attacker_config`.

---

## SUMMARY

| Priority | Count | Status                           |
|----------|-------|----------------------------------|
| HIGH     | 4     | All resolved/deferred            |
| MEDIUM   | 5     | All closed/fixed                 |
| LOW      | 7     | 1 fixed, 6 closed               |

### Remaining Open Items
1. **TODO-SIM1** (lifesteal) — deferred, needs bidirectional combat
