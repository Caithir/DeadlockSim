# Tasks: Defensive Item Scorer

**Input**: Design documents from `/specs/022-defensive-item-scorer/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Organization**: Tasks are grouped by phase and user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Data Models (Shared Infrastructure)

**Purpose**: Add the foundational data structures that all user stories depend on.

- [ ] [T001] [P] [US1] Add `DefensiveScore` dataclass to `deadlock_sim/models.py` with fields: `item_name`, `survival_time_delta`, `fast_survival_delta`, `ehp_delta`, `bullet_ehp_delta`, `spirit_ehp_delta`, `survival_per_soul`, `ehp_per_soul`, `attacker_name`, `attacker_dps`, `attacker_bullet_pct`, `attacker_spirit_pct`
- [ ] [T002] [P] [US1] Extend `ScoringConfig` in `deadlock_sim/engine/scoring.py` with defensive fields: `scoring_mode` (default "offensive"), `attacker_hero`, `attacker_build`, `attacker_boons`, `attacker_ability_upgrades`, `attacker_ability_schedule`

**Checkpoint**: Data model layer complete — engine work can begin.

---

## Phase 2: User Story 1 — Score Defensive Items Against Specific Attacker (Priority: P1) 🎯 MVP

**Goal**: Rank candidate defensive items by survival time delta against a specific attacker's damage profile.

**Independent Test**: Select an enemy hero with a saved build, run defensive scoring, verify items are ranked by survival time gain.

### Engine Implementation for User Story 1

- [ ] [T003] [US1] Add `_estimate_survival_time(result, defender_total_hp) -> float` static method to `ItemScorer` in `deadlock_sim/engine/scoring.py` — extracts kill_time from SimResult or extrapolates via `defender_hp / overall_dps`
- [ ] [T004] [US1] Add `_score_defensive_fast()` static method to `ItemScorer` in `deadlock_sim/engine/scoring.py` — computes attacker damage type split, calculates weighted EHP baseline, scores each candidate by `(weighted_ehp_with_item - weighted_ehp_baseline) / attacker_dps`
- [ ] [T005] [US1] Add `_score_defensive_sim()` static method to `ItemScorer` in `deadlock_sim/engine/scoring.py` — runs baseline sim (attacker vs defender), re-runs for each candidate item added to defender build, computes survival_time_delta
- [ ] [T006] [US1] Add public `score_defensive()` entry point to `ItemScorer` in `deadlock_sim/engine/scoring.py` — dispatches to `_score_defensive_fast` or `_score_defensive_sim` based on mode, returns `dict[str, DefensiveScore]`
- [ ] [T007] [US1] Add zero-DPS and no-attacker guard clauses in `score_defensive()` in `deadlock_sim/engine/scoring.py` — return empty dict when no attacker configured, return all-zero scores when attacker DPS is zero

### Tests for User Story 1

- [ ] [T008] [P] [US1] Add unit test `test_defensive_score_fast_bullet_attacker` in `tests/test_engine.py` — verify bullet resist items rank above spirit resist items when attacker is gun-heavy (SC-001)
- [ ] [T009] [P] [US1] Add unit test `test_defensive_score_fast_spirit_attacker` in `tests/test_engine.py` — verify spirit resist items rank above bullet resist items when attacker is spirit-heavy (SC-002)
- [ ] [T010] [P] [US1] Add unit test `test_defensive_score_sim_mode` in `tests/test_engine.py` — verify sim-mode survival_time_delta is positive for defensive items and consistent with fast mode ranking (SC-003)
- [ ] [T011] [P] [US1] Add unit test `test_defensive_score_no_attacker` in `tests/test_engine.py` — verify `score_defensive()` returns empty dict when `attacker_hero` is None
- [ ] [T012] [P] [US1] Add unit test `test_defensive_score_zero_dps_attacker` in `tests/test_engine.py` — verify all-zero DefensiveScores returned when attacker DPS is 0
- [ ] [T013] [P] [US1] Add unit test `test_estimate_survival_time` in `tests/test_engine.py` — verify helper returns kill_time when set, extrapolates when not, and returns inf when DPS is 0
- [ ] [T014] [P] [US1] Add unit test `test_defensive_score_survival_per_soul` in `tests/test_engine.py` — verify `survival_per_soul` and `ehp_per_soul` efficiency metrics are computed correctly (division by item cost)

**Checkpoint**: Core defensive scoring engine is complete and tested. US1 acceptance scenarios validated.

---

## Phase 3: User Story 2 — Load Attacker from Saved Builds (Priority: P1) 🎯 MVP

**Goal**: Load a saved build as the enemy attacker so that defensive scoring uses accurate damage profiles (including item bonuses and shred).

**Independent Test**: Load a saved build for the attacker, verify scoring results change compared to base-stats-only scoring.

### Implementation for User Story 2

- [ ] [T015] [US2] Add `_build_attacker_config_from_saved()` helper in `deadlock_sim/ui/gui.py` — constructs a `ScoringConfig` with `attacker_hero`, `attacker_build`, `attacker_boons`, and `attacker_ability_upgrades` from a saved build dict, heroes dict, and items dict
- [ ] [T016] [US2] Add defensive state fields to `_PageState` in `deadlock_sim/ui/gui.py` — add `defensive_mode: bool`, `attacker_hero_name: str`, `attacker_build_data: dict | None`

### Tests for User Story 2

- [ ] [T017] [P] [US2] Add unit test `test_build_attacker_config_from_saved` in `tests/test_engine.py` — verify ScoringConfig is correctly populated from a saved build dict with items, boons, and ability upgrades
- [ ] [T018] [P] [US2] Add unit test `test_defensive_score_with_attacker_shred` in `tests/test_engine.py` — verify that when attacker build includes spirit shred items, spirit resist items are valued less (US2 acceptance scenario 2)

**Checkpoint**: Attacker profile loading works. Defensive scoring reflects real attacker builds.

---

## Phase 4: User Story 3 — Defensive Scoring Mode in Build Tab (Priority: P2)

**Goal**: Toggle the item scorer between offensive and defensive modes in the Build tab GUI, with attacker selection and defensive sort options.

**Independent Test**: Toggle scoring mode from "Offensive" to "Defensive", verify item rankings change to prioritize survival time.

### GUI Implementation for User Story 3

- [ ] [T019] [US3] Add "Offensive / Defensive" radio toggle to Build tab in `deadlock_sim/ui/gui.py` — place next to the existing Sort By dropdown, default to "Offensive"
- [ ] [T020] [US3] Add attacker hero dropdown to Build tab in `deadlock_sim/ui/gui.py` — visible only when defensive mode is active, populated from loaded heroes list
- [ ] [T021] [US3] Add attacker saved-build dropdown to Build tab in `deadlock_sim/ui/gui.py` — visible only when defensive mode is active, filtered by selected attacker hero, reads from localStorage saved builds
- [ ] [T022] [US3] Add `_DEFENSIVE_SORT_KEYS` and `_DEFENSIVE_SIM_SORT_KEYS` dicts to `deadlock_sim/ui/gui.py` — define defensive sort options: Survival Time Δ, EHP Δ, Survival/Soul, EHP/Soul, Sim Survival Δ
- [ ] [T023] [US3] Update sort dropdown population logic in `deadlock_sim/ui/gui.py` — when defensive mode is active, replace offensive sort keys with defensive sort keys
- [ ] [T024] [US3] Wire defensive scoring into shop refresh logic in `deadlock_sim/ui/gui.py` — when defensive mode + defensive sort selected, call `ItemScorer.score_defensive()` instead of `score_candidates()`, pass attacker config from `_PageState`
- [ ] [T025] [US3] Update shop card score badge display in `deadlock_sim/ui/gui.py` — show survival time delta (e.g., "+1.8s") instead of DPS delta when defensive scores are active
- [ ] [T026] [US3] Add attacker DPS summary info row in `deadlock_sim/ui/gui.py` — display "Attacker: {hero} ({build}) — {dps} DPS ({bullet_pct}% bullet, {spirit_pct}% spirit)" when defensive mode is active
- [ ] [T027] [US3] Add "Select an attacker" prompt in `deadlock_sim/ui/gui.py` — when defensive mode is active but no attacker selected, show prompt instead of scored items

### Tests for User Story 3

- [ ] [T028] [US3] Add Playwright integration test `test_defensive_mode_toggle` in `tests/test_gui.py` — verify toggling to defensive mode shows attacker selector and changes sort options (SC-004 responsiveness)

**Checkpoint**: GUI defensive mode is complete. Users can toggle modes and see defensive rankings.

---

## Phase 5: CLI Parity (Priority: P2)

**Goal**: Add defensive scoring menu option to the CLI for interface parity.

- [ ] [T029] [US3] Add "Defensive Item Scoring" menu option to CLI main menu in `deadlock_sim/ui/cli.py` — prompt for attacker hero selection, attacker item build (reusing `_select_items()`), defender hero + build
- [ ] [T030] [US3] Add defensive results table display in `deadlock_sim/ui/cli.py` — format results as ranked table with columns: rank, item name, survival time Δ, EHP Δ, per-soul efficiency

**Checkpoint**: CLI and GUI have feature parity for defensive scoring.

---

## Phase 6: Polish & Edge Cases

**Purpose**: Handle edge cases and cross-cutting concerns.

- [ ] [T031] [P] [US1] Handle mixed offense/defense items (e.g., Leech) in `_score_defensive_fast()` in `deadlock_sim/engine/scoring.py` — include lifesteal as bonus EHP: `lifesteal_pct * attacker_dps * expected_fight_duration`
- [ ] [T032] [P] [US1] Add unit test `test_defensive_score_mixed_item` in `tests/test_engine.py` — verify items with both offensive and defensive stats (e.g., Leech) produce non-zero defensive scores

**Checkpoint**: All edge cases handled. Feature is complete.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Data Models)**: No dependencies — can start immediately
- **Phase 2 (US1 Engine)**: Depends on Phase 1 (T001, T002) — BLOCKS all scoring logic
- **Phase 3 (US2 Attacker Loading)**: Depends on Phase 2 (T006) — needs `score_defensive()` entry point
- **Phase 4 (US3 GUI)**: Depends on Phase 2 (T006) and Phase 3 (T015, T016) — needs engine + attacker config helper
- **Phase 5 (CLI)**: Depends on Phase 2 (T006) — engine must exist
- **Phase 6 (Polish)**: Depends on Phase 2 — engine must exist for edge case handling

### Task-Level Dependencies

| Task | Depends On | Reason |
|------|-----------|--------|
| T003 | T001 | Uses DefensiveScore dataclass |
| T004 | T001, T002 | Uses DefensiveScore and ScoringConfig attacker fields |
| T005 | T001, T002, T003 | Uses DefensiveScore, ScoringConfig, and _estimate_survival_time |
| T006 | T004, T005 | Dispatches to both fast and sim methods |
| T007 | T006 | Adds guard clauses to score_defensive() |
| T008–T014 | T006, T007 | Tests require complete engine |
| T015 | T002 | Builds ScoringConfig with attacker fields |
| T016 | — | Independent state addition |
| T017 | T015 | Tests the helper function |
| T018 | T006 | Tests engine behavior with shred |
| T019–T027 | T006, T015, T016 | GUI needs engine, attacker config, and state |
| T029–T030 | T006 | CLI needs engine entry point |
| T031 | T004 | Extends fast scoring with lifesteal |
| T032 | T031 | Tests mixed item handling |

### Parallel Opportunities

```
Phase 1:  T001 ─┬─ (parallel)
          T002 ─┘

Phase 2:  T003 → T004 ─┬─ → T006 → T007
                 T005 ──┘
          T008–T014 all parallel after T007

Phase 3:  T015 ─┬─ (parallel after T006)
          T016 ─┘
          T017, T018 parallel after T015

Phase 4:  T019 → T020 → T021 (sequential — UI build-up)
          T022, T023 parallel with T019
          T024 depends on T022, T023
          T025, T026, T027 parallel after T024

Phase 5:  T029 → T030 (sequential)

Phase 6:  T031, T032 parallel (after T004)
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Data Models (T001, T002)
2. Complete Phase 2: US1 Engine + Tests (T003–T014)
3. Complete Phase 3: US2 Attacker Loading + Tests (T015–T018)
4. **STOP and VALIDATE**: Run `python -m pytest tests/test_engine.py -k defensive` — all pass
5. Engine is fully functional and testable via code

### Incremental Delivery

1. Phases 1–3 → Engine MVP ready (scorable from code/tests)
2. Add Phase 4 → GUI toggle and attacker selector working
3. Add Phase 5 → CLI parity
4. Add Phase 6 → Edge cases polished

---

## Notes

- [P] tasks = different files, no dependencies
- [US#] label maps task to specific user story for traceability
- Engine tasks (Phase 2) form the critical path — prioritize these
- GUI tasks are sequential within a logical group (radio → dropdown → wiring)
- All engine modifications have corresponding test tasks
- Commit after each task or logical group
