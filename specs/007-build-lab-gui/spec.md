# Feature Specification: Build Lab GUI

**Feature Branch**: `007-build-lab-gui`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Hero Selection with Lore (Priority: P1)

As a user opening the Build Lab, I want to select a hero from a dropdown and see their lore/role information so that I can start building on my chosen hero.

**Why this priority**: Hero selection is the entry point for all Build Lab functionality.

**Independent Test**: Open Build Lab tab, select "Infernus" from dropdown — hero name, role, and lore display.

**Acceptance Scenarios**:

1. **Given** the Build Lab tab is active, **When** I select a hero from the dropdown, **Then** the hero's name, role, and description are displayed.
2. **Given** no hero is selected, **When** the tab loads, **Then** the shop and build grid are hidden until a hero is picked.

---

### User Story 2 - Item Shop with Sorting and Filtering (Priority: P1)

As a player browsing items, I want to search, filter by category/tier, and sort by any stat column (including DPS/EHP impact deltas) so that I can find the best item quickly.

**Why this priority**: The shop is the primary item discovery interface.

**Independent Test**: Open shop, type "spirit" in search — only spirit-related items shown. Click DPS column header — items sort by DPS impact.

**Acceptance Scenarios**:

1. **Given** shop is loaded, **When** I type a search term, **Then** items are filtered by name match.
2. **Given** shop items are displayed, **When** I click a stat column header, **Then** items sort ascending/descending by that stat.
3. **Given** category tabs (Weapon/Vitality/Spirit), **When** I click a tab, **Then** only items of that category are shown.
4. **Given** tier filter, **When** I select Tier 3, **Then** only Tier 3 items are displayed.
5. **Given** 17+ sort columns including impact deltas, **When** sorting by "DPS Impact", **Then** items ranked by how much DPS they add to the current build.

---

### User Story 3 - Build Slot Grid (Priority: P1)

As a player constructing a build, I want a 4×4 grid showing my equipped items with icons, names, and costs so that I can see my full build at a glance.

**Why this priority**: The build grid is the central build visualization.

**Independent Test**: Add 3 items to build — 3 slots show item cards with icons, remaining slots are empty.

**Acceptance Scenarios**:

1. **Given** an empty build, **When** I click an item in the shop, **Then** it appears in the next empty build slot.
2. **Given** an item in a build slot, **When** I click the remove button, **Then** the slot empties and the item returns to the shop.
3. **Given** a build with items, **When** viewing, **Then** each slot shows item icon, name, and cost.

---

### User Story 4 - Ability Upgrade Allocator (Priority: P1)

As a player, I want to allocate ability upgrade points (T1/T2/T3) to each of my hero's abilities so that upgrade effects are reflected in stats and simulations.

**Why this priority**: Ability upgrades significantly change hero power — builds aren't complete without them.

**Independent Test**: Select T1 on ability 0, T2 on ability 1 — stat panel updates to reflect upgraded values.

**Acceptance Scenarios**:

1. **Given** a hero selected, **When** ability upgrade UI loads, **Then** each ability shows T1/T2/T3 toggle buttons.
2. **Given** ability points available based on soul total, **When** I select T1 on an ability, **Then** one ability point is consumed and stats update.
3. **Given** no ability points remaining, **When** I try to add another upgrade, **Then** the action is prevented.

---

### User Story 5 - Result Stats Panel (Priority: P1)

As a player, I want to see computed stats (DPS, EHP, detailed breakdown by source) for my current build so that I can evaluate build effectiveness.

**Why this priority**: The stats panel is the output of all build construction — the reason the tool exists.

**Independent Test**: Build 3 items — stats panel shows DPS, EHP, bullet DPS, spirit DPS, HP, resists.

**Acceptance Scenarios**:

1. **Given** a build with items, **When** stats are computed, **Then** panel shows bullet DPS, spirit DPS, total DPS, EHP.
2. **Given** a clickable stat row, **When** I click it, **Then** a breakdown dialog shows per-item contributions to that stat.

---

### User Story 6 - Conditional Stat Toggles (Priority: P2)

As a player, I want to toggle conditional stats (shred active, weapon proc up, etc.) so that I can see DPS with and without conditional effects.

**Why this priority**: Many items have conditional bonuses — toggling them shows realistic vs best-case DPS.

**Independent Test**: Toggle "Shred Active" — DPS changes to reflect shred contribution.

**Acceptance Scenarios**:

1. **Given** an item with a conditional bonus, **When** the toggle is on, **Then** the conditional stat is included in calculations.

---

### User Story 7 - Shop Tier Bonus Visualization (Priority: P3)

As a player, I want to see bars showing my weapon/vitality/spirit investment toward tier bonus thresholds so that I know when I'm close to unlocking a tier bonus.

**Why this priority**: Tier bonuses are subtle but impactful — visual progress helps optimizing.

**Independent Test**: Equip 2 weapon items — weapon tier bar shows progress toward next bonus threshold.

**Acceptance Scenarios**:

1. **Given** items equipped in weapon category, **When** viewing tier bars, **Then** weapon bar shows current investment vs threshold.

---

### User Story 8 - Rich Item Tooltips (Priority: P2)

As a player hovering over an item, I want a tooltip matching the in-game style showing name, cost, properties, conditional flags, and upgrade path so that I can evaluate items without clicking.

**Why this priority**: Tooltips reduce friction in item evaluation.

**Independent Test**: Hover over Toxic Bullets — tooltip shows damage, duration, proc chance, category, tier.

**Acceptance Scenarios**:

1. **Given** hovering over an item, **When** tooltip appears, **Then** it shows item name, cost, category, tier, and all stat bonuses.
2. **Given** an active item, **When** tooltip shows, **Then** active effects (cooldown, duration) are displayed.

---

### Edge Cases

- What if the API returns an item with no image?
- How does the shop handle items with very long names?
- What happens when all 16 build slots are full?

## Requirements

### Functional Requirements

- **FR-001**: System MUST display a hero selection dropdown with all heroes.
- **FR-002**: System MUST display a searchable, sortable item shop with 17+ sort columns.
- **FR-003**: System MUST display a 4×4 build slot grid with item cards.
- **FR-004**: System MUST support ability upgrade allocation with point tracking.
- **FR-005**: System MUST display computed stats (DPS, EHP, breakdown) in a results panel.
- **FR-006**: System MUST support conditional stat toggles.
- **FR-007**: System MUST display shop tier bonus progress bars.
- **FR-008**: System MUST display rich item tooltips with in-game-style formatting.
- **FR-009**: System MUST use lazy shop loading (loaded on first tab activation).
- **FR-010**: System MUST track soul totals and auto-calculate boon levels.

## Success Criteria

- **SC-001**: User can construct a full build (hero + 6 items + ability upgrades) in under 30 seconds.
- **SC-002**: Shop sorting by DPS impact correctly ranks items by build improvement.
- **SC-003**: Stats panel updates within 200ms of any build change.

## Assumptions

- NiceGUI web framework provides the rendering layer.
- Item icons come from the API's `image_url` with local fallback.
- Build state is managed at module level (no persistence between sessions by default).

## Implementation Files

- `deadlock_sim/ui/gui.py` — Build tab UI construction and event handlers
- `deadlock_sim/ui/state.py` — `BuildState` for tracking hero, items, upgrades, souls
- `deadlock_sim/engine/builds.py` — Build evaluation called by GUI
- `deadlock_sim/engine/scoring.py` — Item scoring for shop sort columns
