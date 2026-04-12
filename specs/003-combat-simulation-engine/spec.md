# Feature Specification: Combat Simulation Engine

**Feature Branch**: `003-combat-simulation-engine`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Event-Driven Combat Timeline (Priority: P1)

As a player, I want to simulate a full combat engagement between two heroes and see a time-ordered event log so that I understand real damage output over time.

**Why this priority**: The simulation is the most accurate DPS/TTK predictor, accounting for reload cycles, cooldowns, and item procs.

**Independent Test**: Call `CombatSimulator.run()` with attacker, defender, duration — returns `SimResult` with DPS, damage totals, and event timeline.

**Acceptance Scenarios**:

1. **Given** hero A attacks hero B for 15 seconds, **When** simulation runs, **Then** result includes total bullet damage, spirit damage, overall DPS, and TTK.
2. **Given** attacker has a magazine of 10 bullets, **When** magazine empties, **Then** a reload event fires and no bullets are fired during reload duration.
3. **Given** simulation runs for 15 seconds, **When** complete, **Then** every event has a timestamp and the timeline is monotonically ordered.

---

### User Story 2 - Ability Scheduling (Priority: P1)

As a player, I want to configure which abilities are used during combat and when so that I can model realistic combat rotations.

**Why this priority**: Ability usage dramatically affects total DPS — simulating gun-only is insufficient.

**Independent Test**: Configure `AbilityUse(ability_index=0, first_use=0.5, use_on_cooldown=True)` — abilities fire at correct times.

**Acceptance Scenarios**:

1. **Given** ability scheduled at t=0.5 with `use_on_cooldown=True`, **When** simulation runs, **Then** ability fires at t=0.5 and repeats every cooldown interval.
2. **Given** ability upgrades applied to the scheduled ability, **When** simulation runs, **Then** upgraded damage and cooldown values are used.

---

### User Story 3 - Item Proc and DoT Processing (Priority: P1)

As a player with proc-based items (Toxic Bullets, Mystic Shot), I want the simulation to trigger item effects based on hit events so that I see total damage including item contributions.

**Why this priority**: Many top items are proc-based — ignoring them makes the simulation inaccurate.

**Independent Test**: Equip Toxic Bullets on attacker — DoT damage events appear in the timeline.

**Acceptance Scenarios**:

1. **Given** a proc-on-hit item with 30% chance, **When** bullets hit, **Then** the proc triggers approximately 30% of the time.
2. **Given** a DoT item applied, **When** DoT is active, **Then** tick events fire at the correct interval until expiration.
3. **Given** an item with a cooldown, **When** proc fires, **Then** the item cannot proc again until its cooldown expires.

---

### User Story 4 - Debuff Stacking (Priority: P2)

As a player using shred/amp items, I want debuffs to stack correctly so that combined item effects are accurately modeled.

**Why this priority**: Debuff stacking is important for optimizing multi-item synergies.

**Independent Test**: Apply spirit shred from two sources — verify additive stacking clamped at 100%.

**Acceptance Scenarios**:

1. **Given** two spirit shred debuffs (10% each), **When** both active, **Then** total shred = 20%.
2. **Given** Ethereal Shift stacks (up to 10), **When** stacks accumulate, **Then** spirit amp increases per stack.
3. **Given** shred debuffs totaling over 100%, **When** stacked, **Then** effective shred is clamped to 100%.

---

### User Story 5 - Melee Integration (Priority: P2)

As a player who weaves melee attacks, I want the simulation to insert melee swings between shots/reloads so that melee DPS contributions are captured.

**Why this priority**: Melee weaving is a significant DPS increase for many heroes.

**Independent Test**: Enable `weave_melee=True` — light melee attacks appear in timeline during gaps.

**Acceptance Scenarios**:

1. **Given** `weave_melee=True`, **When** there is time between shots, **Then** light melee events fire.
2. **Given** `melee_after_reload=True`, **When** reload completes, **Then** a melee attack fires before resuming shooting.

---

### User Story 6 - Bidirectional Combat (Priority: P3)

As a player, I want to simulate both heroes fighting each other simultaneously so that I can determine who wins a 1v1 duel.

**Why this priority**: Adds realism but most analysis uses attacker-on-target mode.

**Independent Test**: Enable `bidirectional=True` — both heroes deal damage and a winner is determined.

**Acceptance Scenarios**:

1. **Given** bidirectional mode enabled, **When** simulation completes, **Then** result includes winner, defender DPS, and attacker HP remaining.

---

### Edge Cases

- What happens when both heroes kill each other on the same tick?
- How does the system handle heroes with 0 fire rate (pure spirit casters)?
- What if all abilities are on cooldown for the entire duration?
- How does distance-based falloff interact with melee range?

## Requirements

### Functional Requirements

- **FR-001**: System MUST simulate combat as an event-driven timeline with sub-second precision.
- **FR-002**: System MUST model magazine emptying and reload cycles.
- **FR-003**: System MUST support ability scheduling with configurable first-use time and cooldown repetition.
- **FR-004**: System MUST process 6 item behavior types: passive_stat, proc_on_hit, buildup, dot_active, pulse_passive, debuff_applier.
- **FR-005**: System MUST process 7 debuff types: spirit/bullet shred, spirit amp, fire rate slow, move speed slow, heal reduction, damage amp.
- **FR-006**: System MUST support 16+ event types in the timeline.
- **FR-007**: System MUST apply ability upgrades (T1/T2/T3) to scheduled abilities.
- **FR-008**: System MUST support melee weaving and melee-after-reload modes.
- **FR-009**: System MUST support bidirectional combat with winner determination.
- **FR-010**: System MUST apply distance-based damage falloff.
- **FR-011**: System MUST track combatant state (HP, shield, active debuffs, item cooldowns).

### Key Entities

- **SimConfig**: Full simulation configuration (attacker, defender, builds, settings, schedules).
- **SimSettings**: Duration, accuracy, headshot rate, melee toggles, bidirectional flag.
- **SimResult**: DPS, damage totals, TTK, event log, winner (if bidirectional).
- **SimEvent**: Individual event with timestamp, type, source, damage, metadata.
- **AbilityUse**: Ability schedule entry (index, first use, repeat flag).
- **ActiveUse**: Active item schedule entry.
- **CombatantState**: Per-combatant HP, shield, debuff list, item state.
- **DebuffInstance**: Active debuff with type, value, duration, source.

## Success Criteria

- **SC-001**: Simulation DPS matches analytical DPS within 5% for simple scenarios (no items, no abilities).
- **SC-002**: Event timeline is monotonically ordered by timestamp.
- **SC-003**: Item procs fire at statistically correct rates over many trials.
- **SC-004**: Simulation completes in under 100ms for a 15-second combat.

## Assumptions

- Combat simulates a 1v1 scenario at fixed distance.
- Item proc chances use deterministic rounding or pseudo-random for reproducibility.
- Debuff durations are accurate to the API data.

## Implementation Files

- `deadlock_sim/engine/simulation.py` — `CombatSimulator` with event loop, item behaviors, debuffs
- `deadlock_sim/models.py` — `SimConfig`, `SimSettings`, `SimResult`, `SimEvent`, event/debuff enums
