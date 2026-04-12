# Feature Specification: Build System & Optimization

**Feature Branch**: `004-build-system-optimization`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Aggregate Build Stats (Priority: P1)

As a player constructing a build, I want all equipped item stats aggregated into a single stat block so that I can see my hero's total stats.

**Why this priority**: Stat aggregation is the foundation of all build analysis.

**Independent Test**: Call `BuildEngine.aggregate_stats()` with 3 items — returns `BuildStats` with summed weapon damage, spirit power, resist, etc.

**Acceptance Scenarios**:

1. **Given** items with +20 and +30 weapon damage, **When** aggregated, **Then** `BuildStats.weapon_damage` = 50.
2. **Given** items with 15% and 10% bullet resist, **When** aggregated with multiplicative stacking, **Then** effective resist = `1 - (1-0.15)(1-0.10)` = 23.5%.
3. **Given** items across weapon/vitality/spirit categories, **When** aggregated, **Then** shop tier bonuses are applied (weapon cost → weapon %, vitality cost → HP %, spirit cost → spirit power).

---

### User Story 2 - Build Evaluation (Priority: P1)

As a player, I want to evaluate a complete build getting DPS, EHP, and TTK metrics so that I can judge build effectiveness.

**Why this priority**: Without evaluation, build comparison is impossible.

**Independent Test**: Call `BuildEngine.evaluate_build()` — returns `BuildResult` with DPS, EHP, TTK.

**Acceptance Scenarios**:

1. **Given** a hero with a build vs a defender, **When** evaluated, **Then** result includes bullet DPS, spirit DPS, combined DPS, EHP, and TTK.
2. **Given** two different builds on the same hero, **When** both evaluated, **Then** the higher-DPS build has lower TTK.

---

### User Story 3 - Stat Breakdown per Item (Priority: P2)

As a player, I want to see which items contribute which stats to my build total so that I can identify redundant or underperforming items.

**Why this priority**: Breakdown enables informed item swap decisions.

**Independent Test**: Call `BuildEngine.stat_breakdown()` — returns per-item contribution to each stat.

**Acceptance Scenarios**:

1. **Given** 4 items equipped, **When** breakdown is requested, **Then** each item's contribution to each stat is listed separately.

---

### User Story 4 - Build Optimizer: Max DPS (Priority: P2)

As a player with a soul budget, I want the system to recommend the best items for maximum bullet DPS so that I can optimize my gun build.

**Why this priority**: Automated optimization saves time and discovers non-obvious item combos.

**Independent Test**: Call `BuildOptimizer.best_dps_items()` with a budget — returns a list of items maximizing DPS.

**Acceptance Scenarios**:

1. **Given** a 10,000 soul budget, **When** optimizer runs, **Then** it returns items fitting the budget that maximize bullet DPS.
2. **Given** the optimizer output, **When** I manually try other items within budget, **Then** no combination exceeds the optimizer's DPS.

---

### User Story 5 - Build Optimizer: Min TTK (Priority: P2)

As a player, I want the system to recommend items that minimize time-to-kill against a specific defender so that I can build for burst/kill speed.

**Why this priority**: TTK optimization is often more practical than raw DPS optimization.

**Independent Test**: Call `BuildOptimizer.best_ttk_items()` — returns items minimizing TTK.

**Acceptance Scenarios**:

1. **Given** a budget and a specific defender hero, **When** optimizer runs, **Then** it returns items minimizing TTK against that defender.

---

### User Story 6 - Build-to-Config Conversion (Priority: P1)

As the engine, I need to convert aggregated build stats into a `CombatConfig` object with boon-scaled spirit power so that all calculation paths share one consistent config pipeline.

**Why this priority**: Prevents spirit power divergence between different calculation paths.

**Independent Test**: Call `build_to_attacker_config()` — returns `CombatConfig` with `current_spirit` correctly combining item spirit + boon spirit gain.

**Acceptance Scenarios**:

1. **Given** items providing 50 spirit power and hero with spirit_gain=3.0 at boon 10, **When** converted, **Then** `current_spirit = 50 + (3.0 × 10) = 80`.

---

### Edge Cases

- What happens with duplicate items (can the same item be added twice)?
- How does the optimizer handle items with conditional stats?
- What if budget is too small for any item?

## Requirements

### Functional Requirements

- **FR-001**: System MUST aggregate all item stats into a single `BuildStats` object.
- **FR-002**: System MUST apply multiplicative resist stacking: `1 - Π(1 - resist_i)`.
- **FR-003**: System MUST calculate shop tier bonuses based on per-category cost thresholds.
- **FR-004**: System MUST evaluate builds producing DPS, EHP, and TTK metrics.
- **FR-005**: System MUST provide per-item stat breakdown.
- **FR-006**: System MUST optimize item selection for maximum DPS within a soul budget.
- **FR-007**: System MUST optimize item selection for minimum TTK within a soul budget.
- **FR-008**: System MUST convert build stats to `CombatConfig` with centralized spirit power calculation.

### Key Entities

- **Build**: Collection of equipped items.
- **BuildStats**: Aggregated stats (weapon damage, spirit power, resist, HP, lifesteal, cooldown reduction, etc.).
- **BuildResult**: Evaluation output (DPS, EHP, TTK, breakdown).
- **BuildOptimizer**: Greedy optimizer for DPS and TTK targets.

## Success Criteria

- **SC-001**: Aggregated stats match hand-calculated sums for known item sets.
- **SC-002**: Multiplicative resist stacking is mathematically correct.
- **SC-003**: Optimizer returns a valid build within budget.
- **SC-004**: Spirit power is consistent across `build_to_attacker_config`, simulation, and GUI display.

## Assumptions

- Items cannot be equipped more than once (no duplicate stacking).
- Optimizer uses greedy selection (not exhaustive search).
- Shop tier bonuses follow the game's documented thresholds.

## Implementation Files

- `deadlock_sim/engine/builds.py` — `BuildEngine`, `BuildOptimizer`
- `deadlock_sim/models.py` — `Build`, `BuildStats`, `BuildResult`
