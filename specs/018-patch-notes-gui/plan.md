# Implementation Plan: Patch Notes GUI Tab

**Branch**: `018-patch-notes-gui` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/018-patch-notes-gui/spec.md`

## Summary

Add a "Patch Notes" tab to the NiceGUI web interface that surfaces the existing `patchnotes.py` engine — displaying parsed patch changes grouped by hero/item with buff/nerf color-coding, and providing a "Build Impact" analysis that evaluates the current build under pre-patch vs post-patch data to show DPS/EHP/TTK deltas. The CLI already has a `deadlock-sim-patch` entry point; this feature brings parity to the GUI.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: NiceGUI ≥ 3.0, existing `deadlock_sim.patchnotes` module
**Storage**: `data/patches/*.txt` (existing file-based patch cache)
**Testing**: pytest + Playwright integration tests (existing pattern in `tests/test_gui.py`)
**Target Platform**: Browser (localhost NiceGUI server)
**Project Type**: Desktop web app (NiceGUI)
**Performance Goals**: Patch changes render < 1s, build impact analysis < 2s (per SC-001/SC-002)
**Constraints**: No new runtime dependencies; purely UI + engine wiring
**Scale/Scope**: Single new tab, ~300-400 lines of GUI code, ~50 lines of engine helper

## Constitution Check

### I. Pure Calculation Engine — COMPLIANT
All patch parsing, diffing, and applying logic already lives in `patchnotes.py` (data layer). The new `BuildImpactAnalyzer` helper (computing before/after build metrics) will be a `@staticmethod` engine method in `engine/builds.py` or a new small module. No calculation logic in the GUI.

### II. API-First Data — COMPLIANT
Patch notes originate from the Deadlock forum (external source). Hero/item data comes from the API cache. No new hardcoded data.

### III. Strict Layer Separation — COMPLIANT
- `patchnotes.py` (data layer) → parses and diffs patches using `models`
- `engine/builds.py` → new `evaluate_build_impact()` static method using existing `BuildEngine` and `DamageCalculator`
- `ui/gui.py` → new `_build_patch_notes_tab()` renders results, calls data/engine layers only
- No upward dependencies introduced.

### IV. Dual Interface Parity — PARTIAL EXCEPTION
The CLI already has `deadlock-sim-patch` (fetch + diff + apply). The GUI adds visual display + build impact analysis. The build impact feature is GUI-specific because it requires the interactive build state. **Exception**: Build impact analysis is not replicated in CLI. The CLI can already fetch/diff/apply patches, which is equivalent functionality for a terminal context.

### V. Simplicity First — COMPLIANT
No new abstractions. The `BuildImpact` dataclass is a simple before/after pair. The tab function follows the identical pattern as the 5 existing tabs. No plugin system or generic framework.

### VI. Mechanic Extensibility — COMPLIANT
Patch changes are already parameterized via `PatchChange` dataclass with `old_value`/`new_value` fields. Build impact uses existing `BuildResult` which tracks all stats as fields. New game mechanics added to the engine will automatically appear in impact analysis.

## Design

### 1. New Data Model: `BuildImpact`

Add to `deadlock_sim/models.py`:

```python
@dataclass
class BuildImpact:
    """Before/after comparison of a build across a patch."""
    hero_name: str = ""
    patch_date: str = ""

    # Before patch
    before_bullet_dps: float = 0.0
    before_spirit_dps: float = 0.0
    before_combined_dps: float = 0.0
    before_effective_hp: float = 0.0
    before_ttk: float = 0.0

    # After patch
    after_bullet_dps: float = 0.0
    after_spirit_dps: float = 0.0
    after_combined_dps: float = 0.0
    after_effective_hp: float = 0.0
    after_ttk: float = 0.0

    # Deltas (positive = buff, negative = nerf)
    delta_bullet_dps: float = 0.0
    delta_spirit_dps: float = 0.0
    delta_combined_dps: float = 0.0
    delta_effective_hp: float = 0.0
    delta_ttk: float = 0.0
```

### 2. Engine Addition: `BuildEngine.evaluate_build_impact()`

Add a `@staticmethod` to `engine/builds.py`:

```python
@staticmethod
def evaluate_build_impact(
    hero: HeroStats,
    build: Build,
    changes: list[PatchChange],
    boons: int = 0,
    combat_config: CombatConfig | None = None,
) -> BuildImpact:
```

**Logic**:
1. Compute `BuildResult` for the current (post-patch) hero+build using existing `BuildEngine.evaluate_build()`
2. Create a deep copy of `hero` and `items`
3. Reverse-apply patch changes to the copy (swap `new_value` → `old_value` for the hero's stats)
4. Compute `BuildResult` for the pre-patch copy
5. Calculate deltas and return `BuildImpact`

This approach avoids needing two separate datasets. We use the current data as "after" and reverse-engineer "before" by undoing the patch changes.

### 3. GUI Tab: `_build_patch_notes_tab()`

Add to `deadlock_sim/ui/gui.py` following the existing tab pattern:

```python
def _build_patch_notes_tab(state: _PageState) -> None:
```

**Layout**:

```
┌─────────────────────────────────────────────────────────────┐
│  Patch: [dropdown: 03-25-2026 ▼]   [Fetch Latest] button   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Hero Changes (grouped, collapsible)                        │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ ▼ Infernus                                              ││
│  │   Afterburn DPS: 12 → 14           [+2]  ██ green       ││
│  │   Afterburn T1 DPS: +14 → +16      [+2]  ██ green       ││
│  │   Concussive Combustion T2: ...           ██ green       ││
│  │ ▼ Kelvin                                                ││
│  │   Frost Grenade scaling: 0.8 → 0.7 [-0.1] ██ red        ││
│  │   ...                                                   ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  Item Changes (grouped, collapsible)                        │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ (if any item changes parsed)                            ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  ┌─── Build Impact ────────────────────────────────────────┐│
│  │ [Analyze Impact] button                                 ││
│  │                                                         ││
│  │  Metric         Before    After    Delta                ││
│  │  Bullet DPS     142.3     148.7    +6.4  ██ green       ││
│  │  Spirit DPS      87.1      91.5    +4.4  ██ green       ││
│  │  Combined DPS   229.4     240.2   +10.8  ██ green       ││
│  │  Effective HP   1823      1823      0.0                 ││
│  │  TTK (s)          4.2       3.9    -0.3  ██ green       ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

**Key behaviors**:
- **Patch dropdown**: Populated from `patchnotes.list_saved_patches()`. Defaults to the most recent.
- **Fetch Latest button**: Calls `patchnotes.fetch_latest_patch()` + `save_patch()`, then reloads the dropdown.
- **Change grouping**: Group `PatchChange` objects by `change.hero` (hero changes) and `change.item` (item changes) using `ui.expansion()` panels.
- **Color-coding**: For numeric changes, compare `old_numeric` vs `new_numeric`. If the stat is one where higher = better (damage, DPS, duration, radius), green for increase, red for decrease. For stats where lower = better (cooldown), invert. Non-numeric/mechanical changes shown in neutral gray.
- **Build Impact**: Only enabled when a hero is selected in the Build tab. Reads `state.build_items`, `state.build_hero_name`, `state.build_boons` from `_PageState`.
- **Empty state**: If no patches exist, show a message with a "Fetch Latest" button.

### 4. Color-coding Heuristic

A small helper function to determine buff/nerf direction:

```python
_LOWER_IS_BETTER = {"cooldown", "cd"}

def _is_buff(change: PatchChange) -> bool | None:
    """Return True if buff, False if nerf, None if indeterminate."""
    if change.old_numeric is None or change.new_numeric is None:
        return None
    delta = change.new_numeric - change.old_numeric
    if delta == 0:
        return None
    stat_lower = change.stat.lower()
    invert = any(kw in stat_lower for kw in _LOWER_IS_BETTER)
    if invert:
        return delta < 0  # lower cooldown = buff
    return delta > 0  # higher damage = buff
```

### 5. Tab Integration

In `run_gui()`, add the new tab alongside existing ones:

```python
tab_patch = ui.tab("Patch Notes")
# ...
with ui.tab_panel(tab_patch):
    _build_patch_notes_tab(state)
```

### 6. CLI Parity Note

The CLI already has `deadlock-sim-patch` via `patchnotes._cli_main()`, which can fetch, diff, and apply patches. The GUI tab surfaces this in a visual way with the addition of build impact analysis. No new CLI commands are needed.

## Files Modified

| File | Change |
|------|--------|
| `deadlock_sim/models.py` | Add `BuildImpact` dataclass |
| `deadlock_sim/engine/builds.py` | Add `BuildEngine.evaluate_build_impact()` static method |
| `deadlock_sim/ui/gui.py` | Add `_build_patch_notes_tab()`, `_is_buff()` helper; register new tab in `run_gui()` |
| `tests/test_gui.py` | Add Playwright test for Patch Notes tab navigation and content rendering |

## Files NOT Modified

| File | Reason |
|------|--------|
| `deadlock_sim/patchnotes.py` | Existing API is sufficient: `list_saved_patches()`, `load_saved_patch()`, `parse_patch_notes()`, `diff_patch()`, `apply_patch()`, `fetch_latest_patch()`, `save_patch()` |
| `deadlock_sim/ui/cli.py` | CLI parity already exists via `deadlock-sim-patch` entry point |
| `deadlock_sim/ui/state.py` | No new persistent state needed; patch selection is tab-local |

## Implementation Sequence

1. **Add `BuildImpact` dataclass** to `models.py`
2. **Add `evaluate_build_impact()`** to `engine/builds.py` — testable independently
3. **Build `_build_patch_notes_tab()`** in `gui.py` — change list display with grouping and color-coding
4. **Wire build impact button** — connect to engine, display results table
5. **Register tab** in `run_gui()` with `_on_tab_change` handling
6. **Add integration test** — Playwright test navigates to Patch Notes tab, verifies grouped changes render

## Edge Cases

| Case | Handling |
|------|----------|
| No patch files exist | Show "No patches available" message + prominent "Fetch Latest" button |
| Fetch fails (network error) | Catch `requests.RequestException`, show error notification via `ui.notify()` |
| No hero selected for build impact | Disable "Analyze Impact" button with tooltip "Select a hero in the Build tab first" |
| Patch changes an item not in build | Show in the change list normally; build impact only reflects owned items |
| New hero/item in patch (not in data) | Show raw line with "Unknown entity" styling; `diff_patch()` already handles this as `manual_review` |
| Non-numeric / mechanical changes | Display with neutral/gray styling, no delta badge |
| Reverse-apply fails for a stat | Skip that stat in pre-patch calculation; note in impact results |

## Complexity Tracking

No constitution violations. No complexity exceptions needed.
