# TODO: Engine Calculation Discrepancies

Discrepancies between Deadlock wiki game mechanics and the DeadlockSim engine implementation.
Each item includes the wiki source, codebase location, and severity.

---

## DATA / CONSTANTS

### ~~TODO-D1: Shop Tier Weapon Damage Bonuses Diverge at 4800+ Souls~~ ✅ FIXED
- **Status**: RESOLVED — Updated `_SHOP_TIER_DATA` weapon column to match wiki values.

### ~~TODO-D2: Spirit Shop Tier Bonuses May Be Outdated~~ ✅ FIXED
- **Status**: RESOLVED — Verified all spirit tier values in-game. Updated `_SHOP_TIER_DATA`
  spirit column for tiers 4800+ (38, 48, 57, 66, 75, 100).

### ~~TODO-D3: Vitality Shop Tier Bonuses Need Verification~~ ✅ FIXED
- **Status**: RESOLVED — Verified all vitality tier values in-game. Updated `_SHOP_TIER_DATA`
  vitality column for tiers 4800+ (34, 39, 44, 48, 52, 56). Weapon values confirmed correct.

---

## WEAPON / BULLET DAMAGE

### ~~TODO-W1: Flat Weapon Damage Not Distinguished from % Weapon Damage~~ ✅ FIXED
- **Status**: RESOLVED — Added `flat_weapon_bonus` field to `CombatConfig`. Formula updated:
  `damage_per_bullet = (scaled_dmg * (1 + weapon_damage_bonus) + flat_bonus) * pellets`
  ```
- **Affected Heroes**: Grey Talon (+4 from Rain of Arrows), Haze (+0.2/stack Fixation), Lash (+6, T2 Grapple), Pocket (+7, T3 Flying Cloak), Yamato (+6, T3 Flying Slash), Abrams (+1.5, T3 Shoulder Charge)

### ~~TODO-W2: Crit Multiplier Formula Missing Crit Bonus Scale~~ ✅ FIXED
- **Status**: RESOLVED — Added `crit_bonus_start` field to `HeroStats` (parsed from weapon data).
  Added `_CRIT_BONUS_OVERRIDES` hardcoded table for 7 heroes with reduced crit + Graves (no crit).
  Updated `CombatConfig.headshot_multiplier` default to 1.65. `build_to_attacker_config` now
  accepts and passes `headshot_multiplier` from hero data.

### ~~TODO-W3: Damage Falloff Not Implemented~~ ✅ FIXED
- **Status**: RESOLVED — Added `falloff_multiplier` primitive function in `primitives.py`.
  Added `distance` field to `CombatConfig` (default=20) and `SimSettings` (default=20).
  Linear falloff from 100% to 10% applied in `calculate_bullet` and simulation
  `_handle_bullet_fire` using hero's `falloff_range_min`/`falloff_range_max`.

### ~~TODO-W4: Golden Statue Weapon Damage Bonus Not Modeled~~ ✅ FIXED
- **Status**: RESOLVED — Added `golden_buffs_count` (default=0) to `CombatConfig` with
  even-split assumption across weapon/spirit/vitality. Also added per-type total overrides:
  `golden_weapon_total`, `golden_spirit_total`, `golden_vitality_total`. Applied in
  `calculate_bullet` weapon damage bonus calculation.

### ~~TODO-W5: Increased Bullet Damage Debuffs Not Modeled in Static Calcs~~ ✅ FIXED
- **Status**: RESOLVED — Added `target_bullet_damage_amp` (default=0) to `CombatConfig`.
  Applied as a multiplier in `calculate_bullet`: `final_dps = raw * falloff * (1 + amp) * (1 - resist)`.
  Exposed for settings page what-if scenarios.

### ~~TODO-W6: Conditional Item Modifiers Not Modeled~~ ✅ FIXED
- **Status**: RESOLVED — Added configurable fields to `CombatConfig`:
  `berserker_stacks` (0-10, +7%/stack), `intensifying_mag_pct` (0-0.45),
  `opening_rounds_active` (+45%), `close_range_active` (+50%), `long_range_active` (+70%).
  All applied in `calculate_bullet` as additive weapon damage bonuses.

---

## MELEE DAMAGE

### ~~TODO-M1: Melee Damage Uses 100% Weapon Damage Instead of 50%~~ ✅ FIXED
- **Status**: RESOLVED — Added `MELEE_WEAPON_SCALE = 0.5` constant. Both `damage.py` and
  `simulation.py` now apply `weapon_damage_bonus * 0.5` for melee calculations.

### ~~TODO-M2: Heavy Melee Cycle Time Incorrect~~ ✅ FIXED
- **Status**: RESOLVED — Updated `HEAVY_MELEE_CYCLE` from 1.1s to 1.0s (wiki: hit scenario).

### ~~TODO-M3: Bonus Melee Damage % Items Not Modeled~~ ✅ FIXED
- **Status**: RESOLVED — Added `melee_damage_pct` and `heavy_melee_damage_pct` fields to
  `Item` and `BuildStats` models. Parsed from API properties `BonusMeleeDamagePercent` and
  `BonusHeavyMeleeDamage`. Aggregated in `BuildEngine.aggregate_stats`. Applied in both
  `DamageCalculator.calculate_melee` and simulation `_initialize` melee calculations.

### ~~TODO-M4: Melee-Scaling Abilities Not Implemented~~ ✅ FIXED
- **Status**: RESOLVED — Added `melee_scale` field to `HeroAbility` model. Parsed from API
  properties `LightMeleeScalePct`, `LightMeleeScale`, and `CountsAsLightMelee`.
  `hero_total_spirit_dps` now computes melee-based damage for abilities with `melee_scale > 0`,
  using the hero's light melee damage scaled by boons, weapon bonus, and item melee bonuses.

---

## SPIRIT DAMAGE

### ~~TODO-S1: Resistance Stacking Model May Differ from Wiki~~ ✅ VERIFIED
- **Status**: RESOLVED — Confirmed in-game: 30% + 10% resist = 37% (multiplicative).
  Code already uses multiplicative stacking since B1 fix.

### ~~TODO-S2: Cooldown Reduction Minimum May Differ~~ — CLOSED
- **Status**: CLOSED — Current minimums (0.1s abilities, 0.5s items) are unreachable
  in practice and verified as reasonable.

---

## TTK / DPS

### ~~TODO-T1: Reload Integration Missing from Realistic TTK~~ ✅ FIXED
- **Status**: RESOLVED — `HeroMetrics.ttk()` now simulates step-by-step magazine/reload
  cycles. Fires bullets individually, tracks HP depletion, and adds reload time between
  magazines to find exact kill time.

---

## BUILDS / OPTIMIZER

### ~~TODO-B1: Build Stat Aggregation Stacks Resist Additively~~ ✅ FIXED
- **Status**: RESOLVED — `aggregate_stats` now uses multiplicative stacking:
  `total_resist = 1 - (1-R1)(1-R2)...` Example: 20% + 30% → 44% (not 50%).

### ~~TODO-B2: Optimizer Does Not Consider Item Synergies~~ — CLOSED
- **Status**: CLOSED — Known limitation. Greedy optimizer evaluates items independently.
  True synergy evaluation requires combinatorial search which is prohibitively complex.
  Documented as a heuristic, not a global optimizer.
