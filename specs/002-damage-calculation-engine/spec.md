# Feature Specification: Damage Calculation Engine

**Feature Branch**: `002-damage-calculation-engine`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Bullet DPS Calculation (Priority: P1)

As a player theorycrafting builds, I want to calculate a hero's bullet DPS at any boon level with weapon bonuses so that I can compare heroes' baseline gun damage.

**Why this priority**: Bullet DPS is the most fundamental combat metric — every other calculation builds on it.

**Independent Test**: Call `DamageCalculator.calculate_bullet()` for any hero at boon 0 and boon 20 — returns `BulletResult` with correct per-bullet damage, fire rate, magazine, sustained DPS.

**Acceptance Scenarios**:

1. **Given** a hero with known base damage and damage_gain, **When** bullet DPS is calculated at boon level N, **Then** per-bullet damage equals `base_damage + (damage_gain × N)`.
2. **Given** a hero with pellet weapons (e.g., McGinnis), **When** DPS is calculated, **Then** damage per shot = `per_bullet_damage × effective_pellets`.
3. **Given** accuracy < 100% and headshot rate > 0, **When** `dps_with_accuracy()` is called, **Then** effective DPS accounts for both miss chance and headshot bonus.

---

### User Story 2 - Spirit Damage Calculation (Priority: P1)

As a spirit-focused player, I want to calculate ability damage including spirit scaling, cooldown, and amplifiers so that I can optimize spirit builds.

**Why this priority**: Spirit damage is the second core damage type, essential for ability-based heroes.

**Independent Test**: Call `DamageCalculator.calculate_spirit()` with known spirit power — returns `SpiritResult` with correct scaled damage and DPS.

**Acceptance Scenarios**:

1. **Given** an ability with `base_damage=100` and `spirit_scaling=1.0`, **When** spirit damage is calculated with 50 spirit power, **Then** total damage = `100 + (1.0 × 50) = 150`.
2. **Given** spirit amp of 20%, **When** spirit damage is calculated, **Then** final damage is multiplied by 1.20.
3. **Given** target has 30% spirit resist and 10% resist shred, **When** damage is calculated, **Then** effective resist = `30% - 10% = 20%` and damage is multiplied by 0.80.

---

### User Story 3 - Aggregate Spirit DPS (Priority: P1)

As a player, I want to see total spirit DPS across all abilities for a hero so that I can compare spirit builds holistically.

**Why this priority**: Individual ability DPS is insufficient — players need the full spirit DPS picture.

**Independent Test**: Call `hero_total_spirit_dps()` — returns sum of per-ability DPS for all abilities with cooldowns.

**Acceptance Scenarios**:

1. **Given** a hero with 3 damaging abilities, **When** total spirit DPS is calculated, **Then** result = sum of `(ability_damage / cooldown)` for each ability.
2. **Given** ability upgrades applied (T1/T2/T3), **When** total spirit DPS is calculated with `ability_upgrades` map, **Then** upgraded damage values and reduced cooldowns are reflected.

---

### User Story 4 - Melee Damage Calculation (Priority: P2)

As a player, I want to calculate melee DPS (light and heavy attacks) so that I can evaluate melee weaving and reload-cancel strategies.

**Why this priority**: Melee is secondary to gun/spirit but important for optimal DPS rotation.

**Independent Test**: Call `DamageCalculator.calculate_melee()` — returns `MeleeResult` with light/heavy damage per hit and DPS.

**Acceptance Scenarios**:

1. **Given** a hero with known melee stats, **When** melee is calculated at boon N, **Then** damage includes boon-scaled melee gain.

---

### User Story 5 - Resist Shred Stacking (Priority: P2)

As a player stacking shred items, I want shred from up to 5 sources to stack additively and cap at 100% so that I understand diminishing returns.

**Why this priority**: Correct shred behavior is critical for build accuracy.

**Independent Test**: Call `total_shred()` with 5 sources — verify additive stacking and 100% cap.

**Acceptance Scenarios**:

1. **Given** 3 shred sources (10%, 15%, 20%), **When** total shred is computed, **Then** result = 45%.
2. **Given** shred sources totaling 120%, **When** total shred is computed, **Then** result is clamped to 100%.

---

### User Story 6 - Ability Upgrade Application (Priority: P2)

As a player selecting ability tier upgrades, I want T1/T2/T3 bonuses applied to base damage, cooldown, and duration so that I can see how upgrades affect DPS.

**Why this priority**: Ability upgrades significantly change ability power curves.

**Independent Test**: Call `apply_ability_upgrades()` with tier selections — returns modified damage, cooldown, duration.

**Acceptance Scenarios**:

1. **Given** an ability with T1 upgrade granting +100 damage, **When** T1 is selected, **Then** base damage increases by 100.
2. **Given** T2 reduces cooldown by 3s, **When** T1+T2 are selected, **Then** both damage and cooldown changes apply.

---

### Edge Cases

- What happens when a hero has 0 abilities with damage (pure utility hero)?
- How does the system handle abilities with 0 cooldown (toggle abilities)?
- What if spirit scaling factor is negative?
- How does effective_pellets handle heroes with per-target pellet caps (e.g., Drifter)?

## Requirements

### Functional Requirements

- **FR-001**: System MUST calculate per-bullet damage at any boon level using `base_damage + (damage_gain × boons)`.
- **FR-002**: System MUST calculate bullet DPS accounting for fire rate, magazine size, reload time, and pellet count.
- **FR-003**: System MUST calculate effective DPS with accuracy and headshot multiplier.
- **FR-004**: System MUST calculate spirit damage with `base_damage + (spirit_scaling × current_spirit)`.
- **FR-005**: System MUST apply spirit amp as multiplicative modifier.
- **FR-006**: System MUST apply spirit resist and resist shred to final damage.
- **FR-007**: System MUST aggregate spirit DPS across all hero abilities.
- **FR-008**: System MUST support ability upgrade application (T1/T2/T3).
- **FR-009**: System MUST stack shred additively from up to 5 sources and clamp to 100%.
- **FR-010**: System MUST respect per-target pellet caps via `effective_pellets()`.
- **FR-011**: System MUST use hero-specific `crit_bonus_start` for headshot calculations.

### Key Entities

- **BulletResult**: Per-bullet damage, DPS, sustained DPS, magazine stats.
- **SpiritResult**: Scaled ability damage, DPS, cooldown.
- **MeleeResult**: Light/heavy damage per hit and DPS.
- **CombatConfig**: Boons, accuracy, headshot rate, weapon bonuses, spirit power.

## Success Criteria

- **SC-001**: Bullet DPS matches manual calculation for all heroes at boons 0, 10, 20, 35.
- **SC-002**: Spirit DPS correctly reflects ability upgrades and spirit scaling.
- **SC-003**: Shred stacking follows the 5-source additive cap rule exactly.
- **SC-004**: All calculations are pure functions with no side effects.

## Assumptions

- Hero base stats from the API are accurate and up-to-date.
- Boon levels run 0–35.
- Cooldown reduction is a fraction (0–1) applied multiplicatively.

## Implementation Files

- `deadlock_sim/engine/damage.py` — `DamageCalculator` class with all calculation methods
- `deadlock_sim/engine/primitives.py` — Low-level math: resist, falloff, amplifiers
- `deadlock_sim/models.py` — `BulletResult`, `SpiritResult`, `MeleeResult`, `CombatConfig`
