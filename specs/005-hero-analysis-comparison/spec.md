# Feature Specification: Hero Analysis & Comparison

**Feature Branch**: `005-hero-analysis-comparison`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Hero Stat Snapshot at Boon Level (Priority: P1)

As a player, I want to see a hero's full stat profile (DPS, HP, melee, move speed) at any specific boon level so that I can evaluate a hero at different stages of the game.

**Why this priority**: Boon-level snapshots are the foundation for all comparison and scaling analysis.

**Independent Test**: Call `HeroMetrics.snapshot(hero, boons=15)` — returns `ScalingSnapshot` with all scaled stats.

**Acceptance Scenarios**:

1. **Given** a hero at boon 15, **When** snapshot is taken, **Then** bullet damage = `base + (damage_gain × 15)` and HP = `base_hp + (hp_gain × 15)`.
2. **Given** boon = 0, **When** snapshot is taken, **Then** all stats equal base values with no scaling applied.

---

### User Story 2 - Scaling Curve (Boon 0–35) (Priority: P1)

As a player, I want to see how a hero's stats scale across all 35 boon levels as a chart so that I can identify when a hero power-spikes.

**Why this priority**: Scaling curves reveal mid-game vs late-game hero strength.

**Independent Test**: Call `HeroMetrics.scaling_curve(hero, max_boons=35)` — returns list of snapshots for each boon level.

**Acceptance Scenarios**:

1. **Given** a hero with linear scaling, **When** curve is generated, **Then** there are 36 data points (boon 0 through 35).
2. **Given** the curve data, **When** plotted, **Then** DPS and HP show the correct growth trajectory.

---

### User Story 3 - Growth Percentage Analysis (Priority: P2)

As a player choosing a hero, I want to see growth percentages (DPS growth %, HP growth %, aggregate) so that I can compare which heroes scale best from early to late game.

**Why this priority**: Growth % is a key metric for hero selection strategy.

**Independent Test**: Call `HeroMetrics.growth_percentage(hero)` — returns DPS growth %, HP growth %, aggregate growth %.

**Acceptance Scenarios**:

1. **Given** a hero whose DPS doubles from boon 0 to 35, **When** growth is calculated, **Then** DPS growth = 100%.

---

### User Story 4 - Hero Comparison (Priority: P1)

As a player choosing between two heroes, I want a side-by-side comparison of their stats at a specific boon level so that I can make an informed pick.

**Why this priority**: Direct comparison is the most common hero evaluation use case.

**Independent Test**: Call `ComparisonEngine.compare_two(hero_a, hero_b, boons=10)` — returns `HeroComparison` with both snapshots and delta indicators.

**Acceptance Scenarios**:

1. **Given** two heroes at boon 10, **When** compared, **Then** each stat shows which hero is higher and by how much.
2. **Given** hero A has higher DPS but hero B has higher HP, **When** compared, **Then** both advantages are clearly shown.

---

### User Story 5 - Hero Rankings (Priority: P2)

As a player, I want a ranked list of heroes by any stat (DPS, HP, DPM, fire rate, growth %) so that I can see the best heroes for specific roles.

**Why this priority**: Rankings help with meta analysis and hero tier lists.

**Independent Test**: Call `ComparisonEngine.rank_heroes(stat='dps', boons=20)` — returns ordered list of `RankEntry`.

**Acceptance Scenarios**:

1. **Given** all heroes ranked by DPS at boon 20, **When** rankings are generated, **Then** list is sorted highest to lowest with rank numbers.
2. **Given** ranking by growth %, **When** generated, **Then** heroes with highest boon 0→35 improvement are ranked first.

---

### User Story 6 - Cross-Hero TTK Matrix (Priority: P3)

As a player, I want an N×N matrix showing each hero's time-to-kill against every other hero so that I can see matchup advantages.

**Why this priority**: Power user feature for competitive meta analysis.

**Independent Test**: Call `ComparisonEngine.cross_ttk_matrix(hero_names)` — returns matrix of TTK values.

**Acceptance Scenarios**:

1. **Given** 5 heroes selected, **When** matrix is computed, **Then** result is a 5×5 grid with TTK for each attacker→defender pair.

---

### User Story 7 - Time-to-Kill Calculation (Priority: P1)

As a player, I want to calculate how long it takes to kill a defender accounting for magazine reloads so that I can assess kill speed.

**Why this priority**: TTK is the definitive metric for combat effectiveness.

**Independent Test**: Call `HeroMetrics.ttk(hero, defender_hp)` — returns `TTKResult` with time, magazine count, and shots required.

**Acceptance Scenarios**:

1. **Given** attacker DPS of 200 and defender HP of 1000, **When** TTK is calculated, **Then** time ≈ 5 seconds (adjusted for reload cycles).
2. **Given** attacker with small magazine, **When** TTK computed, **Then** reload time is included in total TTK.

---

### Edge Cases

- What happens when comparing a hero against itself?
- How does ranking handle ties?
- What if TTK is infinite (DPS = 0 or invulnerable defender)?

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide stat snapshots at any boon level (0–35).
- **FR-002**: System MUST generate full scaling curves from boon 0 to any max.
- **FR-003**: System MUST calculate growth percentages (DPS, HP, aggregate).
- **FR-004**: System MUST compare two heroes side-by-side with delta indicators.
- **FR-005**: System MUST rank all heroes by any numeric stat.
- **FR-006**: System MUST compute cross-hero TTK matrices.
- **FR-007**: System MUST calculate realistic TTK including magazine reloads.

### Key Entities

- **ScalingSnapshot**: All stats for a hero at a specific boon level.
- **HeroComparison**: Side-by-side comparison result.
- **RankEntry**: Hero name, rank, stat value.
- **TTKResult**: Time-to-kill, magazine count, shots, damage timeline.

## Success Criteria

- **SC-001**: Snapshots match manual calculations at boons 0, 15, 35.
- **SC-002**: Rankings are correctly sorted for all supported stats.
- **SC-003**: TTK matches magazine-by-magazine hand calculation.
- **SC-004**: Cross-TTK matrix is symmetric in herosets (not values).

## Assumptions

- All heroes in the API have valid stat data for scaling.
- TTK assumes 100% accuracy unless configured otherwise.

## Implementation Files

- `deadlock_sim/engine/heroes.py` — `HeroMetrics` (snapshot, scaling_curve, growth, ttk)
- `deadlock_sim/engine/comparison.py` — `ComparisonEngine` (compare, rank, cross_ttk)
- `deadlock_sim/engine/scaling.py` — `ScalingCalculator` (backward-compat wrapper)
- `deadlock_sim/engine/ttk.py` — `TTKCalculator` (backward-compat wrapper)
- `deadlock_sim/models.py` — `ScalingSnapshot`, `HeroComparison`, `RankEntry`, `TTKResult`
