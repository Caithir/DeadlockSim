# Tasks: Build Sharing

**Input**: Design documents from `specs/019-build-sharing/`
**Prerequisites**: plan.md ✅, spec.md ✅

**Organization**: Tasks are grouped by phase — shared infrastructure first, then by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Data model and engine module that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T001 [US1] Add `BuildSnapshot` dataclass to `deadlock_sim/models.py` — fields: `hero_id`, `hero_name`, `item_ids`, `item_names`, `ability_upgrades`, `extra_souls`
- [ ] T002 [US1] Create `deadlock_sim/engine/sharing.py` with `BuildCodec` class — define `VERSION = 1` constant and binary format constants
- [ ] T003 [US1] Implement `BuildCodec.encode(snapshot)` static method in `deadlock_sim/engine/sharing.py` — binary packing via `struct` + base64url encoding
- [ ] T004 [US1] Implement `BuildCodec.decode(code, heroes, items)` static method in `deadlock_sim/engine/sharing.py` — base64url decode + struct unpack + ID resolution with graceful unknown-ID handling
- [ ] T005 [US1] Implement `BuildCodec.snapshot_from_state(hero, items, ability_upgrades, extra_souls)` static method in `deadlock_sim/engine/sharing.py` — converts live UI state objects to `BuildSnapshot`
- [ ] T006 [US1] Export `BuildCodec` from `deadlock_sim/engine/__init__.py` — add import and `__all__` entry

### Engine Tests (Phase 1)

- [ ] T007 [P] [US1] Add `test_build_codec_roundtrip` in `tests/test_engine.py` — encode a full 12-item snapshot, decode it, assert all fields identical
- [ ] T008 [P] [US1] Add `test_build_codec_empty_build` in `tests/test_engine.py` — encode/decode a snapshot with zero items and zero ability upgrades
- [ ] T009 [P] [US1] Add `test_build_codec_deterministic` in `tests/test_engine.py` — encode the same snapshot twice, assert identical output strings
- [ ] T010 [P] [US1] Add `test_build_codec_invalid_code` in `tests/test_engine.py` — pass garbage string to decode, assert `ValueError` raised
- [ ] T011 [P] [US1] Add `test_build_codec_unknown_item_skipped` in `tests/test_engine.py` — decode a code with an item ID not in the items dict, assert item is skipped without error

**Checkpoint**: `BuildCodec` engine is complete and fully tested. All user stories can now proceed.

---

## Phase 2: User Story 1 — Clipboard Build Code (Priority: P1) 🎯 MVP

**Goal**: Copy/paste build codes via clipboard for sharing on Discord, Reddit, etc.

**Independent Test**: Create a build, click "Copy Build Code", paste into "Paste Build Code" on another session, verify the build loads identically.

### GUI Implementation

- [ ] T012 [US1] Add "Copy Build Code" button to the Build tab in `deadlock_sim/ui/gui.py` — calls `BuildCodec.snapshot_from_state()` → `BuildCodec.encode()`, copies result to clipboard via `navigator.clipboard.writeText()`, shows success notification
- [ ] T013 [US1] Add "Paste Build Code" button + import dialog to the Build tab in `deadlock_sim/ui/gui.py` — opens a dialog with text input, on submit calls `BuildCodec.decode()`, restores build state via existing `load_build_from_saved()` path
- [ ] T014 [US1] Add error handling for paste/import in `deadlock_sim/ui/gui.py` — catch `ValueError` from decode, show `ui.notify(error_message, type="negative")`, no crash

### CLI Implementation

- [ ] T015 [P] [US1] Add "Export Build Code" menu option in `deadlock_sim/ui/cli.py` — after build is created, encode via `BuildCodec` and print code string to terminal
- [ ] T016 [P] [US1] Add "Import Build Code" menu option in `deadlock_sim/ui/cli.py` — prompt for code string, decode via `BuildCodec`, display hero/items/boons, offer to run calculations

### GUI Integration Tests

- [ ] T017 [US1] Add `test_copy_paste_build_code` in `tests/test_gui.py` — copy code from one build, paste in import dialog, verify build matches
- [ ] T018 [US1] Add `test_invalid_build_code_shows_error` in `tests/test_gui.py` — paste garbage string, verify error notification appears without crash

**Checkpoint**: US1 is complete. Users can copy/paste build codes via clipboard in both GUI and CLI.

---

## Phase 3: User Story 2 — Shareable URL (Priority: P2)

**Goal**: Generate a URL with the build encoded in query parameters that auto-loads on page open.

**Independent Test**: Generate a URL, open it in a new browser tab, verify the build auto-loads.

### GUI Implementation

- [ ] T019 [US2] Add "Share URL" button to the Build tab in `deadlock_sim/ui/gui.py` — encodes build, constructs `{current_url}?build={code}`, copies URL to clipboard, shows notification
- [ ] T020 [US2] Implement URL query parameter detection on page load in `deadlock_sim/ui/gui.py` — in `index()` page function, read `?build=` param via `ui.run_javascript("new URLSearchParams(window.location.search).get('build')")`, decode and auto-load build
- [ ] T021 [US2] Add error handling for URL loading in `deadlock_sim/ui/gui.py` — handle outdated/invalid codes: skip unknown items with warning notification, show error for corrupted codes

### GUI Integration Tests

- [ ] T022 [US2] Add `test_share_url_loads_build` in `tests/test_gui.py` — generate URL, navigate to it, verify build auto-loads on page open

**Checkpoint**: US2 is complete. Users can share builds via URL links that auto-load in the browser.

---

## Phase 4: User Story 3 — Build Code in Saved Builds (Priority: P3)

**Goal**: Copy build code directly from the saved builds list without loading the build first.

**Independent Test**: Open saved builds, click copy icon on a build card, verify a valid build code is copied.

### Engine Helper

- [ ] T023 [US3] Implement `BuildCodec.snapshot_from_saved(saved_data, heroes, items)` static method in `deadlock_sim/engine/sharing.py` — converts a saved-build dict (localStorage format) to `BuildSnapshot`
- [ ] T024 [US3] Add `test_build_codec_snapshot_from_saved` in `tests/test_engine.py` — verify `snapshot_from_saved` produces a valid `BuildSnapshot` that round-trips through encode/decode

### GUI Implementation

- [ ] T025 [US3] Add copy-code icon button on each saved build card in `deadlock_sim/ui/gui.py` — next to existing Load/Delete buttons, calls `snapshot_from_saved()` → `encode()` → clipboard copy with notification

**Checkpoint**: US3 is complete. Users can share build codes directly from their saved builds library.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and final validation

- [ ] T026 [P] Update `README.md` or `docs/` with build sharing usage instructions (copy/paste, URL sharing, CLI commands)
- [ ] T027 Run full test suite (`pytest tests/`) — verify no regressions across all engine and GUI tests

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Foundation) ─── BLOCKS ALL ──→ Phase 2 (US1/P1) ──→ Phase 3 (US2/P2) ──→ Phase 4 (US3/P3) ──→ Phase 5 (Polish)
```

- **Phase 1**: No dependencies — start immediately. T001 → T002 → T003/T004/T005 (sequential within sharing.py) → T006. Tests T007–T011 are parallelizable after T004.
- **Phase 2 (US1)**: Depends on Phase 1. GUI tasks T012 → T013 → T014 (sequential — same file, same section). CLI tasks T015/T016 are parallel with GUI tasks.
- **Phase 3 (US2)**: Depends on Phase 1. Can start in parallel with Phase 2 if staffed, but recommended after US1 since Share URL button sits in the same button row.
- **Phase 4 (US3)**: Depends on Phase 1 (T023 depends on T002). GUI task T025 depends on T023.
- **Phase 5**: Depends on all desired user stories being complete.

### Parallel Opportunities

- **Within Phase 1**: Engine tests T007–T011 are all [P] — run in parallel after encode/decode are implemented
- **Within Phase 2**: CLI tasks T015/T016 are [P] with GUI tasks T012–T014 (different files)
- **Across Phases**: US2 and US3 engine work could theoretically start after Phase 1, but GUI changes touch the same file (`gui.py`), so sequential is safer

### Within Each User Story

1. Engine/model code first
2. GUI/CLI integration second
3. Tests after implementation (or TDD if preferred)
4. Story complete before moving to next priority

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundation (T001–T011)
2. Complete Phase 2: US1 Clipboard (T012–T018)
3. **STOP and VALIDATE**: Test copy/paste flow end-to-end
4. Deploy/demo if ready — users can already share builds

### Incremental Delivery

1. Phase 1 → Foundation ready
2. Add US1 (clipboard) → Test → Deploy (MVP!)
3. Add US2 (URL sharing) → Test → Deploy
4. Add US3 (saved builds copy) → Test → Deploy
5. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files, no dependencies
- All engine code in `deadlock_sim/engine/sharing.py` is pure/stateless — no I/O, no UI imports
- Binary format uses version byte for future extensibility
- Build codes target < 200 chars (actual ~52 chars for full 12-item build)
- URL length target < 2000 chars (well within limit)
- Commit after each task or logical group
