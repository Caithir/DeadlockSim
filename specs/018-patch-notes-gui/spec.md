# Feature Specification: Patch Notes GUI Tab

**Feature Branch**: `018-patch-notes-gui`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - View Parsed Patch Changes (Priority: P1)

As a player checking the latest patch, I want to see parsed patch changes grouped by hero and item with delta highlighting so that I can quickly scan what was buffed or nerfed.

**Why this priority**: The patchnotes.py engine already parses and diffs patches — this is purely a UI surface for existing functionality.

**Independent Test**: Load the latest patch, verify changes are displayed grouped by hero/item with green (buff) and red (nerf) highlighting.

**Acceptance Scenarios**:

1. **Given** a patch has been parsed, **When** the Patch Notes tab is opened, **Then** changes are displayed grouped by hero name and item name.
2. **Given** a hero's base damage increased, **When** displayed, **Then** the change shows the old value, new value, and delta in green.
3. **Given** an item's cooldown increased (nerf), **When** displayed, **Then** the change is highlighted in red.

---

### User Story 2 - Build Impact Analysis (Priority: P1)

As a player who has a saved build, I want to see how the patch affects my build's DPS, EHP, and TTK so that I know if my build was buffed or nerfed overall.

**Why this priority**: "Was my build nerfed?" is the first question every player asks on patch day. This answers it with numbers.

**Independent Test**: Load a saved build, click "Impact on my build", verify it shows DPS/EHP/TTK before and after patch with deltas.

**Acceptance Scenarios**:

1. **Given** I have a saved build and a patch is loaded, **When** I click "Impact on my build", **Then** the system evaluates my build under pre-patch and post-patch data.
2. **Given** the evaluation completes, **When** results are displayed, **Then** DPS, EHP, spirit DPS, and TTK are shown as before/after pairs with deltas.
3. **Given** a patch nerfed my hero's base damage, **When** impact is calculated, **Then** DPS delta is negative and highlighted red.

---

### User Story 3 - Patch History Navigation (Priority: P3)

As a player, I want to select from available patches so that I can review older patch impacts or compare across patches.

**Why this priority**: Nice-to-have for historical analysis, but most players only care about the latest patch.

**Independent Test**: Load a previous patch file from `data/patches/`, verify its changes display correctly.

**Acceptance Scenarios**:

1. **Given** multiple patch files exist in `data/patches/`, **When** the tab loads, **Then** a dropdown lists available patches.
2. **Given** I select an older patch, **When** it loads, **Then** the changes and build impact reflect that specific patch.

---

### Edge Cases

- What happens when no patch files are available?
- What if a patch changes an item the player doesn't own — should it still show in "impact on my build"?
- How are new heroes/items added in a patch displayed?

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide a dedicated GUI tab for patch notes display.
- **FR-002**: System MUST group parsed changes by hero and item.
- **FR-003**: System MUST color-code changes: green for buffs, red for nerfs.
- **FR-004**: System MUST provide a "Impact on my build" button that evaluates the current/saved build under pre-patch and post-patch data.
- **FR-005**: Build impact MUST show DPS, EHP, spirit DPS, and TTK deltas.
- **FR-006**: System MUST use existing `patchnotes.py` functions: `parse_patch_notes()`, `diff_patch()`, `apply_patch()`.

### Key Entities

- **PatchChange**: Existing dataclass — hero/item, stat, old value, new value.
- **PatchReport**: Existing dataclass — list of changes with diff results.
- **BuildImpact**: Before/after BuildResult pair with computed deltas.

## Success Criteria

- **SC-001**: Patch changes render grouped and color-coded within 1 second.
- **SC-002**: Build impact analysis completes in under 2 seconds.
- **SC-003**: All changes from `parse_patch_notes()` are displayed — no silent drops.
