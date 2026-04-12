# Feature Specification: Power Spike Tab

**Feature Branch**: `016-power-spike-tab`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Build Timing Chart (Priority: P1)

As a player planning my item purchase order, I want to see a power curve chart with X=soul count showing how my stats change as I buy each item so that I can identify when my build comes online.

**Why this priority**: Build timing is a core Deadlock skill — knowing when to spike determines lane matchups and team fight timing.

**Independent Test**: Set up a build with 4+ items, define a purchase order, verify the chart shows step-function stat jumps at each cumulative soul threshold.

**Acceptance Scenarios**:

1. **Given** a build with items ordered by purchase sequence, **When** the chart renders, **Then** X axis shows cumulative soul cost and Y axis shows stat values with step jumps at each item purchase.
2. **Given** items A (500), B (1250), C (3000) in buy order, **When** charted, **Then** steps appear at souls 500, 1750, 4750.
3. **Given** a purchase order, **When** the user drags an item to reorder, **Then** the chart updates to reflect the new purchase sequence.

---

### User Story 2 - Flex Slot Power Curves (Priority: P1)

As a player who may have between 9 and 12 available item slots, I want to see 4 overlapping power curves (one per slot count) so that I can plan builds for different game states.

**Why this priority**: Slot count varies by game state — the power curves diverge when slot-locked builds require item sells.

**Independent Test**: View a 12+ item build, verify 4 distinct lines appear (9/10/11/12 slots) with divergence after the slot cap.

**Acceptance Scenarios**:

1. **Given** a build with more items than 9 slots, **When** the chart renders, **Then** 4 lines appear showing power at 9, 10, 11, and 12 available slots.
2. **Given** a 9-slot line, **When** a 10th item is added, **Then** the system auto-sells the lowest-value item (50% soul refund) and shows the adjusted power.
3. **Given** the 12-slot line, **When** all items fit, **Then** no sell events occur and the line shows pure additive progression.

---

### User Story 3 - Item Sell/Swap Events (Priority: P2)

As a player who plans to sell early items for late-game upgrades, I want to define sell/swap events in my build order so that the chart accurately reflects my planned item transitions.

**Why this priority**: Slot-locked item transitions are critical late-game decisions that dramatically change power curves.

**Independent Test**: Mark an item as "sell X, buy Y" in the build order, verify the chart shows the power dip/spike at the correct soul threshold.

**Acceptance Scenarios**:

1. **Given** auto-sell mode is active and 9-slot line needs a 10th item, **When** the chart computes, **Then** the lowest-value current item is auto-sold (50% refund) and the net soul cost/stat delta reflects the swap.
2. **Given** the user manually marks "sell Headshot Booster, buy Crippling Headshot", **When** the chart renders, **Then** the sell refund offsets the buy cost and stats reflect removing the old item and adding the new one.
3. **Given** a sell event, **When** the item is sold, **Then** the player receives 50% of the original cost as a soul refund.

---

### User Story 4 - Selectable Y-Axis Metrics (Priority: P2)

As a player analyzing different aspects of my build, I want to toggle which metrics are displayed on the Y axis so that I can focus on DPS, survivability, or spirit power independently.

**Why this priority**: Different playstyles care about different metrics — gun heroes care about bullet DPS while casters care about spirit DPS.

**Independent Test**: Toggle metric visibility, verify the chart shows/hides the selected metric lines.

**Acceptance Scenarios**:

1. **Given** the chart is displayed with Total DPS as default, **When** the user toggles on Bullet DPS, Spirit DPS, and EHP, **Then** additional lines appear for each metric.
2. **Given** the user enables Sim DPS, **When** the "Compute" button is clicked, **Then** simulation-based DPS is calculated for each purchase step and displayed.

---

### Edge Cases

- What happens when a build has only 1 item?
- How are shop tier bonuses reflected in the power curve (e.g., buying 4 weapon items triggers a tier bonus)?
- What if the user's purchase order has items that unlock a tier bonus mid-sequence?
- How is the X axis scaled when there are large soul gaps between items?

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide a dedicated GUI tab for power spike visualization.
- **FR-002**: Chart X axis MUST be cumulative soul count.
- **FR-003**: System MUST support explicit drag-to-reorder item purchase sequences.
- **FR-004**: System MUST render 4 power curves for 9, 10, 11, and 12 flex slot counts.
- **FR-005**: System MUST support auto-sell (lowest-value item, 50% refund) as the default when slot-locked.
- **FR-006**: System MUST support user-defined sell/swap event overrides.
- **FR-007**: Y axis MUST support toggleable metrics: Total DPS (default), Bullet DPS, Spirit DPS, EHP, Sim DPS (via compute button).
- **FR-008**: Chart MUST show step-function stat changes at each purchase/sell event.

### Key Entities

- **PurchaseEvent**: Item, cumulative soul cost, action (buy/sell/swap), target item (for swaps).
- **PowerCurvePoint**: Soul count, active items, computed stats (DPS, EHP, spirit DPS).
- **SlotConfig**: Number of available flex slots (9–12).

## Success Criteria

- **SC-001**: Chart renders with 12 items across 4 slot lines in under 2 seconds.
- **SC-002**: Auto-sell correctly picks the lowest-value item and applies 50% refund.
- **SC-003**: Drag-to-reorder updates the chart in under 1 second.
- **SC-004**: Shop tier bonuses are reflected when purchase order crosses tier thresholds.
