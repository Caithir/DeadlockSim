# Tasks: Ability Upgrade Optimizer

**Input**: Design documents from `/specs/021-ability-upgrade-optimizer/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Included — plan.md section 5 defines five explicit test cases.

**Organization**: Tasks are grouped by phase. US1 (Rank Upgrades by DPS) and US2 (AP Budget Awareness) are both P1 and satisfied by the same engine function, so they share a phase. US3 (Build Tab Integration) is P2 and in a separate phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Data Model (Shared Infrastructure)

**Purpose**: Add the `UpgradeCandidate` result dataclass used by the engine and both UIs.

- [ ] T001 [US1] Add `UpgradeCandidate` dataclass to `deadlock_sim/models.py` — fields: `ability_index: int`, `ability_name: str`, `tier: int`, `ap_cost: int`, `spirit_dps_delta: float`
- [ ] T002 [US1] Export `UpgradeCandidate` from `deadlock_sim/engine/__init__.py` alongside existing exports

**Checkpoint**: `UpgradeCandidate` importable from `deadlock_sim.engine`. No behavior yet.

---

## Phase 2: User Story 1 — Rank Ability Upgrades by DPS Impact (P1) 🎯 MVP + User Story 2 — AP Budget Awareness (P1) 🎯 MVP

**Goal**: Engine function that iterates all unpicked ability upgrades, computes spirit DPS delta for each via `hero_total_spirit_dps()`, filters by AP budget, and returns a sorted list.

**Independent Test (US1)**: Select a hero with unspent AP; verify a sorted list shows each unpicked upgrade with its spirit DPS delta.

**Independent Test (US2)**: With 3 AP remaining, verify only upgrades costing ≤ 3 AP are shown.

### Tests (write first — must FAIL before T008) ⚠️

- [ ] T003 [P] [US1] Add `test_rank_returns_sorted_candidates` in `tests/test_engine.py` — call `rank_ability_upgrades()` with a hero with known abilities and no upgrades; verify results are sorted by `spirit_dps_delta` descending and all abilities appear
- [ ] T004 [P] [US2] Add `test_rank_respects_ap_budget` in `tests/test_engine.py` — call with `ap_remaining=1`; verify only T1 candidates (cost=1) are returned and no T2/T3 candidates appear
- [ ] T005 [P] [US1] Add `test_rank_skips_fully_upgraded` in `tests/test_engine.py` — set ability 0 to `{0: [1, 2, 3]}` (T3); verify ability 0 does not appear in results
- [ ] T006 [P] [US2] Add `test_rank_empty_when_no_ap` in `tests/test_engine.py` — call with `ap_remaining=0`; verify empty list is returned
- [ ] T007 [P] [US1] Add `test_rank_includes_next_tier_only` in `tests/test_engine.py` — with T1 taken on ability 0 (`{0: [1]}`); verify the candidate for ability 0 is T2 (not T1 or T3)

### Implementation

- [ ] T008 [US1] [US2] Implement `DamageCalculator.rank_ability_upgrades()` as a `@staticmethod` in `deadlock_sim/engine/damage.py` — import `ABILITY_TIER_COSTS` from `deadlock_sim.data`; accept `hero`, `current_upgrades`, `ap_remaining`, and all passthrough args for `hero_total_spirit_dps()`; compute baseline DPS; iterate each ability to find next tier; filter by AP cost; compute trial DPS delta; return sorted `list[UpgradeCandidate]`

**Checkpoint**: All five tests (T003–T007) pass. Engine function complete for US1 + US2. No UI yet.

---

## Phase 3: User Story 3 — Build Tab & CLI Integration (P2)

**Goal**: Surface upgrade recommendations in the GUI Build tab and as a new CLI menu option. Both call the same `DamageCalculator.rank_ability_upgrades()` engine function.

**Independent Test (GUI)**: Open Build tab with a hero selected; verify "Suggested Upgrades" list appears near the ability upgrade section showing top-ranked upgrades.

**Independent Test (CLI)**: Run CLI, select "Ability Upgrade Optimizer"; verify formatted table of ranked upgrades is printed.

### Implementation

- [ ] T009 [P] [US3] Add "Suggested Upgrades" panel in `deadlock_sim/ui/gui.py` — inside `refresh_build_display()`, after the ability upgrade area (~line 2220), call `DamageCalculator.rank_ability_upgrades()` with current build state; render a compact list showing ability name, tier, AP cost, and `+X.X Spirit DPS` delta; only show when `ap_remaining > 0` and at least one candidate exists
- [ ] T010 [US3] Add click-to-apply handler for suggestions in `deadlock_sim/ui/gui.py` — clicking a suggested upgrade row updates `state.build_ability_upgrades` for the current hero and calls `refresh_build_display()` to re-rank
- [ ] T011 [P] [US3] Add "Ability Upgrade Optimizer" CLI option in `deadlock_sim/ui/cli.py` — append to `MAIN_MENU` list; implement `display_ability_optimizer()` function that prompts for hero, boon level, and current upgrades; calls `DamageCalculator.rank_ability_upgrades()`; prints a formatted table (Rank | Ability | Tier | AP Cost | Spirit DPS Delta); add dispatch branch in `run_cli()`

**Checkpoint**: GUI shows suggestions in Build tab; CLI prints ranked table. Both respect AP budget. Clicking a GUI suggestion applies the upgrade and refreshes the list.

---

## Phase 4: Polish & Validation

**Purpose**: End-to-end validation of all acceptance scenarios.

- [ ] T012 Validate acceptance scenarios from spec.md — run through all AC scenarios for US1 (Infernus at 10 boons, T1 already taken, cooldown-only upgrade), US2 (1 AP remaining, 0 AP remaining, mixed tiers), and US3 (Build tab panel visible, click-to-apply refreshes)
- [ ] T013 [P] Verify performance goal SC-001 — confirm all candidates scored in <200ms by timing `rank_ability_upgrades()` with a worst-case hero (4 abilities × 3 tiers)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Data Model)**: No dependencies — start immediately
- **Phase 2 (Engine + Tests)**: Depends on Phase 1 (T001, T002) — BLOCKS US1/US2 implementation
- **Phase 3 (UI Integration)**: Depends on Phase 2 (T008) — engine function must exist
- **Phase 4 (Validation)**: Depends on Phase 3 — all features must be implemented

### Task Dependencies

```
T001 → T002 → T003..T007 (parallel) → T008 → T009 (parallel with T011) → T010
                                            → T011
                                       T008 → T012, T013 (parallel, after Phase 3)
```

### Within Each Phase

- **Phase 1**: T001 before T002 (model must exist before export)
- **Phase 2**: Tests T003–T007 are all parallelizable (same file, no conflicts — each is an independent test function). T008 follows after all tests are written.
- **Phase 3**: T009 and T011 are parallelizable (different files: gui.py vs cli.py). T010 depends on T009 (panel must exist before click handler).
- **Phase 4**: T012 and T013 are parallelizable.

### Parallel Opportunities

```
# Phase 2 tests — all independent, write simultaneously:
T003: test_rank_returns_sorted_candidates
T004: test_rank_respects_ap_budget
T005: test_rank_skips_fully_upgraded
T006: test_rank_empty_when_no_ap
T007: test_rank_includes_next_tier_only

# Phase 3 UI — different files, no conflicts:
T009: GUI suggestion panel (gui.py)
T011: CLI menu option (cli.py)

# Phase 4 — independent validations:
T012: Acceptance scenario walkthrough
T013: Performance benchmark
```

---

## Implementation Strategy

### MVP First (US1 + US2 — Phase 1 + Phase 2)

1. Complete Phase 1: Data model (T001–T002)
2. Complete Phase 2: Tests then engine function (T003–T008)
3. **STOP and VALIDATE**: All 5 engine tests pass, `rank_ability_upgrades()` works correctly
4. Engine is usable programmatically even without UI

### Full Feature (Add US3 — Phase 3 + Phase 4)

5. Complete Phase 3: GUI panel + CLI option (T009–T011)
6. Complete Phase 4: Validation + performance check (T012–T013)
7. Feature complete — all acceptance criteria met

---

## Notes

- US1 and US2 are combined in Phase 2 because the AP budget filter (US2) is a guard clause inside the same `rank_ability_upgrades()` loop that computes DPS deltas (US1). Splitting them would create artificial boundaries.
- `ABILITY_TIER_COSTS` already exists in `deadlock_sim/data.py` as `[1, 2, 5]` for T1/T2/T3. No new constants needed.
- `hero_total_spirit_dps()` is a `@classmethod` on `DamageCalculator` in `deadlock_sim/engine/damage.py` — the new function reuses it directly.
- The GUI already computes `ap_remaining` and `cur_ab_map` inside `refresh_build_display()` — T009 reuses those locals.
- The CLI already has `_pick_hero()` and `_prompt_int()` helpers — T011 reuses them.
