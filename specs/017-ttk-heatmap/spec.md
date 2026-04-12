# Feature Specification: TTK Heatmap

**Feature Branch**: `017-ttk-heatmap`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Cross-Hero TTK Grid (Priority: P1)

As a player evaluating matchups, I want an N×N heatmap showing time-to-kill for every selected hero pair so that I can instantly see which matchups favor which heroes.

**Why this priority**: TTK is the single most important combat metric and no GUI visualization exists for the existing `cross_ttk_matrix()` engine call.

**Independent Test**: Select 5 heroes, click "Generate", verify a 5×5 colored grid appears with rows=attackers, columns=defenders, cells colored by TTK.

**Acceptance Scenarios**:

1. **Given** I select 5 heroes and a boon level, **When** I click "Generate", **Then** a 5×5 heatmap renders with rows as attackers and columns as defenders.
2. **Given** the heatmap is rendered, **When** I hover over a cell, **Then** a tooltip shows the exact TTK value (e.g., "Haze → Abrams: 4.2s").
3. **Given** cells represent TTK values, **When** the grid renders, **Then** fast kills are green and slow kills are red.

---

### User Story 2 - Boon Level Selector (Priority: P1)

As a player, I want to adjust the boon level and regenerate the heatmap so that I can see how matchups shift as the game progresses.

**Why this priority**: Matchups change dramatically across boon levels — early game vs late game dominance differs per hero.

**Independent Test**: Generate at boon 5, change to boon 25, regenerate, verify cell values change.

**Acceptance Scenarios**:

1. **Given** a heatmap at boon level 10, **When** I change to boon level 25 and regenerate, **Then** the TTK values update to reflect higher boon stats.

---

### User Story 3 - Hero Subset Selection (Priority: P2)

As a player, I want to select a specific subset of heroes (5–10) rather than computing all 30+ so that generation is fast and the grid is readable.

**Why this priority**: N² computation for all heroes is expensive and the full grid is too large to read. Subset selection keeps it practical.

**Independent Test**: Select 8 heroes from the full roster, verify only those 8 appear in the grid.

**Acceptance Scenarios**:

1. **Given** the hero selection UI, **When** I pick 8 heroes, **Then** only those 8 appear as rows and columns in the heatmap.
2. **Given** no heroes are selected, **When** I try to generate, **Then** a message prompts me to select at least 2 heroes.

---

### Edge Cases

- What happens when TTK exceeds the simulation duration (hero can't kill the target)?
- How are mirror matchups displayed (hero vs. same hero)?
- What if only 2 heroes are selected — is a 2×2 grid still useful?

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide a heatmap visualization for cross-hero TTK data.
- **FR-002**: System MUST use the existing `ComparisonEngine.cross_ttk_matrix()` engine call.
- **FR-003**: System MUST allow selecting a subset of 2–10 heroes for the grid.
- **FR-004**: System MUST include a boon level selector.
- **FR-005**: Cells MUST be color-coded from green (fast kill) to red (slow kill).
- **FR-006**: System MUST show exact TTK on hover.
- **FR-007**: Generation MUST be triggered by a "Generate" button (not automatic).

### Key Entities

- **TTK Matrix**: 2D array of TTK values indexed by attacker and defender hero.
- **HeatmapConfig**: Selected heroes, boon level.

## Success Criteria

- **SC-001**: 8×8 heatmap generates in under 5 seconds.
- **SC-002**: Color scale correctly maps fastest TTK=green, slowest=red.
- **SC-003**: Hover tooltips show accurate TTK values matching engine output.
