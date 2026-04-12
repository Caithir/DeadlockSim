# Feature Specification: API Data Pipeline

**Feature Branch**: `001-api-data-pipeline`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - Fetch Game Data from API (Priority: P1)

As a user launching DeadlockSim for the first time, I want the application to automatically download all hero and item data from the Deadlock Assets API so that I have accurate, up-to-date game data without manual setup.

**Why this priority**: Without game data, no calculations or UI features function at all.

**Independent Test**: Launch app with empty `data/api_cache/` — heroes and items load successfully.

**Acceptance Scenarios**:

1. **Given** no local cache exists, **When** the app starts, **Then** it fetches heroes and items from `assets.deadlock-api.com` and saves JSON to `data/api_cache/`.
2. **Given** the API is unreachable, **When** the app starts with existing cache, **Then** it loads from the local cache without errors.

---

### User Story 2 - Parse API Data into Domain Models (Priority: P1)

As a developer consuming game data, I want raw API JSON parsed into typed Python dataclasses so that all downstream code works with validated, structured objects rather than raw dicts.

**Why this priority**: All engine calculations depend on typed hero/item models.

**Independent Test**: Call `load_heroes()` and `load_items()` — returns `dict[str, HeroStats]` and `dict[str, Item]` with all expected fields populated.

**Acceptance Scenarios**:

1. **Given** cached JSON files exist, **When** `load_heroes()` is called, **Then** it returns a dict of `HeroStats` objects with abilities, upgrades, and scaling stats fully populated.
2. **Given** cached JSON files exist, **When** `load_items()` is called, **Then** it returns a dict of `Item` objects with 60+ stat properties correctly mapped from API field names.
3. **Given** an API field is missing or has an unexpected type, **When** parsing occurs, **Then** a `ParseWarning` is recorded but parsing continues without crashing.

---

### User Story 3 - Refresh Cached Data (Priority: P2)

As a user, I want to manually refresh cached game data so that I get the latest hero/item changes after a game patch.

**Why this priority**: Data freshness matters after patches but isn't needed for core functionality.

**Independent Test**: Call `refresh_all_data()` — new JSON files are written to cache.

**Acceptance Scenarios**:

1. **Given** cached data exists, **When** `refresh_all_data()` is called, **Then** all cache files are overwritten with fresh API responses.

---

### Edge Cases

- What happens when the API returns an empty heroes list?
- How does the system handle API rate limiting or 5xx errors?
- What if a hero or item has new fields not yet mapped in `data.py`?

## Requirements

### Functional Requirements

- **FR-001**: System MUST fetch hero data from `assets.deadlock-api.com/v2/heroes`.
- **FR-002**: System MUST fetch item data from `assets.deadlock-api.com/v2/items`.
- **FR-003**: System MUST cache all API responses as JSON in `data/api_cache/`.
- **FR-004**: System MUST parse cached JSON into `HeroStats` and `Item` dataclasses.
- **FR-005**: System MUST map 60+ API property names to model field names (e.g., `BonusWeaponPower` → `weapon_damage_pct`).
- **FR-006**: System MUST load `HeroAbility` and `AbilityUpgrade` (T1/T2/T3) for each hero.
- **FR-007**: System MUST auto-detect cache and load from disk if available.
- **FR-008**: System MUST record parse warnings for unmapped or malformed fields without crashing.

### Key Entities

- **HeroStats**: Hero with base stats, abilities, scaling curves, weapon data.
- **HeroAbility**: Individual ability with base damage, cooldown, spirit scaling, upgrades.
- **AbilityUpgrade**: T1/T2/T3 ability upgrade with stat deltas.
- **Item**: Game item with cost, category, tier, 60+ stat properties, active/passive flag.
- **ShopTier**: Tier-based shop bonus configuration.
- **ParseWarning**: Recorded warning for data parsing issues.
- **ParseResult**: Container for loaded data + any parse warnings.

## Success Criteria

- **SC-001**: All heroes from the live API parse without errors.
- **SC-002**: All items from the live API parse without errors.
- **SC-003**: Cache load+parse completes in under 1 second.
- **SC-004**: Parse warnings are logged but never cause data loading to fail.

## Assumptions

- The Deadlock Assets API at `assets.deadlock-api.com` remains available and stable.
- API response format is consistent with current v2 endpoints.
- Local filesystem access is available for cache storage.

## Implementation Files

- `deadlock_sim/api_client.py` — HTTP fetch + cache persistence
- `deadlock_sim/data.py` — JSON→dataclass parsing, property mapping
- `deadlock_sim/models.py` — All domain dataclasses
- `data/api_cache/` — Cached JSON files (heroes.json, items.json, etc.)
