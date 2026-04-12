# Feature Specification: Item Scoring Engine

**Feature Branch**: `006-item-scoring-engine`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Fast Analytical Item Scoring (Priority: P1)

As a player in the Build Lab, I want each shop item scored by DPS and EHP delta so that I can quickly see which item gives the biggest improvement.

**Why this priority**: Fast scoring enables real-time shop sorting as the user browses items.

**Independent Test**: Call `ItemScorer.score_candidates(mode='fast')` — returns per-item DPS/EHP deltas in under 200ms.

**Acceptance Scenarios**:

1. **Given** a hero with a current build, **When** fast scoring runs, **Then** each unequipped item gets a DPS delta (how much DPS it adds) and EHP delta.
2. **Given** an item with +20 weapon damage, **When** scored, **Then** its DPS delta is positive and proportional to the stat.
3. **Given** scoring completes, **When** items are sorted by DPS delta, **Then** the highest-impact item is at the top.

---

### User Story 2 - Simulation-Based Item Scoring (Priority: P2)

As a player wanting more accuracy, I want items scored via full combat simulation (gun, spirit, or hybrid focus) so that item procs and interactions are captured.

**Why this priority**: Simulation scoring captures item procs and DoTs that fast mode misses.

**Independent Test**: Call `ItemScorer.score_candidates(mode='sim_gun')` — returns scores that include proc damage contributions.

**Acceptance Scenarios**:

1. **Given** a proc-on-hit item (e.g., Toxic Bullets), **When** scored in sim_gun mode, **Then** its DPS delta includes DoT damage.
2. **Given** gun mode vs spirit mode, **When** the same item is scored, **Then** DPS deltas differ based on combat focus.

---

### User Story 3 - Per-Soul Efficiency (Priority: P2)

As a budget-conscious player, I want to see DPS-per-soul-spent for each item so that I can maximize value when I'm behind on farm.

**Why this priority**: Per-soul efficiency helps lower-income players make smart purchases.

**Independent Test**: Score an item — `ItemScore` includes `dps_per_soul` field.

**Acceptance Scenarios**:

1. **Given** item A costs 500 souls with +10 DPS delta and item B costs 3000 souls with +15 DPS delta, **When** per-soul efficiency is compared, **Then** item A is more efficient (0.02 vs 0.005 DPS/soul).

---

### Edge Cases

- What happens when an item has 0 cost (free items)?
- How are items that only add EHP (no DPS) ranked in DPS mode?
- What if the current build already has 6 items and no slots?

## Requirements

### Functional Requirements

- **FR-001**: System MUST score all candidate items against the current hero/build.
- **FR-002**: System MUST support "fast" mode using analytical stat deltas.
- **FR-003**: System MUST support "sim_gun", "sim_spirit", and "sim_hybrid" modes using full combat simulation.
- **FR-004**: System MUST calculate DPS delta, EHP delta, and per-soul efficiency for each item.
- **FR-005**: System MUST return scores as `dict[str, ItemScore]` for easy lookup.

### Key Entities

- **ItemScorer**: Stateless scoring engine.
- **ScoringConfig**: Mode, hero, current build, defender.
- **ItemScore**: DPS delta, EHP delta, per-soul efficiency, scoring mode.

## Success Criteria

- **SC-001**: Fast scoring completes in under 200ms for all ~100 items.
- **SC-002**: Sim scoring produces different results than fast scoring for proc items.
- **SC-003**: Per-soul efficiency is correctly calculated as `delta / cost`.

## Assumptions

- All items in the shop are valid scoring candidates.
- Scoring uses a default defender if none specified.

## Implementation Files

- `deadlock_sim/engine/scoring.py` — `ItemScorer`, `ScoringConfig`, scoring logic
- `deadlock_sim/models.py` — `ItemScore`
