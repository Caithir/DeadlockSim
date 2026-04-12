# Feature Specification: Ability Upgrade Optimizer

**Feature Branch**: `021-ability-upgrade-optimizer`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Rank Ability Upgrades by DPS Impact (Priority: P1)

As a player with limited ability points, I want to see all available ability upgrades ranked by their DPS impact so that I can pick the highest-value upgrade first.

**Why this priority**: Ability point allocation is a core build decision and currently requires manual trial-and-error. Automated ranking removes guesswork.

**Independent Test**: Select a hero with unspent AP, verify a sorted list shows each unpicked upgrade with its spirit DPS delta.

**Acceptance Scenarios**:

1. **Given** Infernus at 10 boons with no ability upgrades, **When** the optimizer runs, **Then** all available T1 upgrades are listed sorted by spirit DPS delta (highest first).
2. **Given** T1 on ability 0 is already taken, **When** the optimizer runs, **Then** T2 on ability 0 and T1 on other abilities are ranked.
3. **Given** an upgrade that reduces cooldown (no direct damage), **When** scored, **Then** the DPS delta reflects the increased ability uptime.

---

### User Story 2 - AP Budget Awareness (Priority: P1)

As a player, I want the optimizer to respect my current AP budget so that it only recommends upgrades I can actually afford.

**Why this priority**: Recommending upgrades the player can't afford is useless noise.

**Independent Test**: With 3 AP remaining, verify only upgrades costing ≤ 3 AP are shown.

**Acceptance Scenarios**:

1. **Given** 1 AP remaining, **When** the optimizer runs, **Then** only T1 upgrades (cost 1 AP) are listed.
2. **Given** 0 AP remaining, **When** the optimizer runs, **Then** a message says "No ability points available."
3. **Given** 3 AP remaining with T1 already taken on ability 0, **When** the optimizer runs, **Then** T2 on ability 0 (cost 1 AP) and T1 on others (cost 1 AP each) are shown.

---

### User Story 3 - Integration with Build Tab (Priority: P2)

As a player in the Build tab, I want the upgrade recommendations displayed alongside the ability upgrade UI so that I can see suggestions while configuring my build.

**Why this priority**: Contextual placement makes the feature discoverable and immediately actionable.

**Independent Test**: Open Build tab with a hero selected, verify upgrade recommendations appear near the ability upgrade section.

**Acceptance Scenarios**:

1. **Given** the Build tab is open with a hero, **When** abilities section is visible, **Then** a "Suggested upgrades" list appears showing top-ranked upgrades.
2. **Given** the user clicks a suggested upgrade, **When** clicked, **Then** the upgrade is applied and the suggestions refresh.

---

### Edge Cases

- What about upgrades that add utility (stun duration, slow) but no damage?
- How are ability upgrades that scale with spirit power scored at different spirit levels?
- What if all upgrades are taken — is the section hidden?

## Requirements

### Functional Requirements

- **FR-001**: System MUST iterate all unpicked ability upgrades and compute spirit DPS delta for each.
- **FR-002**: System MUST use existing `apply_ability_upgrades()` and `hero_total_spirit_dps()` functions.
- **FR-003**: System MUST respect the current AP budget (only show affordable upgrades).
- **FR-004**: Results MUST be sorted by DPS delta (highest first).
- **FR-005**: System MUST display results in the Build tab alongside the ability upgrade UI.
- **FR-006**: Clicking a suggestion MUST apply the upgrade and refresh recommendations.

### Key Entities

- **UpgradeCandidate**: Ability index, tier level, AP cost, spirit DPS delta.
- Uses existing: `HeroAbility`, `AbilityUpgrade`, `apply_ability_upgrades()`.

## Success Criteria

- **SC-001**: All upgrade candidates are scored in under 200ms.
- **SC-002**: Rankings change correctly as upgrades are applied.
- **SC-003**: AP budget is respected — no unaffordable upgrades are shown.
