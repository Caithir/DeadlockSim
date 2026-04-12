# Tasks: Hero Gun DPS Rankings

**Input**: Design documents from `/specs/020-hero-gun-dps-rankings/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Included — the plan explicitly defines engine and GUI test cases.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Bug Fix — Blocking Prerequisite)

**Purpose**: Fix `snapshot()` DPS calculation that overstates pellet-based hero damage. This bug affects all downstream consumers (`rank_heroes()`, `compare_two()`, `scaling_curve()`), so it MUST be fixed before any ranking work begins.

**⚠️ CRITICAL**: All ranking results will be incorrect until this phase is complete.

- [ ] T001 [US1] Fix `HeroMetrics.snapshot()` to use `DamageCalculator.effective_pellets(hero)` instead of `hero.pellets` in `deadlock_sim/engine/heroes.py` (line 29: `per_bullet = bullet_dmg * hero.pellets`)
- [ ] T002 [US1] Add `test_effective_pellets_in_snapshot` in `tests/test_engine.py` — verify `HeroMetrics.snapshot()` uses `effective_pellets()` by checking Drifter's DPS reflects 1 pellet per target, not raw pellet count

**Checkpoint**: `snapshot()` returns correct DPS for pellet-based heroes. All existing tests still pass.

---

## Phase 2: User Story 1 — Gun DPS Comparison at Min and Max Boons (Priority: P1) 🎯 MVP

**Goal**: Rank all heroes by raw gun DPS at boon 0 and boon 35 (no items), displayed as a sortable table.

**Independent Test**: Call `ComparisonEngine.gun_dps_rankings(heroes)` and verify all heroes appear with correct DPS values sorted by boon 35 DPS descending.

### Data Model

- [ ] T003 [P] [US1] Add `GunDpsRanking` dataclass to `deadlock_sim/models.py` — fields: `hero_name: str`, `dps_boon_0: float`, `dps_boon_35: float`, `rank_boon_0: int`, `rank_boon_35: int`

### Engine

- [ ] T004 [US1] Add `gun_dps_rankings()` static method to `ComparisonEngine` in `deadlock_sim/engine/comparison.py` — calls `rank_heroes(heroes, "dps", boon_level=0)` and `rank_heroes(heroes, "dps", boon_level=35)`, merges results into `list[GunDpsRanking]` sorted by `dps_boon_35` descending (depends on T001, T003)

### Tests for User Story 1

- [ ] T005 [P] [US1] Add `test_gun_dps_rankings_returns_all_heroes` in `tests/test_engine.py` — call `gun_dps_rankings()` and verify every hero in `load_heroes()` has an entry
- [ ] T006 [P] [US1] Add `test_gun_dps_rankings_sorted_by_boon_35` in `tests/test_engine.py` — verify result list is sorted descending by `dps_boon_35`
- [ ] T007 [P] [US1] Add `test_gun_dps_rankings_boon_35_gte_boon_0` in `tests/test_engine.py` — verify `dps_boon_35 >= dps_boon_0` for every hero (damage_gain is non-negative)

**Checkpoint**: `gun_dps_rankings()` returns correct, complete, sorted rankings for all heroes. Engine tests pass. MVP is usable via CLI (`display_rankings(heroes, "dps", boon_level=N)`).

---

## Phase 3: User Story 2 — Visual Bar Chart (Priority: P2)

**Goal**: Add a "Rankings" GUI tab with a horizontal bar chart and sortable table showing gun DPS for all heroes at boon 0 and boon 35.

**Independent Test**: Navigate to Rankings tab, verify bar chart and table render with all heroes visible.

### GUI Implementation

- [ ] T008 [US2] Add `_build_rankings_tab()` function in `deadlock_sim/ui/gui.py` — builds horizontal bar chart via `ui.echart` (hero names on Y-axis, two bars per hero: boon 0 lighter, boon 35 darker, tooltip on hover) and sortable `ui.table` (columns: Rank, Hero, DPS Boon 0, DPS Boon 35) (depends on T004)
- [ ] T009 [US2] Wire new "Rankings" tab in main page layout in `deadlock_sim/ui/gui.py` — add `ui.tab("Rankings")` after "Hero Stats" tab (~line 3891) and connect tab panel to `_build_rankings_tab()` (depends on T008)

### Tests for User Story 2

- [ ] T010 [US2] Add `test_rankings_tab_loads` in `tests/test_gui.py` — navigate to Rankings tab, verify bar chart and table render with hero names visible (depends on T009)
- [ ] T011 [US2] Add `test_rankings_table_has_all_heroes` in `tests/test_gui.py` — count table rows and verify count matches number of heroes (depends on T009)

**Checkpoint**: Rankings tab renders correctly with bar chart and table showing consistent data for all heroes.

---

## Phase 4: Polish & Validation

**Purpose**: Final verification across both interfaces.

- [ ] T012 [US1] Run full engine test suite via `python -m pytest tests/test_engine.py -v` and verify all new and existing tests pass (depends on T005, T006, T007)
- [ ] T013 [US2] Run full GUI test suite via `python -m pytest tests/test_gui.py -v` and verify rankings tab tests pass (depends on T010, T011)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Bug Fix)**: No dependencies — start immediately. BLOCKS all other phases.
- **Phase 2 (US1 — Engine + Data)**: Depends on Phase 1 completion (T001). T003 can start in parallel with T001.
- **Phase 3 (US2 — GUI)**: Depends on T004 from Phase 2.
- **Phase 4 (Validation)**: Depends on all implementation and test tasks.

### Task Dependency Graph

```
T001 (fix snapshot) ──┬──→ T002 (test fix)
                      │
T003 (dataclass) [P] ─┼──→ T004 (gun_dps_rankings) ──┬──→ T005, T006, T007 [P] (engine tests)
                      │                               │
                      │                               └──→ T008 (GUI tab) → T009 (wire tab) → T010, T011 [P] (GUI tests)
                      │
                      └──→ T012, T013 (validation)
```

### Parallel Opportunities

- **T003** (dataclass) can run in parallel with **T001** (bug fix) — different files, no dependency
- **T005, T006, T007** can all run in parallel — independent test functions in same file
- **T010, T011** can run in parallel — independent GUI test functions

### Within Each User Story

- Bug fix (T001) before engine method (T004)
- Dataclass (T003) before engine method (T004)
- Engine method (T004) before GUI (T008)
- GUI function (T008) before wiring (T009)
- Implementation before tests where tests validate the implementation

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Fix `snapshot()` bug (T001, T002)
2. Complete Phase 2: Add `GunDpsRanking` + `gun_dps_rankings()` (T003, T004, T005–T007)
3. **STOP and VALIDATE**: Run engine tests, verify CLI `display_rankings()` shows correct values
4. MVP is deliverable — CLI users can compare DPS at any boon level

### Incremental Delivery

1. Phase 1 → Bug fix landed (benefits all existing callers too)
2. Phase 2 → Engine MVP ready (T003–T007)
3. Phase 3 → GUI bar chart + table (T008–T011)
4. Phase 4 → Full validation pass

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- The bug fix in T001 is a correctness fix that benefits all existing callers of `snapshot()`, not just this feature
- CLI already supports `display_rankings(heroes, "dps", boon_level=N)` — no CLI changes needed
- `RankEntry` dataclass already exists in `deadlock_sim/engine/comparison.py` — reused by `gun_dps_rankings()`
- Commit after each task or logical group
