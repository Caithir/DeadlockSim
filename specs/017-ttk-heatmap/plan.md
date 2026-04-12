# Implementation Plan: TTK Heatmap

**Branch**: `017-ttk-heatmap` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/017-ttk-heatmap/spec.md`

## Summary

Add a TTK Heatmap tab to the GUI and a corresponding CLI command that visualizes the existing `ComparisonEngine.cross_ttk_matrix()` output as an N×N color-coded grid. Users select 2–10 heroes, set a boon level, and generate a heatmap where rows = attackers, columns = defenders, cells colored green (fast kill) → red (slow kill) with hover tooltips showing exact TTK values. No new engine logic is needed — the feature is purely a visualization layer over the existing engine call.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: NiceGUI (GUI), existing engine (`ComparisonEngine.cross_ttk_matrix`)  
**Storage**: N/A (in-memory computation, API cache for hero data)  
**Testing**: pytest + Playwright (integration tests against live GUI)  
**Target Platform**: localhost web UI + CLI terminal  
**Project Type**: desktop-app (local web UI + CLI)  
**Performance Goals**: 8×8 matrix in under 5 seconds (SC-001)  
**Constraints**: N² TTK computations; subset capped at 10 heroes for responsiveness  
**Scale/Scope**: Single new GUI tab, single new CLI menu option

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Pure Calculation Engine — COMPLIANT
No new engine logic is required. The feature delegates entirely to `ComparisonEngine.cross_ttk_matrix()`, which is a stateless `@staticmethod` in `deadlock_sim/engine/comparison.py`. It returns `dict[str, dict[str, float]]` — pure data, no I/O.

### II. API-First Data — COMPLIANT
Hero data comes from the API cache via `load_heroes()`. No new data sources are introduced.

### III. Strict Layer Separation — COMPLIANT
The GUI tab and CLI command import from `engine.comparison` and `data`. No upward or circular dependencies are introduced. The heatmap rendering is purely UI-layer code.

### IV. Dual Interface Parity — COMPLIANT WITH EXCEPTION
The GUI gets a full color-coded heatmap tab. The CLI gets a new "TTK Matrix" menu option that prints the matrix as an ASCII table. The CLI cannot render color gradients, so it will show numeric values with simple column alignment. This is an acceptable fidelity difference — both interfaces expose the same underlying data.

### V. Simplicity First — COMPLIANT
No new abstractions, frameworks, or generic utilities. The GUI tab is a single function. Color mapping uses a direct linear interpolation — no color library needed.

### VI. Mechanic Extensibility — COMPLIANT
Combat parameters are passed via `CombatConfig` dataclass. The boon level, accuracy, and other settings flow through the existing config mechanism. No hardcoded game values are introduced.

## Project Structure

### Documentation (this feature)

```text
specs/017-ttk-heatmap/
├── spec.md              # Feature specification
└── plan.md              # This file
```

### Source Code (files to modify/create)

```text
deadlock_sim/
├── engine/
│   └── comparison.py    # EXISTING — no changes needed
├── ui/
│   ├── gui.py           # MODIFY — add heatmap tab
│   └── cli.py           # MODIFY — add "TTK Matrix" menu option
tests/
└── test_gui.py          # MODIFY — add heatmap integration test
```

**Structure Decision**: No new files. The heatmap tab is a function in `gui.py` and the CLI option is a function in `cli.py`. Both delegate to the existing `ComparisonEngine.cross_ttk_matrix()`.

---

## Design

### 1. Engine Layer — No Changes

The existing engine call is sufficient:

```python
# deadlock_sim/engine/comparison.py (EXISTING, unchanged)
ComparisonEngine.cross_ttk_matrix(
    heroes: dict[str, HeroStats],
    config: CombatConfig,
    hero_names: list[str] | None = None,
) -> dict[str, dict[str, float]]
```

Returns `matrix[attacker_name][defender_name] = ttk_seconds` (ideal TTK). This is already tested in `test_engine.py::TestComparison::test_cross_ttk_matrix`.

**Note**: The current implementation uses `result.ttk_seconds` (ideal TTK, not realistic TTK). The spec does not specify which TTK variant to display. Since the engine returns the full `TTKResult` internally but `cross_ttk_matrix` only stores `ttk_seconds`, the plan will use ideal TTK. If realistic TTK is later desired, the engine method can be updated to store `realistic_ttk` instead — a single-line change.

### 2. GUI Tab — `_build_ttk_heatmap_tab()`

**Location**: `deadlock_sim/ui/gui.py`

**UI Layout**:
```
┌─────────────────────────────────────────────────────┐
│ [Multi-select: Heroes (2–10)]  [Boon: 0-35 slider] │
│ [Accuracy: 0-100% slider]     [Generate] button     │
├─────────────────────────────────────────────────────┤
│          Def1    Def2    Def3    Def4    Def5        │
│  Atk1  [ 2.1s] [ 3.4s] [ 1.8s] [ 4.0s] [ 2.9s]   │
│  Atk2  [ 3.0s] [ 2.5s] [ 3.9s] [ 2.2s] [ 3.1s]   │
│  Atk3  [ 1.9s] [ 2.8s] [ 2.3s] [ 3.5s] [ 2.7s]   │
│  ...                                                 │
└─────────────────────────────────────────────────────┘
```

**Implementation approach**:

1. **Hero selection**: NiceGUI `ui.select` with `multiple=True`, populated from `_hero_names`. Capped at 10 selections.
2. **Boon slider**: `ui.slider(min=0, max=35, value=10)`.
3. **Accuracy slider**: `ui.slider(min=0, max=100, value=50)` — feeds `CombatConfig.accuracy`.
4. **Generate button**: Calls `ComparisonEngine.cross_ttk_matrix()` with a `CombatConfig(boons=boon_val, accuracy=accuracy_val/100)`.
5. **Heatmap grid**: Rendered as an HTML `<table>` via `ui.html()`. Each cell `<td>` gets:
   - Background color: linear interpolation from green (`#22c55e`, fast) → yellow (`#eab308`, mid) → red (`#ef4444`, slow), based on the cell's TTK relative to the matrix min/max.
   - Text: TTK value formatted as `X.Xs`.
   - Title attribute: `"{Attacker} → {Defender}: {TTK}s"` for hover tooltip.
6. **Edge case — TTK exceeds duration or is 0**: Cells where TTK is 0 (e.g., cannot kill) display "∞" with a dark/gray background.

**Color interpolation function** (inline helper, not a separate module):

```python
def _ttk_cell_color(ttk: float, min_ttk: float, max_ttk: float) -> str:
    """Map TTK to green→yellow→red hex color."""
    if max_ttk <= min_ttk:
        return "#eab308"  # all same — yellow
    t = (ttk - min_ttk) / (max_ttk - min_ttk)  # 0=fastest, 1=slowest
    if t <= 0.5:
        # green → yellow
        r = int(34 + (234 - 34) * (t / 0.5))
        g = int(197 + (179 - 197) * (t / 0.5))
        b = int(94 + (8 - 94) * (t / 0.5))
    else:
        # yellow → red
        s = (t - 0.5) / 0.5
        r = int(234 + (239 - 234) * s)
        g = int(179 + (68 - 179) * s)
        b = int(8 + (68 - 8) * s)
    return f"#{r:02x}{g:02x}{b:02x}"
```

**Tab registration**: Add to the tab bar in `run_gui()`:
```python
tab_heatmap = ui.tab("TTK Heatmap")
# ...
with ui.tab_panel(tab_heatmap):
    _build_ttk_heatmap_tab()
```

### 3. CLI Command — `display_ttk_matrix()`

**Location**: `deadlock_sim/ui/cli.py`

**Menu integration**: Add `"TTK Matrix"` to `MAIN_MENU` list (after "Hero Rankings").

**Function signature**:
```python
def display_ttk_matrix(heroes: dict[str, HeroStats]) -> None:
```

**Behavior**:
1. Prompt user to select 2–10 heroes (numbered list + comma-separated input).
2. Prompt for boon level (default 0).
3. Prompt for accuracy % (default 50).
4. Call `ComparisonEngine.cross_ttk_matrix(heroes, config, hero_names=selected)`.
5. Print as aligned ASCII table:
   ```
   ═══════════════════════════════════════════════
     TTK MATRIX (Boon 10, 50% accuracy)
   ═══════════════════════════════════════════════
              Abrams   Haze    Seven   Kelvin
   Abrams     3.2s    2.8s     4.1s    3.5s
   Haze       2.1s    2.5s     1.9s    2.7s
   Seven      3.8s    3.0s     3.3s    3.9s
   Kelvin     4.0s    3.6s     3.4s    3.8s
   ```

### 4. Integration Test

**Location**: `tests/test_gui.py`

**Test**: `test_ttk_heatmap_generation`

**Steps**:
1. Navigate to TTK Heatmap tab.
2. Select 3–4 heroes from the multi-select.
3. Set boon level via slider.
4. Click "Generate".
5. Assert the heatmap table element exists and contains expected hero names.
6. Assert cells contain numeric TTK values (regex match `\d+\.\d+s`).

---

## File Change Summary

| File | Action | What Changes |
|------|--------|--------------|
| `deadlock_sim/ui/gui.py` | MODIFY | Add `_build_ttk_heatmap_tab()` function (~80 lines), register tab in `run_gui()` |
| `deadlock_sim/ui/cli.py` | MODIFY | Add `display_ttk_matrix()` function (~40 lines), add to `MAIN_MENU` and dispatch |
| `tests/test_gui.py` | MODIFY | Add `test_ttk_heatmap_generation` test (~25 lines) |

**Total new code**: ~145 lines across 3 files. No new files, no new dependencies.

## Complexity Tracking

No constitution violations. No complexity justifications needed.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Color mapping | Inline helper, not a library | Single call-site, ~15 lines (Principle V) |
| Heatmap rendering | Raw HTML table via `ui.html()` | NiceGUI has no built-in heatmap widget; raw HTML is the simplest approach |
| Hero cap | 10 heroes max | N² computation; 10×10 = 100 TTK calls is responsive, 30×30 = 900 is not |
| CLI fidelity | ASCII table, no color | Terminal color codes are fragile; numeric alignment is sufficient (Principle IV exception) |
