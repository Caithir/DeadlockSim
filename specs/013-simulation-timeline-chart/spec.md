# Feature Specification: Simulation Timeline Chart

**Feature Branch**: `013-simulation-timeline-chart`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Damage Over Time Chart (Priority: P1)

As a player running a combat simulation, I want to see a stacked area chart of damage dealt over time so that I can understand when each damage source contributes during a fight.

**Why this priority**: The simulation engine already produces per-event timeline data but it's only shown as aggregate numbers. This visualization turns raw data into actionable fight insight.

**Independent Test**: Run a simulation with abilities and items, verify the chart renders with distinct bullet/spirit/melee/proc layers on X=time, Y=cumulative damage.

**Acceptance Scenarios**:

1. **Given** a completed simulation with bullet and spirit damage, **When** the timeline chart renders, **Then** it shows a stacked area chart with separate layers for bullet, spirit, melee, and item proc damage.
2. **Given** a simulation result, **When** the user hovers over the chart, **Then** a tooltip shows the exact damage values per source at that time point.
3. **Given** a simulation with ability usage, **When** abilities fire, **Then** spirit damage steps appear at the correct timestamps.

---

### User Story 2 - HP Remaining Overlay (Priority: P2)

As a player analyzing kill timing, I want the defender's HP remaining overlaid on the damage chart so that I can see when the kill happens relative to damage output.

**Why this priority**: HP overlay connects damage output to actual lethality — showing "you kill at 4.2s" in context.

**Independent Test**: Run a simulation, verify HP line appears on secondary Y axis decreasing as damage accumulates.

**Acceptance Scenarios**:

1. **Given** a simulation result with damage timeline, **When** the chart renders, **Then** a line shows defender HP remaining on a secondary Y axis, decreasing over time.
2. **Given** the defender dies during the simulation, **When** HP reaches 0, **Then** the HP line terminates and a kill marker is shown.

---

### User Story 3 - Per-Second Bucketed View (Priority: P3)

As a player comparing burst vs sustained damage, I want to toggle between cumulative and per-second DPS views so that I can identify damage spikes.

**Why this priority**: Per-second view highlights burst windows that are hidden in cumulative charts.

**Independent Test**: Toggle the view mode, verify the chart switches from cumulative area to per-second bar chart.

**Acceptance Scenarios**:

1. **Given** the cumulative chart is displayed, **When** the user toggles to "per-second" mode, **Then** the chart shows DPS bars bucketed by 0.5s intervals.

---

### Edge Cases

- What happens when a simulation has zero spirit damage (gun-only build)?
- How does the chart handle very short simulations (< 2 seconds)?
- What if the defender has shields — show shield HP separately?

## Requirements

### Functional Requirements

- **FR-001**: System MUST render a stacked area chart from `SimResult.timeline` data.
- **FR-002**: Chart MUST separate damage into bullet, spirit, melee, and item proc layers.
- **FR-003**: System MUST support cumulative and per-second display modes.
- **FR-004**: System MUST overlay defender HP remaining on a secondary Y axis.
- **FR-005**: Chart MUST appear in the Simulation tab after a simulation completes.

### Key Entities

- **SimResult.timeline**: Existing list of `DamageEntry` objects with time, source, damage, damage_type.
- **Chart configuration**: Display mode (cumulative/per-second), layer visibility toggles.

## Success Criteria

- **SC-001**: Chart renders within 500ms of simulation completion.
- **SC-002**: Damage layers sum to total damage shown in simulation results.
- **SC-003**: HP overlay accurately reflects damage dealt at each time point.
