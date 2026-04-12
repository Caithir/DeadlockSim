# Feature Specification: Simulation & Settings GUI

**Feature Branch**: `008-simulation-settings-gui`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Run Combat Simulation (Priority: P1)

As a player, I want to set up attacker hero, defender hero, and equipped items, then run a combat simulation and see the results so that I can evaluate realistic combat outcomes.

**Why this priority**: The simulation tab is the primary advanced analysis tool.

**Independent Test**: Select attacker Infernus + defender Abrams, run sim — results panel shows DPS, TTK, damage breakdown.

**Acceptance Scenarios**:

1. **Given** attacker and defender configured, **When** Run is clicked, **Then** simulation executes and displays overall DPS, bullet damage, spirit damage, and TTK.
2. **Given** simulation completes, **When** viewing results, **Then** a combat timeline shows events with timestamps.

---

### User Story 2 - Ability Schedule Configuration (Priority: P1)

As a player, I want to configure which abilities are used during the simulation and when they first activate so that I can model different combat rotations.

**Why this priority**: Ability scheduling dramatically changes sim results.

**Independent Test**: Add Ability 3 to schedule at t=0.5 with repeat — simulation includes ability damage events.

**Acceptance Scenarios**:

1. **Given** ability schedule with one ability, **When** sim runs, **Then** ability damage appears in the timeline at configured times.
2. **Given** no abilities scheduled, **When** sim runs, **Then** only gun and melee damage are tracked.

---

### User Story 3 - Saved Builds (Priority: P2)

As a player, I want to save builds with custom names and reload them later so that I can compare different builds for the same hero.

**Why this priority**: Build persistence enables iterative optimization across sessions.

**Independent Test**: Save a build named "Spirit Infernus", reload it — same hero, items, and upgrades restored.

**Acceptance Scenarios**:

1. **Given** a build configured, **When** Save is clicked with a name, **Then** the build appears in the Saved Builds tab.
2. **Given** a saved build card, **When** Load is clicked, **Then** the Build Lab restores that hero, items, and upgrades.
3. **Given** a saved build card, **When** viewing, **Then** it shows hero name, item list, DPS, EHP, TTK, and a badge (Gun/Spirit/Hybrid).

---

### User Story 4 - Simulation Settings (Priority: P1)

As a player, I want to configure simulation parameters (duration, accuracy, headshot rate, melee toggles, etc.) so that I can model different combat scenarios.

**Why this priority**: Settings make simulations match real gameplay conditions.

**Independent Test**: Change accuracy to 80%, run sim — DPS increases vs 65% accuracy.

**Acceptance Scenarios**:

1. **Given** settings panel, **When** accuracy is changed to 80%, **Then** subsequent simulations use 80% accuracy.
2. **Given** melee weaving enabled, **When** sim runs, **Then** melee damage events appear in the timeline.
3. **Given** bidirectional combat enabled, **When** sim runs, **Then** result shows a winner and both heroes' damage.

---

### User Story 5 - Custom Item Overrides (Priority: P3)

As a player, I want to set custom DPS/EHP values for utility items so that I can approximate their value when the simulator can't model their effects directly.

**Why this priority**: Power user feature for advanced theorycrafting.

**Independent Test**: Set custom DPS override of 25 for Ethereal Shift — build eval incorporates the override.

**Acceptance Scenarios**:

1. **Given** a custom DPS override set for an item, **When** build evaluation runs, **Then** the override value is added to the item's effective DPS contribution.

---

### User Story 6 - Hero Stats Display (Priority: P2)

As a player, I want a tab showing detailed hero stats (gun stats, melee stats, survivability, scaling, growth %) so that I can study hero data comprehensively.

**Why this priority**: Reference data helps with hero selection and build planning.

**Independent Test**: Select a hero in Hero Stats tab — full stat breakdown displayed.

**Acceptance Scenarios**:

1. **Given** a hero selected, **When** Hero Stats tab is active, **Then** gun stats (damage, fire rate, DPS, ammo), melee stats, survivability, and per-boon scaling are shown.
2. **Given** scaling data displayed, **When** viewing, **Then** growth percentages (DPS, HP, aggregate) from boon 0→35 are shown.

---

### Edge Cases

- What happens when the user runs a simulation with no hero selected?
- How does the settings panel handle invalid values (negative accuracy)?
- What if saved builds reference items that no longer exist after a patch?

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide a simulation tab with attacker/defender hero selection.
- **FR-002**: System MUST display simulation results (DPS, TTK, timeline) after each run.
- **FR-003**: System MUST support configurable ability scheduling per simulation.
- **FR-004**: System MUST support saving and loading builds with custom names.
- **FR-005**: System MUST provide a settings panel for all simulation parameters.
- **FR-006**: System MUST support custom DPS/EHP overrides for utility items.
- **FR-007**: System MUST provide a Hero Stats tab with full hero data display.
- **FR-008**: System MUST support bidirectional combat mode in settings.

## Success Criteria

- **SC-001**: Simulation runs and displays results within 2 seconds.
- **SC-002**: Saved builds persist and restore correctly.
- **SC-003**: Settings changes are immediately reflected in subsequent simulations.

## Assumptions

- Builds are saved in module-level state (not persisted to disk between app restarts).
- Simulation uses the settings from the Settings tab at the time of execution.

## Implementation Files

- `deadlock_sim/ui/gui.py` — Simulation tab, Saved Builds tab, Settings tab, Hero Stats tab
- `deadlock_sim/ui/state.py` — Build state management for save/load
- `deadlock_sim/engine/simulation.py` — `CombatSimulator.run()` called by GUI
