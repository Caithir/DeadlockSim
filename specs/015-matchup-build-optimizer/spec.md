# Feature Specification: Matchup-Specific Build Optimizer

**Feature Branch**: `015-matchup-build-optimizer`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Defender-Aware Item Scoring (Priority: P1)

As a player building against a specific enemy, I want the item scorer to evaluate items against a chosen defender hero so that my build is optimized for the matchup I'm facing.

**Why this priority**: Itemization in Deadlock is matchup-dependent. Scoring against a generic dummy produces suboptimal recommendations.

**Independent Test**: Select a defender hero in the Build tab, run item scoring, verify scores differ from no-defender scoring.

**Acceptance Scenarios**:

1. **Given** I am building Infernus, **When** I select "Seven" as my matchup target, **Then** item scores reflect DPS against Seven's HP/resist profile.
2. **Given** I score items against a high-spirit-resist defender, **When** compared to scoring against a low-resist defender, **Then** spirit shred items rank higher against the high-resist target.
3. **Given** no defender is selected, **When** scoring runs, **Then** it falls back to the default generic defender behavior.

---

### User Story 2 - Load Defender from Saved Builds (Priority: P1)

As a player who knows the enemy's build, I want to load a saved build as the defender so that scoring accounts for the enemy's actual items and stats.

**Why this priority**: Enemy builds drastically change damage profiles — base stats alone are insufficient for accurate matchup optimization.

**Independent Test**: Load a saved build as the defender, verify item scoring uses the defender's build stats (HP, resists from items).

**Acceptance Scenarios**:

1. **Given** I have a saved "Haze Gun Build", **When** I load it as the defender, **Then** item scoring uses Haze's base stats plus all item bonuses from that build.
2. **Given** the defender build includes resist items, **When** I score shred items, **Then** shred items rank higher than if the defender had no resists.

---

### User Story 3 - Matchup Optimizer Integration (Priority: P2)

As a player, I want the BuildOptimizer to find the best items specifically against my selected matchup so that I get a complete build recommendation for the fight.

**Why this priority**: Extends per-item scoring to full build optimization with matchup awareness.

**Independent Test**: Run BuildOptimizer with a defender selected, verify the recommended build differs from the generic recommendation.

**Acceptance Scenarios**:

1. **Given** I select a defender hero, **When** I run "Optimize for DPS", **Then** the recommended items are optimized against that specific defender.

---

### Edge Cases

- What if the defender's saved build uses items that have been patched/removed?
- How should scoring handle defender ability upgrades (T1/T2/T3)?
- What happens when the defender and attacker are the same hero?

## Requirements

### Functional Requirements

- **FR-001**: Build tab MUST include a defender hero selector for matchup-specific scoring.
- **FR-002**: System MUST support loading a saved build for the defender.
- **FR-003**: ItemScorer MUST accept a defender configuration (hero + build) and score against it.
- **FR-004**: BuildOptimizer MUST route through the matchup-aware scorer when a defender is selected.
- **FR-005**: System MUST fall back to default scoring when no defender is selected.

### Key Entities

- **Defender config**: Hero + optional saved build reference.
- **ScoringConfig**: Extended with defender hero and defender build fields.

## Success Criteria

- **SC-001**: Item scores visibly change when different defenders are selected.
- **SC-002**: Saved build loading for defender works with all existing saved builds.
- **SC-003**: Shred items rank higher against high-resist defenders than low-resist defenders.
