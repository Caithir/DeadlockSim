# Tasks: Patch Notes GUI Tab

**Input**: Design documents from `/specs/018-patch-notes-gui/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Data Model (Blocking Prerequisite)

**Purpose**: Add the `BuildImpact` dataclass needed by engine and UI layers

- [ ] T001 [P] [US2] Add `BuildImpact` dataclass to `deadlock_sim/models.py` — fields for hero_name, patch_date, before/after metrics (bullet_dps, spirit_dps, combined_dps, effective_hp, ttk), and computed deltas

**Checkpoint**: `BuildImpact` importable from models — engine work can begin

---

## Phase 2: Engine (Build Impact Calculation)

**Purpose**: Add the `evaluate_build_impact()` method that computes before/after build metrics across a patch

- [ ] T002 [US2] Add `BuildEngine.evaluate_build_impact()` static method to `deadlock_sim/engine/builds.py` — accepts hero, build, list[PatchChange], boons, combat_config; computes post-patch BuildResult via existing `evaluate_build()`, deep-copies hero/items, reverse-applies patch changes, computes pre-patch BuildResult, returns `BuildImpact` with deltas

**Checkpoint**: `evaluate_build_impact()` callable from engine with correct return type — UI can wire to it

---

## Phase 3: User Story 1 — View Parsed Patch Changes (Priority: P1) 🎯 MVP

**Goal**: Display parsed patch changes grouped by hero/item with buff/nerf color-coding in a new GUI tab

**Independent Test**: Load the latest patch, verify changes display grouped by hero/item with green (buff) and red (nerf) highlighting

### Implementation for User Story 1

- [ ] T003 [US1] Add `_is_buff()` helper function to `deadlock_sim/ui/gui.py` — determine buff/nerf/neutral from a `PatchChange` using `_LOWER_IS_BETTER` set for cooldown stats; return True (buff), False (nerf), or None (indeterminate)

- [ ] T004 [US1] Add `_build_patch_notes_tab(state: _PageState)` function scaffold to `deadlock_sim/ui/gui.py` — empty-state handling ("No patches available" message + "Fetch Latest" button when no patch files exist)

- [ ] T005 [US1] Implement patch loading dropdown in `_build_patch_notes_tab()` in `deadlock_sim/ui/gui.py` — populate from `patchnotes.list_saved_patches()`, default to most recent, add "Fetch Latest" button that calls `patchnotes.fetch_latest_patch()` + `save_patch()` and reloads dropdown

- [ ] T006 [US1] Implement hero changes display section in `_build_patch_notes_tab()` in `deadlock_sim/ui/gui.py` — group `PatchChange` objects by `change.hero`, render collapsible `ui.expansion()` panels per hero, show stat/old_value/new_value/delta with color-coding via `_is_buff()`

- [ ] T007 [US1] Implement item changes display section in `_build_patch_notes_tab()` in `deadlock_sim/ui/gui.py` — group `PatchChange` objects by `change.item`, render collapsible `ui.expansion()` panels per item, same color-coding pattern as hero changes

- [ ] T008 [US1] Register "Patch Notes" tab in `run_gui()` in `deadlock_sim/ui/gui.py` — add `tab_patch = ui.tab("Patch Notes")` alongside existing tabs, add `ui.tab_panel(tab_patch)` calling `_build_patch_notes_tab(state)`, handle in `_on_tab_change` if needed

**Checkpoint**: Patch Notes tab renders grouped, color-coded changes from parsed patch files — US1 fully functional

---

## Phase 4: User Story 2 — Build Impact Analysis (Priority: P1) 🎯 MVP

**Goal**: Show how a patch affects the current build's DPS, EHP, and TTK with before/after deltas

**Independent Test**: Load a saved build, click "Analyze Impact", verify DPS/EHP/TTK before-and-after pairs with deltas

### Implementation for User Story 2

- [ ] T009 [US2] Add "Build Impact" section to `_build_patch_notes_tab()` in `deadlock_sim/ui/gui.py` — "Analyze Impact" button disabled with tooltip when no hero selected; enabled when `state.build_hero_name` is set

- [ ] T010 [US2] Wire "Analyze Impact" button click handler in `deadlock_sim/ui/gui.py` — call `BuildEngine.evaluate_build_impact()` with current hero, build items, boons, and parsed patch changes; display results in a table with columns: Metric, Before, After, Delta; color-code delta cells green/red

- [ ] T011 [US2] Handle build impact edge cases in `deadlock_sim/ui/gui.py` — show error notification on network failure during fetch (`requests.RequestException`), handle reverse-apply failures gracefully with notes in impact results, handle patch changes for items not in build

**Checkpoint**: Build impact analysis shows before/after DPS/EHP/TTK deltas for current build — US2 fully functional

---

## Phase 5: User Story 3 — Patch History Navigation (Priority: P3)

**Goal**: Allow selecting from available patches to review older patch impacts

**Independent Test**: Load a previous patch file from `data/patches/`, verify its changes and build impact reflect that specific patch

### Implementation for User Story 3

- [ ] T012 [US3] Enhance patch dropdown in `_build_patch_notes_tab()` in `deadlock_sim/ui/gui.py` — on selection change, reload and re-parse the selected patch via `patchnotes.load_saved_patch()` + `parse_patch_notes()`, re-render change groups, reset build impact results

**Checkpoint**: Selecting an older patch re-renders all changes and impact analysis for that patch — US3 functional

---

## Phase 6: Tests

**Purpose**: Engine unit test and GUI integration test for new functionality

- [ ] T013 [P] [US2] Add unit test for `BuildEngine.evaluate_build_impact()` in `tests/test_engine.py` — test with known hero/build and synthetic PatchChange list; assert deltas are correct; test edge cases (empty changes list, non-matching hero changes, reverse-apply of cooldown stats)

- [ ] T014 [P] [US1] Add Playwright integration test for Patch Notes tab in `tests/test_gui.py` — navigate to Patch Notes tab, verify tab renders, verify grouped changes display with correct hero/item headings, verify color-coding classes on buff/nerf elements

- [ ] T015 [US2] Add Playwright integration test for build impact in `tests/test_gui.py` — select a hero in Build tab, navigate to Patch Notes tab, click "Analyze Impact", verify impact table renders with Metric/Before/After/Delta columns

**Checkpoint**: All tests pass — feature complete

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Data Model)**: No dependencies — can start immediately
- **Phase 2 (Engine)**: Depends on T001 (`BuildImpact` dataclass)
- **Phase 3 (US1 — Change Display)**: Depends on Phase 1 only (no engine dependency); T004→T005→T006→T007 are sequential (same function); T003 and T008 are parallel with the rest
- **Phase 4 (US2 — Build Impact)**: Depends on T002 (engine method) and T008 (tab registered)
- **Phase 5 (US3 — History)**: Depends on Phase 3 (change display must exist)
- **Phase 6 (Tests)**: T013 depends on T002; T014 depends on T008; T015 depends on T010

### Task Dependency Graph

```
T001 (BuildImpact model)
 ├── T002 (evaluate_build_impact engine method)
 │    ├── T009 → T010 → T011 (Build Impact UI)
 │    ├── T013 (engine unit test)
 │    └── T015 (build impact integration test)
 │
 ├── T003 (_is_buff helper) ─────────────────┐
 ├── T004 (tab scaffold) ────────────────────┤
 │    └── T005 (patch dropdown) ─────────────┤
 │         └── T006 (hero changes display) ──┤
 │              └── T007 (item changes) ─────┤
 │                   └── T012 (history nav)  │
 └── T008 (register tab in run_gui) ────────┤
                                             └── T014 (GUI integration test)
```

### Parallel Opportunities

- T001 is standalone — start immediately
- T003 and T004 can run in parallel (different functions in same file, but no overlap)
- T013 and T014 can run in parallel (different test files)
- Once Phase 3 is complete, US2 (Phase 4) and US3 (Phase 5) can proceed in parallel

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Add `BuildImpact` dataclass (T001)
2. Complete Phase 2: Add engine method (T002)
3. Complete Phase 3: Build change display tab (T003–T008)
4. Complete Phase 4: Wire build impact analysis (T009–T011)
5. **STOP and VALIDATE**: Patch tab shows grouped changes + build impact works
6. Complete Phase 6: Add tests (T013–T015)

### Incremental Delivery

1. T001–T002 → Engine ready
2. T003–T008 → Change display tab live (US1 MVP!)
3. T009–T011 → Build impact analysis live (US2 MVP!)
4. T012 → Patch history navigation (US3 — nice-to-have)
5. T013–T015 → Tests pass — feature complete

---

## Notes

- All GUI code goes in `deadlock_sim/ui/gui.py` following the existing `_build_*_tab()` pattern
- No new runtime dependencies required — purely UI + engine wiring
- `PatchChange` and `PatchReport` live in `deadlock_sim/patchnotes.py` (not models.py)
- `BuildImpact` is the only new dataclass, added to `deadlock_sim/models.py`
- The CLI already has `deadlock-sim-patch` — no CLI changes needed
- Color-coding: green for buffs, red for nerfs, gray/neutral for indeterminate changes
- Performance targets: change rendering < 1s (SC-001), impact analysis < 2s (SC-002)
