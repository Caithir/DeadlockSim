# Feature Specification: Defensive Item Scorer

**Feature Branch**: `022-defensive-item-scorer`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Score Defensive Items Against Specific Attacker (Priority: P1)

As a player being focused by an enemy, I want to see which defensive items give me the most survival time against that specific attacker's build so that I can counter-itemize effectively.

**Why this priority**: Defensive itemization is matchup-dependent — bullet resist is useless against a spirit caster. Scoring against a real attacker profile solves this.

**Independent Test**: Select an enemy hero with a saved build, run defensive scoring, verify items are ranked by survival time gain.

**Acceptance Scenarios**:

1. **Given** I select "Haze" with a saved gun build as my attacker, **When** defensive scoring runs, **Then** bullet resist and HP items rank higher than spirit resist items.
2. **Given** I select "Seven" with a saved spirit build as my attacker, **When** defensive scoring runs, **Then** spirit resist items rank highest.
3. **Given** scoring completes, **When** results are displayed, **Then** each item shows survival time delta (e.g., "+1.8s vs Haze").

---

### User Story 2 - Load Attacker from Saved Builds (Priority: P1)

As a player who knows the enemy's build, I want to load a saved build as the enemy attacker so that defensive scoring uses accurate damage profiles.

**Why this priority**: Enemy builds drastically change damage profiles. Base stats alone produce incorrect defensive recommendations.

**Independent Test**: Load a saved build for the attacker, verify scoring results change compared to base-stats-only scoring.

**Acceptance Scenarios**:

1. **Given** I load "Haze Gun Build" as the attacker, **When** defensive scoring runs, **Then** item scores reflect Haze's actual DPS with all item bonuses.
2. **Given** the attacker build includes spirit shred items, **When** defensive scoring runs, **Then** spirit resist items are valued less (since they'll be shredded).

---

### User Story 3 - Defensive Scoring Mode in Build Tab (Priority: P2)

As a player building my hero, I want to toggle the item scorer between offensive and defensive modes so that I can balance damage and survivability recommendations.

**Why this priority**: Players need to balance offense and defense — a mode toggle is the simplest way to serve both needs.

**Independent Test**: Toggle scoring mode from "Offensive" to "Defensive", verify item rankings change to prioritize EHP and survival time.

**Acceptance Scenarios**:

1. **Given** the item scorer is in offensive mode, **When** I switch to defensive mode, **Then** items are re-scored by survival time gain against the selected attacker.
2. **Given** defensive mode is active, **When** no attacker is selected, **Then** the system prompts "Select an attacker to score defensive items."

---

### Edge Cases

- What about items that provide both offense and defense (e.g., Leech) — how are they scored?
- How is lifesteal valued in survival time calculations?
- What happens when the attacker build uses items with conditional stats (e.g., shred after 3 hits)?
- How are active defensive items (e.g., Metal Skin) scored when they have cooldowns?

## Requirements

### Functional Requirements

- **FR-001**: System MUST add a "defensive" scoring mode to the existing ItemScorer.
- **FR-002**: Defensive scoring MUST accept an attacker configuration (hero + saved build).
- **FR-003**: System MUST score items by survival time delta against the attacker's damage profile.
- **FR-004**: System MUST load attacker builds from the saved builds system.
- **FR-005**: Build tab MUST include a toggle between offensive and defensive scoring modes.
- **FR-006**: System MUST handle mixed offense/defense items by showing both DPS delta and survival time delta.

### Key Entities

- **ScoringConfig**: Extended with scoring_mode (offensive/defensive) and attacker config.
- **DefensiveScore**: Survival time delta, EHP delta, per-soul efficiency, attacker profile used.
- Uses existing: `ItemScorer`, `ScoringConfig`, `CombatSimulator`, saved build infrastructure.

## Success Criteria

- **SC-001**: Defensive scoring against a gun-heavy attacker ranks bullet resist items above spirit resist items.
- **SC-002**: Defensive scoring against a spirit-heavy attacker ranks spirit resist items above bullet resist items.
- **SC-003**: Survival time deltas are consistent with running the attacker's build in a full simulation.
- **SC-004**: Mode toggle updates item rankings in under 1 second (fast mode) or under 5 seconds (sim mode).
