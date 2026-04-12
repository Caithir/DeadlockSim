# Feature Specification: CLI Interface

**Feature Branch**: `009-cli-interface`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Interactive Menu Navigation (Priority: P1)

As a terminal user, I want an interactive numbered menu so that I can access all simulation features without a GUI.

**Why this priority**: The CLI is the primary interface for headless/server environments and quick lookups.

**Independent Test**: Run `deadlock-sim` — interactive menu displays 9 options. Select option 1 — hero stats are shown.

**Acceptance Scenarios**:

1. **Given** the CLI launches, **When** the menu displays, **Then** 9 numbered options are shown.
2. **Given** a menu option selected, **When** the feature runs, **Then** results are displayed in formatted terminal output.
3. **Given** a feature completes, **When** returning to menu, **Then** the user can select another option or exit.

---

### User Story 2 - Hero Stats Lookup (Priority: P1)

As a terminal user, I want to look up any hero's base stats and per-boon scaling so that I can quickly reference hero data.

**Why this priority**: Most common CLI use case — quick reference.

**Independent Test**: Select "Hero Stats", enter "Infernus" — displays base damage, fire rate, HP, scaling values.

**Acceptance Scenarios**:

1. **Given** hero name entered, **When** stats are fetched, **Then** gun stats, melee stats, survivability, and scaling are printed.

---

### User Story 3 - Bullet & Spirit DPS Calculators (Priority: P1)

As a terminal user, I want CLI calculators for bullet DPS and spirit damage so that I can do quick math without opening the GUI.

**Why this priority**: Rapid calculation for theorycrafting on the go.

**Independent Test**: Select "Bullet DPS", enter hero + boon level — DPS result printed.

**Acceptance Scenarios**:

1. **Given** hero and boon level entered, **When** bullet DPS is calculated, **Then** per-bullet damage, fire rate, DPS, and sustained DPS are displayed.
2. **Given** base damage, spirit scaling, and spirit power entered, **When** spirit damage is calculated, **Then** total damage and DPS are displayed.

---

### User Story 4 - Hero Comparison & Rankings (Priority: P2)

As a terminal user, I want side-by-side hero comparison and top-10 rankings so that I can evaluate the meta from the terminal.

**Why this priority**: Comparison features mirror GUI capabilities for CLI users.

**Independent Test**: Select "Compare", enter two hero names + boon level — side-by-side stats with advantage indicators.

**Acceptance Scenarios**:

1. **Given** two heroes compared, **When** results display, **Then** each stat shows which hero wins and by how much.
2. **Given** "Rankings" selected with stat and boon level, **When** computed, **Then** top 10 heroes listed in order.

---

### User Story 5 - Build Evaluator & Optimizer (Priority: P2)

As a terminal user, I want to evaluate custom builds and auto-optimize for DPS/TTK so that I can theorycraft builds from the CLI.

**Why this priority**: Build analysis via CLI enables scripting and batch analysis.

**Independent Test**: Select "Build Evaluator", enter hero + items — DPS, EHP, TTK displayed.

**Acceptance Scenarios**:

1. **Given** hero and item list entered, **When** build is evaluated, **Then** DPS, EHP, and TTK vs default defender are shown.
2. **Given** "Optimizer" selected with hero and budget, **When** optimizer runs, **Then** best items for max DPS are listed.

---

### User Story 6 - Scaling Curve & TTK (Priority: P2)

As a terminal user, I want to see scaling progression and time-to-kill calculations so that I can analyze hero power curves.

**Why this priority**: Completes feature parity with GUI.

**Independent Test**: Select "Scaling Curve" + hero — boon 0 to max progression printed as table.

**Acceptance Scenarios**:

1. **Given** hero selected for scaling, **When** curve is shown, **Then** each boon level's DPS and HP are listed.
2. **Given** attacker and defender for TTK, **When** computed, **Then** time, magazines, shots, and damage timeline are shown.

---

### Edge Cases

- What happens when a hero name is misspelled?
- How does the CLI handle invalid input (non-numeric for boon level)?
- What if the data cache is missing when CLI starts?

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide an interactive numbered menu with 9 operations.
- **FR-002**: System MUST support hero stats lookup with formatted terminal output.
- **FR-003**: System MUST support bullet DPS and spirit damage calculation.
- **FR-004**: System MUST support scaling curve display as a terminal table.
- **FR-005**: System MUST support TTK calculation with magazine reload accounting.
- **FR-006**: System MUST support side-by-side hero comparison.
- **FR-007**: System MUST support hero rankings by any stat.
- **FR-008**: System MUST support build evaluation and optimization.
- **FR-009**: System MUST delegate all calculations to the engine layer (no business logic in CLI).

## Success Criteria

- **SC-001**: All 9 menu options produce correct output matching engine calculations.
- **SC-002**: CLI and GUI produce identical results for the same inputs.
- **SC-003**: Invalid input is handled gracefully with error messages (no crashes).

## Assumptions

- Terminal supports basic text formatting (no color/ANSI required but may be used).
- CLI shares the same data cache as GUI.

## Implementation Files

- `deadlock_sim/ui/cli.py` — Interactive menu, input handling, formatted output
- `deadlock_sim/__main__.py` — Entry point
