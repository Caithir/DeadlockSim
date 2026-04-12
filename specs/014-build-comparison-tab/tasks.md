# Tasks: Build Comparison Tab

**Input**: Design documents from `/specs/014-build-comparison-tab/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Data Models (Shared Infrastructure)

**Purpose**: New dataclasses that all subsequent phases depend on

- [ ] [T001] [P] [US1] Add `StatDelta` dataclass to `deadlock_sim/models.py` — fields: `stat_name: str`, `value_a: float`, `value_b: float`, `delta: float`, `higher_is_better: bool = True`
- [ ] [T002] [P] [US1] Add `BuildComparisonResult` dataclass to `deadlock_sim/models.py` — fields: `result_a: BuildResult`, `result_b: BuildResult`, `deltas: list[StatDelta]`, `items_only_a: list[str]`, `items_only_b: list[str]`, `items_shared: list[str]`

**Checkpoint**: Data models ready — engine and GUI tasks can proceed

---

## Phase 2: Engine — `compare_builds()` (Blocking Prerequisite)

**Purpose**: Pure calculation logic for build comparison. Must be complete before GUI can display results.

**⚠️ CRITICAL**: No GUI comparison work can begin until this phase is complete

- [ ] [T003] [US1] Add `compare_builds()` static method to `ComparisonEngine` class in `deadlock_sim/engine/comparison.py` — accepts hero, two Builds, boon/accuracy/headshot/defender params, per-build ability_upgrades/cooldown_reduction/spirit_amp/spirit_resist_shred. Calls `BuildEngine.evaluate_build()` for each build, computes spirit DPS via `DamageCalculator.hero_total_spirit_dps()`, builds `StatDelta` list for: Bullet DPS (sustained), Spirit DPS, Combined DPS, EHP, TTK (if defender), Magazine Size, Fire Rate. Computes item set differences. Returns `BuildComparisonResult`.
- [ ] [T004] [US1] Add `_reconstruct_build()` helper function to `deadlock_sim/engine/comparison.py` — parses a saved build dict into `(hero_name, Build, ability_upgrades, extra_souls)` tuple, silently skips missing items for post-patch compatibility
- [ ] [T005] [US1] Export new symbols from `deadlock_sim/engine/__init__.py` — ensure `compare_builds` and `_reconstruct_build` (or public wrapper) are importable

**Checkpoint**: Engine comparison logic ready — all tests and GUI work can proceed

---

## Phase 3: User Story 1 — Side-by-Side Build Diff (Priority: P1) 🎯 MVP

**Goal**: Compare two builds side-by-side with stat deltas showing DPS, EHP, TTK, spirit DPS differences with color-coded directional indicators

**Independent Test**: Load two saved builds for the same hero, verify a two-column layout shows all key stats with green/red delta arrows

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] [T006] [P] [US1] Add `test_compare_builds_same_hero` to `tests/test_engine.py` — create two Builds for the same hero with different items, call `ComparisonEngine.compare_builds()`, verify deltas are mathematically correct (`value_a - value_b`), verify `higher_is_better` is `True` for DPS/EHP and `False` for TTK
- [ ] [T007] [P] [US1] Add `test_compare_builds_item_diff` to `tests/test_engine.py` — create two Builds with overlapping and unique items, verify `items_only_a`, `items_only_b`, `items_shared` are correct sets
- [ ] [T008] [P] [US1] Add `test_comparison_tab_loads` to `tests/test_gui.py` — navigate to the Compare tab, verify two dropdown selectors appear

### Implementation for User Story 1

- [ ] [T009] [US1] Register the "Compare" tab in `deadlock_sim/ui/gui.py` `run_gui()` — add `tab_compare = ui.tab("Compare")` between "Saved Builds" and "Simulation" tabs (~line 3889), add corresponding `ui.tab_panel(tab_compare)` block that calls `_build_comparison_tab(state)`
- [ ] [T010] [US1] Create `_build_comparison_tab(state: _PageState)` builder function in `deadlock_sim/ui/gui.py` — scaffold the three-column layout (Build A stats | Deltas | Build B stats) with placeholder content
- [ ] [T011] [US1] Implement saved-build dropdown selectors in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — two `ui.select` dropdowns populated by reading `deadlocksim_saved_builds` from localStorage (reuse `_LOCALSTORAGE_KEY` and pattern from `_build_saved_builds_tab`), show hero name + build label in each option
- [ ] [T012] [US1] Implement build loading and comparison execution in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — on dropdown selection change, reconstruct both builds via `_reconstruct_build()`, call `ComparisonEngine.compare_builds()`, store results in local tab state
- [ ] [T013] [US1] Implement stat delta display in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — render each `StatDelta` row in the center column with: stat name, delta value, directional arrow (▲/▼), color coding (green `#4caf50` for better, red `#f44336` for worse, based on `higher_is_better` and `delta` sign)
- [ ] [T014] [US1] Implement build stat columns in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — render Build A and Build B stat values (DPS, EHP, TTK, spirit DPS, bullet DPS, magazine size, fire rate) in left and right columns respectively
- [ ] [T015] [US1] Implement item difference display in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — render color-coded chips: amber for `items_only_a`, blue for `items_only_b`, gray for `items_shared`
- [ ] [T016] [US1] Add cross-hero info banner in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — when builds are for different heroes, show subtle info banner: "Comparing builds for different heroes — stat deltas reflect hero base stat differences too"

**Checkpoint**: User Story 1 complete — two saved builds can be loaded and compared side-by-side with stat deltas and item diffs

---

## Phase 4: User Story 2 — Load from Saved Builds (Priority: P1) 🎯 MVP

**Goal**: Select builds from saved builds for comparison without rebuilding from scratch

**Independent Test**: Open comparison tab, select two saved builds from dropdowns, verify both load correctly with hero, items, ability upgrades, and boon level restored

> Note: Most of US2's functionality is already implemented in US1 tasks (T011, T012). This phase covers the remaining acceptance criteria.

### Tests for User Story 2

- [ ] [T017] [P] [US2] Add `test_comparison_tab_with_builds` to `tests/test_gui.py` — pre-populate localStorage with two saved builds, open Compare tab, select both builds from dropdowns, verify stat rows render with correct values matching expected `BuildResult` outputs

### Implementation for User Story 2

- [ ] [T018] [US2] Implement full build restoration in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — ensure dropdown selection restores hero, items, ability upgrades, and boon level (extra_souls) from saved build data; display hero name and item list for each loaded build in the stat columns
- [ ] [T019] [US2] Handle edge case of saved builds referencing missing items in `deadlock_sim/ui/gui.py` — when a saved build references an item that no longer exists (post-patch), silently skip it and show a warning chip "(N items unavailable)" next to the build's item list

**Checkpoint**: User Stories 1 AND 2 complete — saved builds load fully into comparison view

---

## Phase 5: User Story 3 — Single Item Swap Impact (Priority: P2)

**Goal**: Swap a single item in one build and see stat deltas update immediately without saving a new build

**Independent Test**: Load a build, swap one item, verify stat deltas update in real-time

### Tests for User Story 3

- [ ] [T020] [P] [US3] Add `test_compare_builds_after_item_swap` to `tests/test_engine.py` — start with a build, swap one item, call `compare_builds()` with original vs modified build, verify all deltas reflect the single-item change

### Implementation for User Story 3

- [ ] [T021] [US3] Add Quick Swap UI section to `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — below the comparison columns, add a "Quick Swap (Build A)" section with two dropdowns: "Remove item" (populated from Build A's current items) and "Add item" (populated from all shop items) and an "Apply Swap" button
- [ ] [T022] [US3] Implement item swap logic in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — on "Apply Swap" click, mutate the loaded build's item list in memory (remove selected item, add new item), re-run `ComparisonEngine.compare_builds()`, refresh all stat deltas and item diff display. Do NOT persist to localStorage.
- [ ] [T023] [US3] Add Quick Swap for Build B in `_build_comparison_tab()` in `deadlock_sim/ui/gui.py` — duplicate the swap UI section for Build B, allowing independent item swaps on either side

**Checkpoint**: All user stories complete — full comparison with item swap capability

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Performance, UX refinements, and documentation

- [ ] [T024] [P] Verify comparison load time < 1s (SC-001) — add timing assertion or manual verification that loading two builds and displaying comparison completes under 1 second
- [ ] [T025] [P] Verify item swap delta update < 500ms (SC-003) — add timing assertion or manual verification that item swap delta recalculation completes under 500ms
- [ ] [T026] [P] Add tab auto-refresh in `deadlock_sim/ui/gui.py` — wire `_on_tab_change` to refresh saved builds list when Compare tab is selected (similar to existing Saved Builds tab refresh at ~line 3912)
- [ ] [T027] [P] Run full test suite — execute `pytest tests/` and verify all existing tests still pass alongside new comparison tests

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Data Models)**: No dependencies — can start immediately
- **Phase 2 (Engine)**: Depends on Phase 1 — BLOCKS GUI and test implementation
- **Phase 3 (US1 - Side-by-Side Diff)**: Depends on Phase 2 — tests can be written first (TDD)
- **Phase 4 (US2 - Load from Saved)**: Depends on Phase 3 core (T009–T012)
- **Phase 5 (US3 - Item Swap)**: Depends on Phase 3 completion
- **Phase 6 (Polish)**: Depends on all story phases being complete

### Within Each Phase

- T001, T002 are parallel (different dataclasses, same file but non-overlapping)
- T003 depends on T001 + T002 (uses `StatDelta` and `BuildComparisonResult`)
- T004 can parallel with T003 (helper function, no dependency on compare_builds)
- T006, T007, T008 are parallel (independent test functions)
- T009 must come before T010–T016 (tab registration before tab content)
- T010 must come before T011–T016 (scaffold before detailed content)
- T011, T012 are sequential (dropdowns before selection handlers)
- T013, T014, T015 can parallel after T012 (different UI sections)
- T021 before T022 (UI before logic)
- T022 before T023 (Build A swap before duplicating for Build B)

### Parallel Opportunities

```text
# Phase 1: Both model tasks in parallel
T001 ─┬─→ T003
T002 ─┘

# Phase 2: T003 and T004 can partially overlap
T003 ─→ T005
T004 ─→ T005

# Phase 3: Tests in parallel, then sequential GUI build
T006 ─┐
T007 ─┤ (all parallel)
T008 ─┘
T009 → T010 → T011 → T012 → T013 ─┐
                                T014 ─┤ (parallel)
                                T015 ─┤
                                T016 ─┘

# Phase 5: Sequential swap implementation
T020 (test, parallel with T021)
T021 → T022 → T023

# Phase 6: All polish tasks parallel
T024, T025, T026, T027 (all parallel)
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Data Models (T001–T002)
2. Complete Phase 2: Engine (T003–T005)
3. Complete Phase 3: US1 Side-by-Side Diff (T006–T016)
4. Complete Phase 4: US2 Saved Build Loading (T017–T019)
5. **STOP and VALIDATE**: Both P1 stories fully functional and testable

### Incremental Delivery

1. Phase 1 + 2 → Engine ready
2. Phase 3 → Side-by-side comparison works (MVP!)
3. Phase 4 → Full saved build integration
4. Phase 5 → Item swap (P2 enhancement)
5. Phase 6 → Polish and performance validation

---

## Notes

- [P] tasks = different files or non-overlapping sections, no dependencies
- The existing `ComparisonEngine` class in `engine/comparison.py` handles hero-vs-hero comparison; this feature adds build-vs-build comparison to the same class
- GUI tab follows the existing `_build_*_tab()` builder pattern used by all other tabs
- Saved builds use existing `deadlocksim_saved_builds` localStorage key — no schema changes needed
- CLI parity is explicitly deferred per Constitution Principle IV exception (documented in plan.md)
- Commit after each task or logical group
