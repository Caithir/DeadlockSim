# Feature Specification: Hero Gun DPS Rankings

**Feature Branch**: `020-hero-gun-dps-rankings`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Gun DPS Comparison at Min and Max Boons (Priority: P1)

As a player choosing a hero, I want to see all heroes ranked by raw gun DPS at 0 boons and 35 boons (no items) so that I can compare base weapon strength across the roster.

**Why this priority**: Base gun DPS is the most fundamental hero stat and currently has no visual comparison in the GUI.

**Independent Test**: Open the rankings view, verify a table/bar chart shows all heroes sorted by gun DPS at boon 0 and boon 35.

**Acceptance Scenarios**:

1. **Given** the rankings view is opened, **When** it loads, **Then** all heroes are listed with their gun DPS at boon 0 and boon 35.
2. **Given** the data is displayed, **When** sorted by boon 35 DPS, **Then** the highest gun DPS hero is at the top.
3. **Given** a hero with high base damage but slow fire rate vs. one with low damage but fast fire rate, **When** compared, **Then** DPS correctly reflects both factors.

---

### User Story 2 - Visual Bar Chart (Priority: P2)

As a player glancing at hero rankings, I want a horizontal bar chart showing gun DPS so that I can visually compare heroes at a glance.

**Why this priority**: Bar charts are faster to scan than tables for relative comparisons.

**Independent Test**: Verify a bar chart renders with hero names on Y axis and DPS bars showing both boon 0 and boon 35 values.

**Acceptance Scenarios**:

1. **Given** the rankings are loaded, **When** the bar chart renders, **Then** each hero has two bars (boon 0 in lighter color, boon 35 in darker color).
2. **Given** the bars are displayed, **When** hovered, **Then** exact DPS values are shown.

---

### Edge Cases

- How are heroes with 0 gun DPS (if any) displayed?
- How is sustained DPS (accounting for reload) vs. burst DPS handled — which is shown?
- Do pellet-based heroes (shotguns) show per-target DPS using `effective_pellets()`?

## Requirements

### Functional Requirements

- **FR-001**: System MUST rank all heroes by raw gun DPS at boon 0 and boon 35 with no items.
- **FR-002**: System MUST display results as both a sortable table and a bar chart.
- **FR-003**: System MUST use existing `ComparisonEngine.rank_heroes()` with `'dps'` stat.
- **FR-004**: System MUST use `DamageCalculator.effective_pellets()` for pellet-based heroes.
- **FR-005**: View MUST live as a sub-view within the TTK Heatmap tab.

### Key Entities

- **RankEntry**: Existing dataclass — hero name, stat value, rank position.

## Success Criteria

- **SC-001**: All heroes appear in the ranking with correct DPS values.
- **SC-002**: Rankings load in under 1 second.
- **SC-003**: Bar chart and table show consistent values.
