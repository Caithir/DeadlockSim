# Feature Specification: In-Game Verified Test Suite

**Feature Branch**: `012-game-verified-tests`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Game-Pinned Value Tests (Priority: P1)

As a developer maintaining calculation accuracy, I want a suite of tests with hardcoded values manually verified in the live Deadlock sandbox so that any engine regression or API data drift is immediately caught.

**Why this priority**: Game-verified values are the ultimate source of truth — if the engine disagrees with the live game, the engine is wrong.

**Independent Test**: Run `pytest tests/test_engine.py::TestGameVerified -v` — all 27+ tests pass against current API data.

**Acceptance Scenarios**:

1. **Given** hero "Haze" in sandbox at boon 0, **When** shooting the target dummy at point blank, **Then** per-bullet damage rounds to 5 (matching `test_base_bullet_single_pellet`).
2. **Given** hero "Abrams" at boon 0, **When** shooting at point blank, **Then** per-shot damage = `ceil(3.6 × 9) = 33` (matching `test_base_bullet_multi_pellet`).
3. **Given** hero "Haze" landing a headshot, **When** at boon 0, **Then** damage = `round(5.26 × 1.65) = 9` (matching `test_headshot_damage`).
4. **Given** hero "Wraith" at boon 0, **When** emptying full magazine, **Then** total damage = `round(5.64 × 52) = 293` (matching `test_full_magazine_damage`).

---

### User Story 2 - Weapon Archetype Reload Tests (Priority: P1)

As a developer, I want fire-and-reload cycle tests for every weapon archetype (fast auto, burst, shotgun, sniper, spray, large mag, semi-auto) so that the simulation's magazine/reload timing exactly matches step-by-step manual calculation.

**Why this priority**: Reload timing errors compound over long simulations and produce systematically wrong DPS.

**Independent Test**: Run `pytest tests/test_engine.py::TestSimReloadDamage -v` — all parametrized hero tests pass.

**Acceptance Scenarios**:

1. **Given** Venator shooting a dummy for 3 seconds at 100% accuracy, **When** simulation runs, **Then** exactly 24 bullets fire with no reloads and total damage = `24 × 8.0 = 192.0`.
2. **Given** Venator for 10 seconds, **When** simulated, **Then** 58 bullets fire across 1 reload cycle.
3. **Given** any hero for exactly 2 full mag+reload cycles, **When** sustained DPS is measured, **Then** it matches `(2 × mag_damage) / (2 × cycle_time)` within 1%.

---

### User Story 3 - Two-Magazine Sustained DPS Across Archetypes (Priority: P1)

As a developer, I want parametrized sustained DPS tests for 10 weapon archetypes to verify sim-to-analytical consistency so that every hero weapon type is covered.

**Why this priority**: Different weapon types (burst, shotgun, spray, sniper) have different timing edge cases.

**Independent Test**: Run `pytest tests/test_engine.py::TestSimReloadDamage::test_two_mag_sustained_dps -v` — all 10 heroes pass.

**Acceptance Scenarios**:

| Hero | Archetype | Expected Sustained DPS |
|------|-----------|----------------------|
| Venator | Fast auto | 37.94 |
| Seven | Burst fire | 31.47 |
| Abrams | Spread shotgun (9 pellets) | 48.42 |
| Drifter | Tight shotgun (1 per target) | 30.25 |
| Grey Talon | Slow sniper | 32.85 |
| Vyper | Fastest spray (14.29 rps) | 48.15 |
| McGinnis | Huge magazine (66 rounds) | 23.86 |
| Silver | Fast reload shotgun | 40.83 |
| Paige | Semi-auto heavy | 51.58 |
| Yamato | Multi-pellet slash (5 pellets) | 42.57 |

---

### User Story 4 - Boon Scaling Verification (Priority: P1)

As a developer, I want specific boon-level stat checks verified in sandbox so that the `base + (gain × boons)` formula is confirmed at multiple checkpoints.

**Why this priority**: Scaling correctness affects every downstream calculation.

**Independent Test**: Run `pytest tests/test_engine.py::TestGameVerified::test_boon_scaling_abrams -v` and `test_haze_boon_20`.

**Acceptance Scenarios**:

1. **Given** Abrams at boon 9 (~6000 souls), **When** per-shot damage measured, **Then** = `ceil((base + gain×9) × 9_pellets) = 41`. HP = 1368.
2. **Given** Haze at boon 20 (~21600 souls), **When** bullet damage checked, **Then** = `round(base + gain×20) = 8`. HP = 1640.

---

### User Story 5 - Ability Damage Verification (Priority: P1)

As a developer, I want base ability damage values verified in sandbox across multiple heroes so that the API→parser→engine pipeline is confirmed end-to-end.

**Why this priority**: Ability parsing errors silently corrupt spirit DPS calculations.

**Independent Test**: Run `pytest tests/test_engine.py::TestGameVerified::test_instant_ability_base_damage -v` and `test_cross_hero_instant_abilities`.

**Acceptance Scenarios**:

1. **Given** Infernus Concussive Combustion at 0 spirit, **When** used on dummy, **Then** deals 125 damage.
2. **Given** Seven Static Charge at 0 spirit, **When** used on dummy, **Then** deals 35 damage.
3. **Given** Infernus CC with T1 upgrade (+100), **When** used, **Then** deals 225 damage.
4. **Given** Infernus Flame Dash (DPS ability), **When** 17 spirit equipped, **Then** tooltip DPS = 47 = `(90 + 3.0×17) / 3`.

---

### User Story 6 - Item Effect Verification (Priority: P1)

As a developer, I want item stat effects verified in sandbox (shop tier bonuses, resist stacking, magazine rounding, fire rate) so that build calculations match the game.

**Why this priority**: Item stat mismatches directly cause wrong build evaluations.

**Independent Test**: Run `pytest tests/test_engine.py::TestGameVerified::test_spirit_shop_tier_bonus -v` through `test_fire_rate_with_item`.

**Acceptance Scenarios**:

1. **Given** Extra Spirit (800 cost), **When** equipped, **Then** total spirit = 17 (10 base + 7 tier). Haze Sleep Dagger = 109 damage.
2. **Given** Headshot Booster (800 cost, 0% weapon), **When** equipped, **Then** +7% weapon from shop tier.
3. **Given** Battle Vest (18%) + Bullet Resilience (30%), **When** both equipped, **Then** combined resist = `1 - (0.82)(0.70) = 43%` (multiplicative).
4. **Given** Haze + Extended Magazine (30%), **When** equipped, **Then** ammo = `ceil(25 × 1.30) = 33`.
5. **Given** Haze + Rapid Rounds, **When** equipped, **Then** fire rate ≈ 10.4 rps.

---

### User Story 7 - Spirit Scaling with Items (Priority: P1)

As a developer, I want ability damage with spirit items verified across heroes so that the full `base + scaling × spirit` pipeline is confirmed.

**Why this priority**: Spirit power aggregation (items + shop tier + boon gain) has multiple sources that must combine correctly.

**Independent Test**: Run `pytest tests/test_engine.py::TestGameVerified::test_spirit_scaling_with_items -v`.

**Acceptance Scenarios**:

1. **Given** Improved Spirit (29 total spirit after tier), **When** Haze Sleep Dagger used, **Then** damage = `round(65 + 2.6 × 29) = 140`.
2. **Given** Improved Spirit on Infernus CC, **When** used, **Then** = `round(125 + 0.975 × 29) = 153`.
3. **Given** Improved Spirit on Infernus Napalm, **When** used, **Then** = `round(40 + 0.6 × 29) = 57`.

---

### User Story 8 - Damage Mechanic Edge Cases (Priority: P2)

As a developer, I want tests covering special mechanic interactions (display rounding, non-standard DPS abilities, per-target pellet caps, stacking damage amp patterns) so that edge cases don't silently produce wrong results.

**Why this priority**: Edge cases are where bugs hide — these represent mechanics that are easy to model incorrectly.

**Independent Test**: Run `pytest tests/test_engine.py::TestGameVerified::test_damage_display_rounding_not_actual -v` through `test_other_shotguns_hit_all_pellets`.

**Acceptance Scenarios**:

1. **Given** Mo & Krill (2.82 × 4 pellets = 11.28), **When** viewing damage, **Then** game displays 11 but actual fractional damage is 11.28 (engine uses exact, not rounded).
2. **Given** Paradox Pulse Grenade (35/hit, +4% amp/stack, 4 pulses), **When** all pulses land, **Then** total = `round(35 + 36.4 + 37.8 + 39.2) = 148`.
3. **Given** Drifter (3 pellets, max 1 per target), **When** shooting single target, **Then** only 1 pellet hits, DPS ≈ 44.2.
4. **Given** other shotgun heroes (Abrams, Yamato, Silver, Pocket), **When** shooting single target, **Then** all pellets hit (no per-target cap).

---

### User Story 9 - Damage Outlier / Sanity Bounds (Priority: P2)

As a developer, I want exploratory tests that define plausible damage bounds for extreme scenarios (max amp stacks, combined shred, full EHP) so that formula errors producing 10× damage are caught before release.

**Why this priority**: Guards against catastrophic formula bugs that produce absurd results.

**Independent Test**: Run `pytest tests/test_engine.py::TestDamageOutliers -v`.

**Acceptance Scenarios**:

1. **Given** 20% spirit amp on 100 base damage, **When** calculated, **Then** = 120 (amp). **Not** the same as 20% resist shred on 40% resist target.
2. **Given** resist shred on 0% resist target, **When** calculated, **Then** no effect (damage unchanged).
3. **Given** EE stacks (+spirit amp) on item, **When** classified for sim, **Then** behavior includes both `stack_amplifier` (spirit amp stacks) AND `spirit_resist_shred` debuff as separate mechanics.
4. **Given** max stacked scenario (200 base × 1.70 amp × 1.40 dmg_amp × 0.88 resist), **When** calculated, **Then** = 418 damage.

---

### User Story 10 - Data Sanity Checks (Priority: P2)

As a developer, I want sanity checks on loaded API data (all heroes have positive stats, all items have costs, hero DPS matches formula) so that data parsing regressions are caught immediately.

**Why this priority**: Bad data silently corrupts all calculations.

**Independent Test**: Run `pytest tests/test_engine.py::TestDataSanity -v`.

**Acceptance Scenarios**:

1. **Given** data loaded, **When** checked, **Then** ≥ 20 heroes and ≥ 50 items load.
2. **Given** every hero, **When** checked, **Then** base_hp > 0, damage_gain ≥ 0, hp_gain > 0, 1.0 ≤ crit_bonus_start ≤ 2.0.
3. **Given** every item, **When** checked, **Then** cost > 0 and category ∈ {weapon, vitality, spirit}.
4. **Given** every hero, **When** base_dps checked, **Then** ≈ `base_bullet × pellets × fire_rate` within 15%.

---

### Edge Cases

- What happens when a game patch changes a hero's base damage? Tests must be re-verified in sandbox and updated.
- How does the system handle API data that diverges from live game (API staleness)? Tests document known divergences (e.g., Afterburn DPS: API=12, game=14).
- What if a hero is reworked and abilities are reordered? Index-based tests (e.g., `abilities[0]`) must be updated.

## Requirements

### Functional Requirements

- **FR-001**: System MUST include tests with hardcoded values verified in the live Deadlock sandbox.
- **FR-002**: Each game-verified test MUST document the exact in-game verification procedure.
- **FR-003**: Tests MUST cover all weapon archetypes: fast auto, burst, shotgun (spread + tight), sniper, spray, large magazine, semi-auto, multi-pellet slash.
- **FR-004**: Tests MUST verify base bullet damage, headshot multiplier, full magazine damage, boon scaling, melee damage, and base HP for multiple heroes.
- **FR-005**: Tests MUST verify ability base damage, T1 upgrades, spirit scaling with items, and DPS-over-time ability parsing.
- **FR-006**: Tests MUST verify shop tier bonuses (weapon %, spirit power, HP %), resist stacking (multiplicative), magazine ceiling rounding, and fire rate with items.
- **FR-007**: Tests MUST verify that spirit amp and resist shred are correctly modeled as independent mechanics.
- **FR-008**: Tests MUST verify special mechanics: display rounding vs actual, Drifter per-target pellet cap, Paradox stacking damage amp, non-standard DPS keys.
- **FR-009**: Tests MUST include data sanity checks on all loaded heroes and items.
- **FR-010**: Tests MUST include simulation reload timing verification with step-by-step manual bullet counting.
- **FR-011**: Tests MUST verify sim sustained DPS converges to analytical sustained DPS within 5% over 30-second durations.
- **FR-012**: When a test fails after data refresh, the failure message MUST guide the developer to re-verify in sandbox.

### Key Entities

- **TestGameVerified (class)**: 27+ tests with sandbox-pinned values covering bullets, abilities, items, scaling, and special mechanics.
- **TestSimReloadDamage (class)**: 12+ tests verifying fire/reload timing for Venator, Seven, Abrams, Wraith across different durations.
- **TestDamageOutliers (class)**: Exploratory tests defining plausible bounds and verifying mechanic independence.
- **TestDataSanity (class)**: Structural checks on loaded API data.

## Success Criteria

- **SC-001**: All game-verified tests pass against current API data without modification.
- **SC-002**: When a game patch changes a value, exactly one test fails with a clear message indicating which value to re-verify.
- **SC-003**: Sustained DPS tests for all 10 weapon archetypes match analytical engine within 1%.
- **SC-004**: Sim bullet counts match manual step-by-step fire/reload counting exactly.
- **SC-005**: Documentation per test is sufficient for a new developer to reproduce the in-game verification in under 5 minutes.

## Assumptions

- Deadlock sandbox mode is available for verification with controllable boon levels and target dummies.
- API data may lag behind live game patches; known divergences are documented in test comments.
- Game rounds display numbers but deals exact fractional damage internally.

## Mechanics Documentation

Supporting mechanic documentation in `docs/mechanics/`:
- [weapon_damage.md](../../docs/mechanics/weapon_damage.md) — Full damage formula, crit scaling, falloff, shop tier bonuses
- [spirit_damage.md](../../docs/mechanics/spirit_damage.md) — Spirit damage pipeline, spirit power sources, amp vs shred
- [damage_resistance.md](../../docs/mechanics/damage_resistance.md) — Resist stacking, shred mechanics
- [damage_amp_status_effects.md](../../docs/mechanics/damage_amp_status_effects.md) — Amp stacking, EE, crippling, soulshredder
- [health_survivability.md](../../docs/mechanics/health_survivability.md) — HP scaling, EHP calculation
- [boon_leveling_melee_parry.md](../../docs/mechanics/boon_leveling_melee_parry.md) — Boon tables, melee damage, parry

## Implementation Files

- `tests/test_engine.py` — All test classes:
  - `TestGameVerified` (section 18) — 27+ sandbox-pinned value tests
  - `TestSimReloadDamage` (section 14b) — Fire/reload timing verification
  - `TestDamageOutliers` (section 19) — Mechanic edge cases and bounds
  - `TestDataSanity` (section 17) — API data structural checks
  - `TestBulletDamage` (section 3) — Per-hero bullet damage scenarios
  - `TestSpiritDamage` (section 4) — Spirit damage formula tests
  - `TestMeleeDamage` (section 5) — Melee damage calculations
  - `TestAbilityUpgrades` (section 6) — Tier upgrade application
  - `TestHeroSpiritDPS` (section 7) — Aggregate spirit DPS
  - `TestDPSWithAccuracy` (section 8) — Accuracy + headshot calculations
  - `TestHeroScaling` (section 9) — Boon scaling curves
  - `TestTTK` (section 10) — Time-to-kill calculations
  - `TestBuildEngine` (section 11) — Build aggregation and evaluation
  - `TestComparison` (section 12) — Hero comparison and rankings
  - `TestItemDamage` (section 13) — Item damage scaling
  - `TestCombatSimulation` (section 14) — Simulation structural tests
  - `TestItemClassification` (section 15) — Item behavior classification
  - `TestEndToEndScenarios` (section 16) — Full pipeline scenarios
- `tests/conftest.py` — Fixtures, server management, Chromium discovery
- `docs/mechanics/` — 6 mechanic reference documents with formulas verified against wiki + sandbox
