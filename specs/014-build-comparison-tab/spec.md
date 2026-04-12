# Feature Specification: Build Comparison Tab

**Feature Branch**: `014-build-comparison-tab`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Side-by-Side Build Diff (Priority: P1)

As a player with multiple saved builds, I want to compare two builds side-by-side with stat deltas so that I can see exactly how they differ in DPS, EHP, TTK, and spirit DPS.

**Why this priority**: Build comparison is the most requested missing feature — players save builds but can't evaluate tradeoffs between them.

**Independent Test**: Load two saved builds for the same hero, verify a two-column layout shows all key stats with green/red delta arrows.

**Acceptance Scenarios**:

1. **Given** two saved builds for the same hero, **When** both are loaded into the comparison view, **Then** each stat (DPS, EHP, TTK, spirit DPS) is shown side-by-side with delta values and directional arrows (green for improvement, red for regression).
2. **Given** Build A has higher DPS but lower EHP than Build B, **When** compared, **Then** DPS delta shows green on A's side and EHP delta shows green on B's side.
3. **Given** both builds are loaded, **When** the user views the comparison, **Then** item differences are highlighted (items unique to each build).

---

### User Story 2 - Load from Saved Builds (Priority: P1)

As a player, I want to select builds from my saved builds for comparison so that I don't need to rebuild them from scratch.

**Why this priority**: Without saved build integration, the comparison tab has no data to work with.

**Independent Test**: Open comparison tab, select two saved builds from dropdowns, verify both load correctly.

**Acceptance Scenarios**:

1. **Given** I have saved builds, **When** I open the comparison tab, **Then** I see two dropdowns listing all saved builds.
2. **Given** I select a saved build, **When** it loads, **Then** its hero, items, ability upgrades, and boon level are restored.

---

### User Story 3 - Single Item Swap Impact (Priority: P2)

As a player evaluating an item change, I want to swap a single item in one build and see the stat delta immediately so that I can test marginal changes without saving a new build.

**Why this priority**: Quick item swap testing is the most common comparison scenario — "what if I drop X for Y?"

**Independent Test**: Load a build, swap one item, verify stat deltas update in real-time.

**Acceptance Scenarios**:

1. **Given** a build is loaded in one comparison slot, **When** I remove an item and add a different one, **Then** all stat deltas update immediately.
2. **Given** I swap Toxic Bullets for Mystic Shot, **When** the delta recalculates, **Then** DPS, EHP, spirit DPS, and TTK deltas all reflect the change.

---

### Edge Cases

- What happens when comparing builds for different heroes?
- How is TTK compared when builds use different defenders?
- What if a saved build references an item that no longer exists (post-patch)?

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide a dedicated 6th GUI tab for build comparison.
- **FR-002**: System MUST allow loading two saved builds into comparison slots.
- **FR-003**: System MUST display DPS, EHP, TTK, spirit DPS, and bullet DPS for each build.
- **FR-004**: System MUST show stat deltas with color-coded directional indicators (green=better, red=worse).
- **FR-005**: System MUST highlight item differences between builds.
- **FR-006**: System MUST support in-place item swaps without saving a new build.

### Key Entities

- **ComparisonSlot**: Hero, build items, ability upgrades, boon level, computed BuildResult.
- **StatDelta**: Stat name, value A, value B, delta, direction (better/worse).

## Success Criteria

- **SC-001**: Loading two saved builds and displaying comparison takes under 1 second.
- **SC-002**: Stat deltas are mathematically correct (verified against manual BuildResult subtraction).
- **SC-003**: Item swap delta updates in under 500ms.
