# Feature Specification: Patch Notes System

**Feature Branch**: `011-patch-notes-system`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Fetch Latest Patch Notes (Priority: P1)

As a developer or user, I want to fetch the latest Deadlock patch notes from the forum so that I can see what changed.

**Why this priority**: Patch awareness is critical for keeping simulation data accurate.

**Independent Test**: Call `fetch_latest_patch_url()` — returns a valid forum thread URL.

**Acceptance Scenarios**:

1. **Given** the forum changelog index is accessible, **When** latest patch URL is fetched, **Then** a valid URL to the most recent patch thread is returned.
2. **Given** the URL, **When** `fetch_patch_text(url)` is called, **Then** the raw patch notes text is returned.

---

### User Story 2 - Parse Patch Notes into Changes (Priority: P1)

As a user, I want patch notes parsed into individual change objects so that each hero/item change is structured and queryable.

**Why this priority**: Structured changes enable automated data comparison and alerts.

**Independent Test**: Call `parse_patch_notes(text)` — returns list of `PatchChange` objects with hero/item, stat, old/new values.

**Acceptance Scenarios**:

1. **Given** raw patch text containing "Infernus: Base damage increased from 10 to 12", **When** parsed, **Then** a `PatchChange` with hero="Infernus", stat="base_damage", old=10, new=12 is produced.
2. **Given** patch text with mixed hero and item changes, **When** parsed, **Then** both hero and item changes are captured.

---

### User Story 3 - Diff Patch vs Current Data (Priority: P2)

As a developer, I want to compare parsed patch changes against current cached data so that I can see which values are outdated.

**Why this priority**: Diff detection highlights stale data requiring API refresh.

**Independent Test**: Call `diff_patch()` with parsed changes — returns `PatchReport` showing matches, mismatches, and unknown fields.

**Acceptance Scenarios**:

1. **Given** a patch change increasing Infernus base damage, **When** diff runs against current data, **Then** the mismatch is flagged.
2. **Given** a patch change matching current data, **When** diff runs, **Then** it's marked as "already up-to-date".

---

### User Story 4 - Apply Patch to Loaded Data (Priority: P3)

As a developer, I want to apply parsed patch changes to in-memory game data so that I can test with patched values before the API updates.

**Why this priority**: Enables rapid testing after a patch without waiting for API propagation.

**Independent Test**: Call `apply_patch(changes)` — in-memory hero data reflects the patched values.

**Acceptance Scenarios**:

1. **Given** a patch change, **When** applied, **Then** the corresponding hero/item stat in memory is updated.

---

### Edge Cases

- What happens when the forum format changes and parsing fails?
- How does the system handle ambiguous patch note wording?
- What if a patch note references a hero or item not in the current data?

## Requirements

### Functional Requirements

- **FR-001**: System MUST fetch patch notes from the Deadlock forum changelog.
- **FR-002**: System MUST parse patch text into structured `PatchChange` objects via regex.
- **FR-003**: System MUST diff parsed changes against current cached data.
- **FR-004**: System MUST support applying changes to in-memory data.

### Key Entities

- **PatchChange**: Hero/item name, stat, old value, new value.
- **PatchReport**: Matches, mismatches, unknowns from diff.

## Success Criteria

- **SC-001**: Parser correctly extracts changes from at least the most recent 3 patch formats.
- **SC-002**: Diff correctly identifies matching and outdated values.

## Assumptions

- Deadlock forum patch notes follow a semi-consistent text format.
- Patch notes are publicly accessible without authentication.

## Implementation Files

- `deadlock_sim/patchnotes.py` — Fetch, parse, diff, apply
- `data/patches/` — Stored patch note text files
- `scripts/apply_patch.py` — Script for running patch application
