# Tasks: TTK Heatmap

**Input**: Design documents from `/specs/017-ttk-heatmap/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Integration test is specified in the plan — included below.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Verify that the engine layer already supports everything needed — no new engine code is required per the plan.

- [ ] [T001] [US1] Verify `ComparisonEngine.cross_ttk_matrix()` signature and return type in `deadlock_sim/engine/comparison.py` — confirm it accepts `heroes`, `config`, `hero_names` and returns `dict[str, dict[str, float]]`

**Checkpoint**: Engine API confirmed — GUI and CLI implementation can begin.

---

## Phase 2: User Story 1 — Cross-Hero TTK Grid (Priority: P1) 🎯 MVP

**Goal**: Render an N×N color-coded heatmap of TTK values in a new GUI tab and a new CLI menu option.

**Independent Test**: Select 5 heroes, click "Generate", verify a 5×5 colored grid appears with rows=attackers, columns=defenders, cells colored by TTK.

### Implementation for User Story 1

- [ ] [T002] [US1] Add `_ttk_cell_color()` inline helper function in `deadlock_sim/ui/gui.py` — linear interpolation mapping TTK to green→yellow→red hex color
- [ ] [T003] [US1] Add `_build_ttk_heatmap_tab()` function in `deadlock_sim/ui/gui.py` — hero multi-select (2–10), boon slider, accuracy slider, Generate button, heatmap HTML table rendering with colored cells and hover tooltips
- [ ] [T004] [US1] Register "TTK Heatmap" tab in `run_gui()` in `deadlock_sim/ui/gui.py` — add `tab_heatmap = ui.tab("TTK Heatmap")` to tab bar and `_build_ttk_heatmap_tab()` in a new `ui.tab_panel(tab_heatmap)` block
- [ ] [T005] [P] [US1] Add `display_ttk_matrix()` function in `deadlock_sim/ui/cli.py` — prompt for hero subset (2–10), boon level, accuracy; call `ComparisonEngine.cross_ttk_matrix()`; print aligned ASCII table with TTK values
- [ ] [T006] [US1] Add "TTK Matrix" entry to `MAIN_MENU` list in `deadlock_sim/ui/cli.py` (after "Hero Rankings") and add dispatch branch in `run_cli()` `while` loop

### Edge Cases for User Story 1

- [ ] [T007] [US1] Handle TTK=0 / infinite TTK cells in `_build_ttk_heatmap_tab()` in `deadlock_sim/ui/gui.py` — display "∞" with gray background for cells where the hero cannot kill the target
- [ ] [T008] [US1] Handle TTK=0 / infinite TTK values in `display_ttk_matrix()` in `deadlock_sim/ui/cli.py` — display "∞" or "N/A" in ASCII table for unkillable matchups

### Tests for User Story 1

- [ ] [T009] [US1] Add `test_ttk_heatmap_tab_present` test in `tests/test_gui.py` — verify "TTK Heatmap" tab appears in the tab bar and is clickable
- [ ] [T010] [US1] Add `test_ttk_heatmap_generation` integration test in `tests/test_gui.py` — navigate to TTK Heatmap tab, select 3–4 heroes, set boon level, click Generate, assert heatmap table exists with expected hero names and numeric TTK values matching regex `\d+\.\d+s`
- [ ] [T011] [US1] Update `TABS` list in `tests/test_gui.py` to include "TTK Heatmap" so existing `test_all_tabs_present` and `test_tab_clickable` parametrized tests cover the new tab

**Checkpoint**: At this point, User Story 1 should be fully functional — an N×N colored heatmap renders in the GUI and an ASCII table prints in the CLI.

---

## Phase 3: User Story 2 — Boon Level Selector (Priority: P1) 🎯 MVP

**Goal**: Allow users to change the boon level and regenerate the heatmap to see how matchups shift across game stages.

**Independent Test**: Generate at boon 5, change to boon 25, regenerate, verify cell values change.

### Implementation for User Story 2

> **Note**: The boon slider is structurally built as part of T003 (heatmap tab layout). This phase focuses on verifying that changing the boon value and regenerating produces updated results.

- [ ] [T012] [US2] Verify boon slider value flows through `CombatConfig(boons=boon_val)` to `cross_ttk_matrix()` in `_build_ttk_heatmap_tab()` in `deadlock_sim/ui/gui.py` — ensure regeneration with a different boon level produces different TTK values in the heatmap

### Tests for User Story 2

- [ ] [T013] [US2] Add `test_ttk_heatmap_boon_change` integration test in `tests/test_gui.py` — generate heatmap at one boon level, change slider, regenerate, assert at least one cell value differs

**Checkpoint**: Boon level changes are reflected in the heatmap upon regeneration.

---

## Phase 4: User Story 3 — Hero Subset Selection (Priority: P2)

**Goal**: Allow selecting a specific subset of 2–10 heroes instead of computing all heroes, keeping generation fast and the grid readable.

**Independent Test**: Select 8 heroes from the full roster, verify only those 8 appear in the grid.

### Implementation for User Story 3

> **Note**: The multi-select hero picker is structurally built as part of T003. This phase adds validation and enforcement of the 2–10 hero constraint.

- [ ] [T014] [US3] Add validation in `_build_ttk_heatmap_tab()` in `deadlock_sim/ui/gui.py` — if fewer than 2 heroes are selected when Generate is clicked, show a notification/message prompting the user to select at least 2 heroes; cap selection at 10
- [ ] [T015] [P] [US3] Add validation in `display_ttk_matrix()` in `deadlock_sim/ui/cli.py` — reject input if fewer than 2 or more than 10 heroes are selected; prompt user to re-enter

### Tests for User Story 3

- [ ] [T016] [US3] Add `test_ttk_heatmap_minimum_heroes_validation` test in `tests/test_gui.py` — attempt to generate with 0 or 1 heroes selected, assert that a validation message appears and no heatmap is rendered

**Checkpoint**: Hero subset selection is validated in both GUI and CLI. All user stories are independently functional.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final cleanup affecting multiple user stories.

- [ ] [T017] [P] Verify mirror matchup display (hero vs. same hero) renders correctly in both GUI and CLI — diagonal cells should show valid TTK values
- [ ] [T018] [P] Verify 2×2 minimum grid renders cleanly in `deadlock_sim/ui/gui.py` — no layout issues with smallest possible heatmap
- [ ] [T019] Performance validation — generate an 8×8 heatmap and verify it completes in under 5 seconds (SC-001)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Foundational)**: No dependencies — start immediately
- **Phase 2 (US1 — Core Heatmap)**: Depends on Phase 1 completion
- **Phase 3 (US2 — Boon Selector)**: Depends on Phase 2 (T003 builds the slider)
- **Phase 4 (US3 — Subset Selection)**: Depends on Phase 2 (T003 builds the multi-select)
- **Phase 5 (Polish)**: Depends on all user stories being complete

### Within Phase 2 (User Story 1)

```
T001 ──► T002 ──► T003 ──► T004 ──► T007 ──► T009, T010, T011
                    │
                    └──► T005 [P] ──► T006 ──► T008
```

- T002 (color helper) must precede T003 (heatmap tab uses it)
- T003 (heatmap tab function) must precede T004 (tab registration)
- T005 (CLI function) can run in parallel with T002–T004 (different file)
- T006 (CLI menu entry) depends on T005
- T007, T008 (edge cases) depend on their respective implementations
- T009, T010, T011 (tests) depend on T004 (tab must be registered)

### Parallel Opportunities

- T005 (CLI) can run in parallel with T002–T004 (GUI) — different files
- T009, T010, T011 (GUI tests) can run in parallel with T008 (CLI edge cases)
- T014 (GUI validation) can run in parallel with T015 (CLI validation) — different files
- T017, T018, T019 (polish) can run in parallel with each other

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Verify engine API
2. Complete Phase 2: Core heatmap in GUI + CLI
3. Complete Phase 3: Boon selector verification
4. **STOP and VALIDATE**: Generate heatmaps at different boon levels

### Incremental Delivery

1. Phase 1 → Engine confirmed
2. Phase 2 → Core heatmap working → Test independently (MVP!)
3. Phase 3 → Boon changes reflected → Test independently
4. Phase 4 → Subset validation → Test independently
5. Phase 5 → Polish and performance verification

---

## Notes

- No new files are created — all changes are to existing files (`gui.py`, `cli.py`, `test_gui.py`)
- No new dependencies — uses NiceGUI (existing), raw HTML table rendering
- No engine changes — delegates entirely to `ComparisonEngine.cross_ttk_matrix()`
- Total new code: ~145 lines across 3 files per the plan
- [P] tasks = different files, no dependencies
- Commit after each task or logical group
