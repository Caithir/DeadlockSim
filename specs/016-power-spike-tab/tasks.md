# Tasks: Power Spike Tab

**Input**: Design documents from `/specs/016-power-spike-tab/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Engine tests are included for all engine modifications per project convention.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational Models (Blocking Prerequisites)

**Purpose**: Data models and engine infrastructure that MUST be complete before any user story work

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T001 [US1] Add `PurchaseEvent` dataclass to `deadlock_sim/models.py` — fields: `action` (buy/sell/swap), `item`, `swap_target`, `cumulative_souls`
- [ ] T002 [US1] Add `PowerCurveConfig` dataclass to `deadlock_sim/models.py` — fields: `hero`, `purchase_order`, `slot_counts` (default [9,10,11,12]), `sell_refund_rate` (0.5), `metrics`, `sim_settings`, `accuracy`, `headshot_rate`, `defender`
- [ ] T003 [US1] Add `PowerCurvePoint` dataclass to `deadlock_sim/models.py` — fields: `cumulative_souls`, `active_items`, `sold_item`, `metrics` dict
- [ ] T004 [US1] Add `PowerCurveResult` dataclass to `deadlock_sim/models.py` — fields: `hero_name`, `curves` (slot_count → list[PowerCurvePoint]), `purchase_events`

**Checkpoint**: All model dataclasses exist; engine and UI phases can begin

---

## Phase 2: User Story 1 — Build Timing Chart (Priority: P1) 🎯 MVP

**Goal**: Chart showing step-function stat jumps at each item purchase threshold (X = cumulative souls, Y = stats)

**Independent Test**: Set up a build with 4+ items, define a purchase order, verify the chart shows step-function stat jumps at each cumulative soul threshold.

### Engine for User Story 1

- [ ] T005 [US1] Create `deadlock_sim/engine/powerspike.py` with `PowerCurveEngine` class skeleton and imports
- [ ] T006 [US1] Implement `PowerCurveEngine._evaluate_at_step()` in `deadlock_sim/engine/powerspike.py` — delegate to `BuildEngine.aggregate_stats`, `DamageCalculator.calculate_bullet`, `DamageCalculator.hero_total_spirit_dps`, `BuildEngine.defender_effective_hp` for metric computation
- [ ] T007 [US1] Implement `PowerCurveEngine._build_slot_sequence()` in `deadlock_sim/engine/powerspike.py` — walk purchase order, track active items up to max_slots (no auto-sell in this single-line mode)
- [ ] T008 [US1] Implement `PowerCurveEngine.compute_curves()` in `deadlock_sim/engine/powerspike.py` — iterate slot_counts, call `_build_slot_sequence` + `_evaluate_at_step` at each step, return `PowerCurveResult`
- [ ] T009 [US1] Export `PowerCurveEngine` from `deadlock_sim/engine/__init__.py` — add import and `__all__` entry

### Tests for User Story 1

- [ ] T010 [US1] Add unit test in `tests/test_engine.py`: verify `compute_curves` returns correct cumulative soul thresholds for a 4-item build (e.g., items at 500, 1250, 3000 → steps at 500, 1750, 4750)
- [ ] T011 [US1] Add unit test in `tests/test_engine.py`: verify `_evaluate_at_step` returns non-zero bullet_dps and total_dps for a hero with weapon items
- [ ] T012 [P] [US1] Add unit test in `tests/test_engine.py`: verify `compute_curves` returns a `PowerCurveResult` with one curve per slot_count in config

### UI for User Story 1

- [ ] T013 [US1] Add `purchase_order` property and `set_purchase_order()` method to `BuildState` in `deadlock_sim/ui/state.py` — default order is cost-ascending from `state.items`
- [ ] T014 [US1] Create `_build_power_spike_tab(state: BuildState)` function in `deadlock_sim/ui/gui.py` — scaffold tab layout with ECharts placeholder and purchase order display
- [ ] T015 [US1] Implement ECharts step-line chart in `_build_power_spike_tab()` in `deadlock_sim/ui/gui.py` — `ui.echart` with `type: 'line'`, `step: 'end'`, X axis = cumulative souls, Y axis = Total DPS (default metric), one series per slot count
- [ ] T016 [US1] Register Power Spikes tab in `run_gui()` in `deadlock_sim/ui/gui.py` — add tab alongside existing tabs
- [ ] T017 [US1] Wire chart update on build change in `deadlock_sim/ui/gui.py` — when hero/items change, call `PowerCurveEngine.compute_curves()` and refresh chart data

**Checkpoint**: User Story 1 complete — chart renders step-function power curves with default Total DPS metric. MVP deliverable.

---

## Phase 3: User Story 2 — Flex Slot Power Curves (Priority: P1) 🎯 MVP

**Goal**: 4 overlapping power curve lines (9/10/11/12 slots) showing how builds diverge when slot-locked

**Independent Test**: View a 12+ item build, verify 4 distinct lines appear with divergence after the slot cap.

### Engine for User Story 2

- [ ] T018 [US2] Implement `PowerCurveEngine._auto_sell_item()` in `deadlock_sim/engine/powerspike.py` — remove lowest-cost item from active list, return (new_items, sold_item, refund_amount) with 50% refund
- [ ] T019 [US2] Extend `PowerCurveEngine._build_slot_sequence()` in `deadlock_sim/engine/powerspike.py` — when `len(active_items) > max_slots`, call `_auto_sell_item()` and subtract refund from cumulative cost, record `sold_item` in output

### Tests for User Story 2

- [ ] T020 [US2] Add unit test in `tests/test_engine.py`: verify `_auto_sell_item` removes the lowest-cost item and returns 50% refund
- [ ] T021 [US2] Add unit test in `tests/test_engine.py`: verify 9-slot curve triggers auto-sell when 10th item added — sold item name appears in `PowerCurvePoint.sold_item`
- [ ] T022 [P] [US2] Add unit test in `tests/test_engine.py`: verify 12-slot curve with ≤12 items has no sell events (all `sold_item` fields are None)

### UI for User Story 2

- [ ] T023 [US2] Ensure chart in `deadlock_sim/ui/gui.py` renders 4 distinct series with unique colors/labels for 9, 10, 11, 12 slots — verify divergence point visible in tooltip
- [ ] T024 [US2] Add ECharts tooltip in `deadlock_sim/ui/gui.py` showing item purchased, item sold (if any), and current active item set at each X point

**Checkpoint**: User Story 2 complete — 4 slot-count lines render with auto-sell divergence visible.

---

## Phase 4: User Story 3 — Item Sell/Swap Events (Priority: P2)

**Goal**: User-defined sell/swap events in purchase order for planned item transitions

**Independent Test**: Mark an item as "sell X, buy Y", verify the chart shows power dip/spike at the correct soul threshold.

### Engine for User Story 3

- [ ] T025 [US3] Extend `_build_slot_sequence()` in `deadlock_sim/engine/powerspike.py` to handle `PurchaseEvent.action == "swap"` — sell `swap_target`, apply refund, then buy new item
- [ ] T026 [US3] Extend `_build_slot_sequence()` in `deadlock_sim/engine/powerspike.py` to handle `PurchaseEvent.action == "sell"` — remove item, apply 50% refund, adjust cumulative souls

### Tests for User Story 3

- [ ] T027 [US3] Add unit test in `tests/test_engine.py`: verify swap event correctly removes old item and adds new item with refund applied to cumulative souls
- [ ] T028 [P] [US3] Add unit test in `tests/test_engine.py`: verify sell event removes item and reduces cumulative soul cost by 50% of sold item's cost

### State & UI for User Story 3

- [ ] T029 [US3] Add `add_sell_event(sell_item, buy_item, after_index)` method to `BuildState` in `deadlock_sim/ui/state.py` — insert swap `PurchaseEvent` into purchase sequence
- [ ] T030 [US3] Add sell/swap event UI controls in `_build_power_spike_tab()` in `deadlock_sim/ui/gui.py` — per-item dropdown or button to mark "sell X, buy Y" overrides
- [ ] T031 [US3] Wire sell/swap events to engine recompute in `deadlock_sim/ui/gui.py` — on sell/swap change, rebuild `PowerCurveConfig.purchase_order` and refresh chart

**Checkpoint**: User Story 3 complete — user-defined sell/swap events reflected in power curves.

---

## Phase 5: User Story 4 — Selectable Y-Axis Metrics (Priority: P2)

**Goal**: Toggle which metrics appear on the Y axis (Total DPS, Bullet DPS, Spirit DPS, EHP, Sim DPS)

**Independent Test**: Toggle metric visibility, verify the chart shows/hides selected metric lines.

### Engine for User Story 4

- [ ] T032 [US4] Ensure `_evaluate_at_step()` in `deadlock_sim/engine/powerspike.py` computes all requested metrics from `config.metrics` list — bullet_dps, spirit_dps, ehp, total_dps computed conditionally
- [ ] T033 [US4] Add sim_dps metric path in `_evaluate_at_step()` in `deadlock_sim/engine/powerspike.py` — when "sim_dps" in metrics and `config.sim_settings` provided, call `CombatSimulator.run()` for each step

### Tests for User Story 4

- [ ] T034 [US4] Add unit test in `tests/test_engine.py`: verify `_evaluate_at_step` returns only the metrics listed in `config.metrics` (e.g., requesting ["bullet_dps", "ehp"] returns exactly those keys)
- [ ] T035 [P] [US4] Add unit test in `tests/test_engine.py`: verify sim_dps metric is skipped when `sim_settings` is None even if "sim_dps" is in metrics list

### UI for User Story 4

- [ ] T036 [US4] Add metric toggle checkboxes in `_build_power_spike_tab()` in `deadlock_sim/ui/gui.py` — checkboxes for Total DPS (default on), Bullet DPS, Spirit DPS, EHP, Sim DPS
- [ ] T037 [US4] Wire metric toggles to chart update in `deadlock_sim/ui/gui.py` — on toggle change, update `PowerCurveConfig.metrics`, recompute, add/remove ECharts series
- [ ] T038 [US4] Add "Compute Sim DPS" button in `deadlock_sim/ui/gui.py` — visible only when sim_dps metric toggled, triggers expensive simulation computation on click

**Checkpoint**: User Story 4 complete — all metric toggles functional, Sim DPS computed on demand.

---

## Phase 6: Drag-to-Reorder & CLI (Cross-Cutting)

**Purpose**: Interactive reorder (FR-003) and CLI parity (Principle IV)

### Drag-to-Reorder (GUI)

- [ ] T039 [US1] Implement drag-to-reorder for purchase order in `deadlock_sim/ui/gui.py` — use NiceGUI `ui.sortable` or equivalent for item card reordering
- [ ] T040 [US1] Wire reorder events to state + engine in `deadlock_sim/ui/gui.py` — on drag end, call `state.set_purchase_order()`, recompute curves, update chart (target: < 1s per SC-003)

### CLI Summary

- [ ] T041 [P] [US1] Add power curve text table menu option in `deadlock_sim/ui/cli.py` — print tabular summary of purchase order with step, souls, item bought, and stat columns for each slot count

**Checkpoint**: All interactive features complete. CLI provides text-equivalent data access.

---

## Phase 7: Polish & Integration

**Purpose**: Performance, edge cases, and cross-cutting improvements

- [ ] T042 [P] Add boon progression integration in `_evaluate_at_step()` in `deadlock_sim/engine/powerspike.py` — call `souls_to_boons(cumulative_souls)` to include boon scaling at each step
- [ ] T043 [P] Handle edge case: single-item build in `compute_curves()` in `deadlock_sim/engine/powerspike.py` — ensure chart renders with a single step
- [ ] T044 [P] Handle edge case: empty build (no items) in `compute_curves()` in `deadlock_sim/engine/powerspike.py` — return base hero stats as the only point
- [ ] T045 Performance validation: verify 12-item 4-slot-line chart renders in < 2 seconds (SC-001) — profile `compute_curves` and chart render
- [ ] T046 [P] Verify shop tier bonuses are reflected via `BuildEngine.aggregate_stats` when purchase order crosses tier thresholds (SC-004)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Models)**: No dependencies — start immediately
- **Phase 2 (US1 Engine/UI)**: Depends on Phase 1 completion
- **Phase 3 (US2 Auto-sell)**: Depends on Phase 2 (extends `_build_slot_sequence`)
- **Phase 4 (US3 Sell/Swap)**: Depends on Phase 3 (extends auto-sell logic)
- **Phase 5 (US4 Metrics)**: Depends on Phase 2; can run in parallel with Phases 3–4
- **Phase 6 (Reorder/CLI)**: Depends on Phase 2 (US1 chart must exist)
- **Phase 7 (Polish)**: Depends on Phases 2–6

### Parallel Opportunities

- T001–T004: Models are in the same file but logically sequential (each builds on prior types)
- T010, T011, T012: US1 tests can be written in parallel
- T020, T021, T022: US2 tests can be written in parallel
- T027, T028: US3 tests can be written in parallel
- T034, T035: US4 tests can be written in parallel
- Phase 5 (US4 metrics) can run in parallel with Phases 3–4 (US2/US3 auto-sell)
- T041 (CLI) can run in parallel with any GUI task
- T042, T043, T044, T046: Polish tasks are independent

### Within Each User Story

- Models before engine
- Engine before tests (tests verify engine)
- Engine before UI (UI calls engine)
- Tests written alongside or after engine implementation

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Models
2. Complete Phase 2: US1 — Build Timing Chart
3. Complete Phase 3: US2 — Flex Slot Power Curves
4. **STOP and VALIDATE**: 4-line power chart renders with auto-sell
5. Demo/review

### Incremental Delivery

1. Phase 1 + Phase 2 → Basic chart with Total DPS (MVP core)
2. Phase 3 → Auto-sell divergence visible (MVP complete)
3. Phase 4 → Sell/swap overrides (P2 enhancement)
4. Phase 5 → Multi-metric Y axis (P2 enhancement)
5. Phase 6 → Drag reorder + CLI parity
6. Phase 7 → Polish and edge cases

---

## Notes

- [P] tasks = different files or independent logic, no ordering dependencies
- [US#] maps each task to its user story for traceability
- All engine modifications have corresponding test tasks
- `sell_refund_rate` (0.5) is parameterized in `PowerCurveConfig`, not hardcoded
- Slot counts [9, 10, 11, 12] are parameterized in `PowerCurveConfig`
- Shop tier bonuses are handled by existing `BuildEngine.aggregate_stats` — no new code needed
- Boon progression via `souls_to_boons()` is integrated in Phase 7 polish
