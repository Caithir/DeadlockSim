# Tasks: Simulation Timeline Chart

**Input**: Design documents from `/specs/013-simulation-timeline-chart/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Integration test included per plan.md test plan (Playwright GUI test + bucketing helper unit test).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Shared Helpers)

**Purpose**: Extract and implement the bucketing and HP-remaining helpers that all chart modes depend on.

- [ ] T001 [US1] Extract timeline bucketing logic into `_bucket_timeline()` helper function at module level in `deadlock_sim/ui/gui.py` (~line 3465). Takes `list[DamageEntry]`, `duration`, `bucket_size`, `cumulative`, `bidirectional` and returns `dict` with `time_labels`, `series`, `damage_types`, `combatants`. Replaces inline bucketing in `_render_results()` (lines ~3469–3486).
- [ ] T002 [US2] Implement `_hp_remaining_series()` helper function in `deadlock_sim/ui/gui.py`. Computes defender HP remaining at each time bucket. Uses Option A math: `initial_hp = total_damage + target_hp_remaining`. Handles both unidirectional and bidirectional cases.

**Checkpoint**: Bucketing helpers ready — chart implementation can begin.

---

## Phase 2: User Story 1 — Damage Over Time Chart (Priority: P1) 🎯 MVP

**Goal**: Replace the existing DPS bar chart with a stacked area chart showing bullet/spirit/melee/proc damage layers over time.

**Independent Test**: Run a simulation with abilities and items, verify the chart renders with distinct damage layers on X=time, Y=cumulative damage.

### Implementation for User Story 1

- [ ] T003 [US1] Replace the existing "DPS Over Time" bar chart section in `_render_results()` (`deadlock_sim/ui/gui.py`, lines ~3465–3543) with a stacked area chart using `ui.echart()`. Use `_bucket_timeline()` with `cumulative=True`. Configure `type: "line"`, `areaStyle: {}`, `stack: "damage"` for each damage source series. Keep existing color scheme (`_dtype_colors_a`, `_dtype_colors_b`) and legend icon logic.
- [ ] T004 [US1] Add tooltip configuration to the new ECharts chart in `deadlock_sim/ui/gui.py`. Tooltip should trigger on axis hover and show exact damage values per source at the hovered time point (satisfies acceptance scenario 1.2).
- [ ] T005 [US1] Handle edge case for short simulations (< 3s duration) in `_bucket_timeline()` in `deadlock_sim/ui/gui.py` — use `bucket_size=0.25` instead of `0.5` to maintain granularity.
- [ ] T006 [US1] Handle edge case for zero-damage series in chart config in `deadlock_sim/ui/gui.py` — filter out all-zero series from `legend.data` so empty damage types (e.g., spirit on a gun-only build) don't clutter the legend.

**Checkpoint**: Stacked area cumulative chart renders after simulation. US1 acceptance scenarios met.

---

## Phase 3: User Story 2 — HP Remaining Overlay (Priority: P2)

**Goal**: Overlay the defender's HP remaining as a line on a secondary Y axis, with a kill marker when HP hits 0.

**Independent Test**: Run a simulation, verify HP line appears on secondary Y axis decreasing as damage accumulates.

### Implementation for User Story 2

- [ ] T007 [US2] Add a secondary Y axis to the ECharts chart config in `deadlock_sim/ui/gui.py`. Configure for HP remaining: `type: "value"`, `name: "HP"`, positioned on the right side.
- [ ] T008 [US2] Add HP remaining line series to the chart in `deadlock_sim/ui/gui.py`. Use `_hp_remaining_series()` output. Configure as `type: "line"`, `yAxisIndex: 1`, color `#ef4444` (red), dashed `lineStyle`.
- [ ] T009 [US2] Add kill marker as `markPoint` on the HP line in `deadlock_sim/ui/gui.py`. When `result.kill_time` is not None, place a marker at the time bucket where HP reaches 0 (acceptance scenario 2.2).
- [ ] T010 [US2] Handle bidirectional mode HP overlay in `deadlock_sim/ui/gui.py` — render two HP lines (one per combatant) using `_hp_remaining_series()` with respective `combatant_filter` values. Use distinct styling (e.g., solid vs dashed) to differentiate.

**Checkpoint**: HP remaining overlay and kill marker visible on chart. US2 acceptance scenarios met.

---

## Phase 4: User Story 3 — Per-Second Bucketed View (Priority: P3)

**Goal**: Add a toggle to switch between cumulative stacked area and per-second DPS bar chart views.

**Independent Test**: Toggle the view mode, verify the chart switches from cumulative area to per-second bar chart.

### Implementation for User Story 3

- [ ] T011 [US3] Add `ui.toggle` control above the chart in `deadlock_sim/ui/gui.py` with options "Cumulative" and "Per-Second". Default to "Cumulative".
- [ ] T012 [US3] Implement toggle callback in `deadlock_sim/ui/gui.py`. On toggle change, call `_bucket_timeline()` with the new `cumulative` flag, rebuild ECharts options (stacked area for cumulative, stacked bar for per-second), and update chart via `chart.options = new_options; chart.update()`. HP overlay remains visible in both modes.
- [ ] T013 [US3] Ensure per-second mode divides bucket values by `bucket_size` to show DPS rather than raw damage per bucket in `_bucket_timeline()` in `deadlock_sim/ui/gui.py`.

**Checkpoint**: Toggle switches between cumulative and per-second views. US3 acceptance scenario met.

---

## Phase 5: CLI Parity

**Purpose**: Provide equivalent per-second DPS visibility in the CLI interface.

- [ ] T014 [P] [US1] Implement `_print_dps_timeline()` function in `deadlock_sim/ui/cli.py`. Takes `SimResult`, prints ASCII per-second DPS table with columns: Time, Bullet, Spirit, Melee, Total. Uses same bucketing logic as `_bucket_timeline()` (can inline or import).
- [ ] T015 [US1] Call `_print_dps_timeline()` from the CLI simulation results output path in `deadlock_sim/ui/cli.py` (after existing result display logic near `run_cli()`).

**Checkpoint**: CLI prints per-second DPS table after simulation results. Dual interface parity achieved.

---

## Phase 6: Tests & Polish

**Purpose**: Integration tests and cross-cutting validation.

### Tests

- [ ] T016 [P] [US1] Add unit test `test_bucket_timeline_cumulative` in `tests/test_gui.py` (or new `tests/test_timeline_helpers.py`). Construct a known `list[DamageEntry]`, call `_bucket_timeline()` with `cumulative=True`, assert series values match expected running sums. Verify SC-002: layers sum to total damage.
- [ ] T017 [P] [US1] Add unit test `test_bucket_timeline_per_second` in same test file. Call `_bucket_timeline()` with `cumulative=False`, assert bucket values are divided by `bucket_size`.
- [ ] T018 [P] [US2] Add unit test `test_hp_remaining_series` in same test file. Construct known timeline data, call `_hp_remaining_series()`, assert HP decreases correctly and clamps to 0.
- [ ] T019 [US1] Add Playwright integration test `test_simulation_timeline_chart` in `tests/test_gui.py`. Select a hero, run simulation, assert chart container is visible, assert toggle exists with "Cumulative" / "Per-Second" options, click each toggle option and verify chart updates.

### Polish

- [ ] T020 [P] Verify SC-001 performance: chart renders within 500ms of simulation completion. Add a timing check in integration test or manual verification.
- [ ] T021 [P] Code cleanup: remove any dead code from the old DPS bar chart section in `deadlock_sim/ui/gui.py` that was replaced by the new chart.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Foundational)**: No dependencies — start immediately
  - T001 before T002 (HP series depends on bucketing pattern, but can be parallel if signatures are agreed)
- **Phase 2 (US1 — Chart)**: Depends on T001
  - T003 → T004 (tooltip depends on chart existing)
  - T005, T006 can be done after T003
- **Phase 3 (US2 — HP Overlay)**: Depends on T002 and T003
  - T007 → T008 → T009 (sequential: axis → line → marker)
  - T010 after T008
- **Phase 4 (US3 — Toggle)**: Depends on T003 (chart must exist)
  - T011 → T012 → T013 (sequential: control → callback → DPS math)
- **Phase 5 (CLI)**: Depends on T001 (bucketing logic)
  - T014 → T015 (function → call site)
  - T014 is [P] — can run in parallel with Phase 2/3/4
- **Phase 6 (Tests)**: T016–T018 depend on T001/T002; T019 depends on all US1+US3 tasks

### Parallel Opportunities

```
After T001 completes:
  ├── T003 (start US1 chart)           ─ sequential within phase
  ├── T014 (CLI parity)                ─ [P] different file
  ├── T016, T017 (bucketing tests)     ─ [P] test file

After T002 completes:
  └── T018 (HP helper test)            ─ [P] test file

After T003 completes:
  ├── T004, T005, T006 (US1 polish)    ─ sequential (same file region)
  ├── T007 (start US2 overlay)         ─ after T002 also done
  └── T011 (start US3 toggle)          ─ can begin
```

### User Story Dependencies

- **US1 (P1)**: Depends on Phase 1 only — no cross-story dependencies
- **US2 (P2)**: Depends on Phase 1 + US1 chart existing (T003)
- **US3 (P3)**: Depends on US1 chart existing (T003)

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: T001 (bucketing helper)
2. Complete Phase 2: T003–T006 (stacked area chart)
3. Complete Phase 5: T014–T015 (CLI parity)
4. **STOP and VALIDATE**: Run simulation, verify cumulative chart renders correctly
5. Run T016, T017 (unit tests) to validate bucketing math

### Incremental Delivery

1. Phase 1 + Phase 2 → Cumulative stacked area chart (MVP!)
2. Add Phase 3 → HP overlay with kill marker
3. Add Phase 4 → Toggle between cumulative / per-second
4. Phase 5 → CLI parity
5. Phase 6 → Full test coverage and polish

---

## Notes

- All GUI changes are in a single file (`deadlock_sim/ui/gui.py`) — tasks within the same phase are sequential to avoid conflicts
- CLI changes are in a separate file (`deadlock_sim/ui/cli.py`) — can be parallelized with GUI work
- Test tasks marked [P] target different test functions and can run in parallel
- No engine changes required — all work is in the UI layer (Constitution Principle I)
- Existing ECharts support via NiceGUI `ui.echart()` — no new dependencies needed
