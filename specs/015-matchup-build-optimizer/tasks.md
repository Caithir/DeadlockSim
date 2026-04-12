# Tasks: Matchup-Specific Build Optimizer

**Input**: Design documents from `/specs/015-matchup-build-optimizer/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundation (Blocking Prerequisites)

**Purpose**: Extend `ScoringConfig` and add the shared `_resolve_defender` helper that all user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] [T001] [US1] Add `defender_hero`, `defender_build`, and `defender_boons` optional fields to `ScoringConfig` dataclass in `deadlock_sim/engine/scoring.py`
- [ ] [T002] [US1] Add `_resolve_defender(cfg: ScoringConfig) -> tuple[float, float, float]` static method to `ItemScorer` that extracts (bullet_resist, spirit_resist, effective_hp) from defender config, returning `(0.0, 0.0, 0.0)` when no defender is set, in `deadlock_sim/engine/scoring.py`

**Checkpoint**: `ScoringConfig` extended, `_resolve_defender` helper available — user story implementation can now begin.

---

## Phase 2: User Story 1 — Defender-Aware Item Scoring (Priority: P1) 🎯 MVP

**Goal**: Item scorer evaluates items against a chosen defender hero's HP/resist profile so builds are optimized for specific matchups.

**Independent Test**: Select a defender hero, run item scoring, verify scores differ from no-defender scoring.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation.**

- [ ] [T003] [P] [US1] Unit test: `_resolve_defender` returns `(0.0, 0.0, 0.0)` when `cfg.defender_hero is None` in `tests/test_engine.py`
- [ ] [T004] [P] [US1] Unit test: `_resolve_defender` computes correct bullet_resist, spirit_resist, and effective_hp from defender hero base stats + boons + build items in `tests/test_engine.py`
- [ ] [T005] [P] [US1] Unit test: `_resolve_defender` returns base-stats-only values when `defender_build is None` but `defender_hero` is set in `tests/test_engine.py`
- [ ] [T006] [P] [US1] Unit test: `_score_fast` produces different DPS deltas when scoring with a high-resist defender vs no defender in `tests/test_engine.py`
- [ ] [T007] [P] [US1] Unit test: `_score_sim` uses `cfg.defender_hero` instead of hardcoded `Dummy Target` when defender is set in `tests/test_engine.py`
- [ ] [T008] [P] [US1] Unit test: `score_candidates` with no defender falls back to default generic scoring (regression) in `tests/test_engine.py`

### Implementation for User Story 1

- [ ] [T009] [US1] Update `_score_fast` to call `_resolve_defender` and pass `enemy_bullet_resist`, `enemy_spirit_resist`, `enemy_hp` into `build_to_attacker_config` for both baseline and candidate evaluations in `deadlock_sim/engine/scoring.py`
- [ ] [T010] [US1] Update `_score_sim` to replace hardcoded `HeroStats(name="Dummy Target", ...)` with `cfg.defender_hero` (when set) and pass `cfg.defender_build` into `SimConfig.defender_build` in `deadlock_sim/engine/scoring.py`
- [ ] [T011] [US1] Add `_defender_hero_name`, `_defender_build_items`, `_defender_boons` fields plus `set_defender_hero()`, `clear_defender()` methods to `BuildState` in `deadlock_sim/ui/state.py`
- [ ] [T012] [US1] Add `to_scoring_config(heroes, **kwargs) -> ScoringConfig` method to `BuildState` that populates defender fields when a defender is selected in `deadlock_sim/ui/state.py`
- [ ] [T013] [US1] Add defender hero dropdown (`ui.select`) populated from `_heroes.keys()` with a "None (generic)" option to the Build Lab tab in `deadlock_sim/ui/gui.py`
- [ ] [T014] [US1] Wire `_compute_impact_scores` and `_sim_item_scores` to construct `ScoringConfig` via `BuildState.to_scoring_config()` and pass it to `ItemScorer.score_candidates` in `deadlock_sim/ui/gui.py`
- [ ] [T015] [US1] Add "Select defender hero (0 for generic)" prompt to `display_build_optimizer` in Max DPS flow, constructing `ScoringConfig` with defender context in `deadlock_sim/ui/cli.py`

**Checkpoint**: Item scores change when different defenders are selected. Shred items rank higher vs high-resist defenders. Fallback to generic scoring works.

---

## Phase 3: User Story 2 — Load Defender from Saved Builds (Priority: P1) 🎯 MVP

**Goal**: Players can load a saved build as the defender so scoring accounts for the enemy's actual items and stats (HP, resists from items).

**Independent Test**: Load a saved build as defender, verify item scoring uses defender's build stats.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation.**

- [ ] [T016] [P] [US2] Unit test: `BuildState.set_defender_build(items, boons)` stores items and boons correctly, and `to_scoring_config` includes them in the resulting `ScoringConfig` in `tests/test_engine.py`
- [ ] [T017] [P] [US2] Unit test: scoring with a defender build that includes resist items produces different scores than scoring with defender base stats only in `tests/test_engine.py`

### Implementation for User Story 2

- [ ] [T018] [US2] Add `set_defender_build(items: list[Item], boons: int)` method to `BuildState` in `deadlock_sim/ui/state.py`
- [ ] [T019] [US2] Add "Load Defender Build" button to Build Lab that opens a dialog listing saved builds filtered to the selected defender hero, using existing `_load_saved_builds()` localStorage reader in `deadlock_sim/ui/gui.py`
- [ ] [T020] [US2] Wire selected saved build into `BuildState.set_defender_build(items, boons)` when a build is chosen from the dialog in `deadlock_sim/ui/gui.py`
- [ ] [T021] [US2] Add defender info label showing "vs. {hero_name}" or "vs. {hero_name} ({build_name})" when a defender is selected in `deadlock_sim/ui/gui.py`
- [ ] [T022] [US2] Handle edge case: filter out removed/patched items when loading a saved build as defender (silently drop items not in current `load_items()`) in `deadlock_sim/ui/gui.py`

**Checkpoint**: Saved builds can be loaded as defender. Scores reflect defender's actual items and resist profile. Missing items are gracefully handled.

---

## Phase 4: User Story 3 — Matchup Optimizer Integration (Priority: P2)

**Goal**: `BuildOptimizer` finds the best items specifically against the selected matchup, producing a complete build recommendation for the fight.

**Independent Test**: Run `BuildOptimizer` with a defender selected, verify the recommended build differs from the generic recommendation.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation.**

- [ ] [T023] [P] [US3] Unit test: `best_dps_items` with `scoring_config` containing a high-resist defender selects different items than with no defender in `tests/test_engine.py`
- [ ] [T024] [P] [US3] Unit test: `best_ttk_items` with `defender_build` passes build to `evaluate_build`, producing different TTK than base-stats-only defender in `tests/test_engine.py`
- [ ] [T025] [P] [US3] Unit test: `best_dps_items` without `scoring_config` behaves identically to current behavior (regression) in `tests/test_engine.py`

### Implementation for User Story 3

- [ ] [T026] [US3] Add `scoring_config: ScoringConfig | None = None` parameter to `BuildOptimizer.best_dps_items()` and use defender resist/HP from `_resolve_defender` in the greedy DPS evaluation loop in `deadlock_sim/engine/builds.py`
- [ ] [T027] [US3] Add `defender_build: Build | None = None` parameter to `BuildOptimizer.best_ttk_items()` and pass it to `BuildEngine.evaluate_build()` in the greedy TTK evaluation loop in `deadlock_sim/engine/builds.py`
- [ ] [T028] [US3] Update `display_build_optimizer` Max DPS branch to pass `scoring_config` to `BuildOptimizer.best_dps_items()` and Min TTK branch to pass `defender_build` to `best_ttk_items()` in `deadlock_sim/ui/cli.py`
- [ ] [T029] [US3] Wire GUI Build Lab optimizer (if present) to pass defender context to `BuildOptimizer` methods via `ScoringConfig` / `defender_build` in `deadlock_sim/ui/gui.py`

**Checkpoint**: Optimized builds differ when a defender is selected. Both DPS and TTK optimization modes account for matchup. CLI and GUI produce equivalent results.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end validation and edge case coverage across all user stories.

- [ ] [T030] [P] End-to-end test: score same item set against two different defenders (low-resist vs high-resist), verify shred items rank higher against high-resist defender in `tests/test_engine.py`
- [ ] [T031] [P] End-to-end test: mirror matchup (attacker and defender are same hero) produces valid scores without errors in `tests/test_engine.py`
- [ ] [T032] [P] Edge case test: `defender_build` set without `defender_hero` is a no-op (falls back to generic scoring) in `tests/test_engine.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundation (Phase 1)**: No dependencies — can start immediately. BLOCKS all user stories.
- **User Story 1 (Phase 2)**: Depends on Phase 1 completion.
- **User Story 2 (Phase 3)**: Depends on Phase 2 (US1) — requires defender state fields and scoring wiring.
- **User Story 3 (Phase 4)**: Depends on Phase 1 — can proceed in parallel with US1/US2 for engine changes, but GUI/CLI wiring depends on US1.
- **Polish (Phase 5)**: Depends on all user stories being complete.

### Task Dependencies (within phases)

| Task | Depends On | Reason |
|------|-----------|--------|
| T002 | T001 | `_resolve_defender` reads `ScoringConfig` defender fields |
| T009, T010 | T002 | Scoring methods call `_resolve_defender` |
| T011, T012 | T001 | State methods construct `ScoringConfig` with defender fields |
| T013, T014 | T011, T012 | GUI wiring needs state layer and engine support |
| T015 | T009 | CLI wiring needs engine to accept defender context |
| T018 | T011 | `set_defender_build` extends state fields from T011 |
| T019–T022 | T018, T014 | GUI build loading needs state method and scoring wiring |
| T026, T027 | T002 | `BuildOptimizer` uses `_resolve_defender` |
| T028 | T026, T027, T015 | CLI wiring needs optimizer parameters |
| T029 | T026, T027, T014 | GUI wiring needs optimizer parameters and scoring wiring |
| T030–T032 | All impl tasks | End-to-end tests validate full integration |

### Parallel Opportunities

```
Phase 1: T001 → T002 (sequential — T002 depends on T001)

Phase 2 tests: T003 ‖ T004 ‖ T005 ‖ T006 ‖ T007 ‖ T008 (all parallel)
Phase 2 engine: T009 ‖ T010 (parallel — different methods in same file, non-overlapping)
Phase 2 state:  T011 → T012 (sequential)
Phase 2 UI:     T013 → T014 (sequential); T015 can run in parallel with GUI tasks

Phase 3 tests: T016 ‖ T017 (parallel)
Phase 3 impl:  T018 → T019 → T020 → T021 → T022 (sequential — GUI dialog flow)

Phase 4 tests: T023 ‖ T024 ‖ T025 (all parallel)
Phase 4 engine: T026 ‖ T027 (parallel — different methods)
Phase 4 UI:     T028 ‖ T029 (parallel — CLI and GUI are different files)

Phase 5: T030 ‖ T031 ‖ T032 (all parallel)
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Foundation (`ScoringConfig` + `_resolve_defender`)
2. Complete Phase 2: US1 — Defender-aware item scoring
3. Complete Phase 3: US2 — Load saved builds as defender
4. **STOP and VALIDATE**: Scores change per defender; saved builds load correctly
5. Deploy/demo if ready

### Incremental Delivery

1. Phase 1 → Foundation ready
2. Phase 2 (US1) → Item scores reflect matchup → **MVP Demo**
3. Phase 3 (US2) → Defender builds loaded from saves → **Full P1**
4. Phase 4 (US3) → Optimizer recommends matchup-specific builds → **P2 Complete**
5. Phase 5 → Edge cases validated, polish complete

---

## Notes

- [P] tasks = different files or non-overlapping regions, no dependencies
- All engine changes are in existing files — no new modules created
- `ScoringConfig` defaults ensure zero breaking changes to existing callers
- CLI does not support saved-build loading (no localStorage) — defender is base stats + boons only
- Simulation engine already handles `defender_build` in `SimConfig` — no changes to `simulation.py` needed
- Commit after each task or logical group
