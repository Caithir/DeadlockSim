# Implementation Plan: Simulation Timeline Chart

**Branch**: `013-simulation-timeline-chart` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/013-simulation-timeline-chart/spec.md`

## Summary

Replace the existing DPS-over-time bar chart in the Simulation tab with a richer, multi-mode timeline visualization. The new chart adds a stacked area cumulative mode, an HP-remaining overlay on a secondary Y axis with a kill marker, and a toggle to switch between cumulative and per-second DPS views. All chart data is derived from the existing `SimResult.timeline` list of `DamageEntry` objects — no engine changes are required. The CLI gets an ASCII per-second DPS table as the parity equivalent.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: NiceGUI ≥ 3.0 (ECharts via `ui.echart`)
**Storage**: N/A (chart is rendered from in-memory `SimResult`)
**Testing**: pytest + Playwright integration tests (existing `tests/test_gui.py` pattern)
**Target Platform**: Web browser (localhost NiceGUI server)
**Project Type**: Desktop web app (NiceGUI)
**Performance Goals**: Chart renders within 500ms of simulation completion (SC-001)
**Constraints**: No new runtime dependencies; ECharts is already available via NiceGUI
**Scale/Scope**: Single tab enhancement; ~150–200 lines of new/modified GUI code

## Constitution Check

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | **Pure Calculation Engine** | ✅ Compliant | No engine changes. Chart data preparation is a pure transformation of `SimResult.timeline` into bucket arrays — implemented as a helper function in GUI code, not in `engine/`. |
| II | **API-First Data** | ✅ N/A | No new game data. Chart visualizes simulation output only. |
| III | **Strict Layer Separation** | ✅ Compliant | All changes are in `ui/gui.py` (and a small CLI table). No new imports into engine modules. The timeline bucketing helper lives in the UI layer since it is presentation logic (bucket sizes, display modes). |
| IV | **Dual Interface Parity** | ✅ Compliant | GUI gets the interactive chart. CLI gets an ASCII per-second DPS breakdown table printed after simulation results, providing equivalent data visibility. Documented exception: CLI cannot render area charts or HP overlays — the tabular per-second breakdown is the reasonable equivalent. |
| V | **Simplicity First** | ✅ Compliant | No new abstractions. One helper function buckets timeline data; the chart config is inline ECharts JSON. No charting library, no chart component framework. |
| VI | **Mechanic Extensibility** | ✅ Compliant | Damage type colors and bucket size are parameterized, not hardcoded inline. New damage types or sources automatically appear in the chart because bucketing iterates `DamageEntry.damage_type`. |

## Project Structure

### Documentation (this feature)

```text
specs/013-simulation-timeline-chart/
├── spec.md              # Feature specification
└── plan.md              # This file
```

### Source Code (files modified)

```text
deadlock_sim/
└── ui/
    ├── gui.py           # MODIFY — replace DPS chart with multi-mode timeline chart
    └── cli.py           # MODIFY — add ASCII per-second DPS table after sim results
tests/
└── test_gui.py          # MODIFY — add timeline chart test
```

No new files are created.

## Design

### 1. Timeline Data Bucketing

A helper function `_bucket_timeline(timeline, duration, bucket_size, cumulative)` transforms `list[DamageEntry]` into chart-ready data structures:

```python
def _bucket_timeline(
    timeline: list[DamageEntry],
    duration: float,
    bucket_size: float = 0.5,
    cumulative: bool = True,
    bidirectional: bool = False,
) -> dict:
    """Bucket timeline events into chart series data.
    
    Returns dict with:
      - time_labels: list[float]  — X axis values
      - series: dict[str, list[float]]  — {source_label: [values per bucket]}
      - damage_types: dict[str, str]  — {source_label: damage_type}
      - combatants: dict[str, str]  — {source_label: "a"|"b"}
    """
```

**Logic**:
1. Compute `n_buckets = max(1, int(duration / bucket_size) + 1)`.
2. For each `DamageEntry`, assign to bucket `min(int(entry.time / bucket_size), n_buckets - 1)`.
3. Group by source (and combatant label if bidirectional).
4. If `cumulative=True`, compute running sums per series.
5. If `cumulative=False`, divide each bucket value by `bucket_size` to get DPS.

This extracts the existing bucketing logic from `_render_results()` into a reusable helper.

### 2. HP Remaining Series

Computed from `SimResult` after bucketing damage:

```python
def _hp_remaining_series(
    timeline: list[DamageEntry],
    initial_hp: float,
    duration: float,
    bucket_size: float = 0.5,
    combatant_filter: str = "a",  # damage dealt BY this combatant reduces HP
) -> list[float]:
    """Compute defender HP remaining at each time bucket."""
```

**Logic**:
1. Start at `initial_hp` (defender's `max_hp + bullet_shield + spirit_shield` from the sim).
2. For each bucket, subtract cumulative damage dealt by the attacker.
3. Clamp to 0.

The initial HP value is obtained from `SimResult`. Currently `SimResult` does not store the defender's initial HP. Two options:
- **Option A**: Compute it as `result.total_damage + result.target_hp_remaining` (works for unidirectional). For bidirectional, equivalent math applies from the respective damage totals.
- **Option B**: Add a `defender_initial_hp` field to `SimResult`.

**Decision**: Option A — no engine change needed. The math `initial_hp = total_damage + target_hp_remaining` is exact for unidirectional. For bidirectional, `initial_hp_b = (result.total_damage or 0) + result.target_hp_remaining` and `initial_hp_a = (result.defender_total_damage or 0) + (result.attacker_hp_remaining or 0)`.

### 3. Chart Configuration (ECharts)

The chart is rendered with `ui.echart()` using a stacked area chart (cumulative mode) or stacked bar chart (per-second mode). Key ECharts config:

**Cumulative mode** (default):
- `type: "line"`, `areaStyle: {}`, `stack: "damage"` for damage layers
- Secondary `yAxis` for HP remaining (line, no stack, dashed, red)
- Kill marker as `markPoint` on the HP line where value hits 0

**Per-second mode**:
- `type: "bar"`, `stack: "dps"` (same as current chart)
- HP overlay still shown as a line on secondary axis

**Color scheme** (reuse existing):
- Bullet: `#f59e0b` (amber)
- Spirit: `#a855f7` (purple)
- Melee: `#22c55e` (green)
- Item procs inherit from their damage type
- HP line: `#ef4444` (red), dashed
- Bidirectional combatant B uses muted variants (existing `_dtype_colors_b`)

### 4. Toggle Control

A `ui.toggle` above the chart switches between "Cumulative" and "Per-Second" views. On change, the chart re-renders with `chart.update()` (in-place ECharts option update, no full page rebuild).

Implementation approach:
- Store `SimResult` reference in closure scope (already the pattern in `_render_results`)
- Toggle callback calls the bucketing helper with the new mode and calls `chart.options = new_options; chart.update()`

### 5. CLI Parity

After existing simulation result output in `cli.py`, print a per-second DPS table:

```
═ DPS BY TIME INTERVAL ═════════════════════
 Time     Bullet   Spirit    Melee    Total
 0.0-0.5    120.0     0.0      0.0    120.0
 0.5-1.0    135.2    45.0      0.0    180.2
 1.0-1.5    128.0    90.0     63.0    281.0
 ...
```

This is a simple tabular representation using the same bucketing logic.

### 6. Edge Cases

| Case | Handling |
|------|----------|
| Zero spirit damage (gun-only build) | Spirit series simply has all-zero values and won't appear in legend (ECharts auto-hides empty series via `legend.data` filtering) |
| Very short simulation (< 2s) | Use smaller bucket size (0.25s) when duration < 3s to maintain granularity |
| Shields | Shields are consumed during the sim; `target_hp_remaining` already accounts for them. The HP line starts at effective HP (HP + shields) and tracks total damage dealt. No separate shield line (Simplicity First). |
| Bidirectional mode | Two HP lines (one per combatant), two damage stacks labeled with (A)/(B). Reuses existing combatant labeling pattern. |

### 7. Modifications to Existing Code

**`deadlock_sim/ui/gui.py` — `_render_results()`**:
- Replace the existing "DPS Over Time" chart section (lines ~3188–3240) with the new multi-mode chart.
- Extract bucketing logic into `_bucket_timeline()` helper (defined at module level in gui.py, near existing chart section).
- Add `_hp_remaining_series()` helper.
- Add view mode toggle (`ui.toggle`).
- Render chart with dual Y axes, conditional series based on mode.

**`deadlock_sim/ui/cli.py`**:
- Add a `_print_dps_timeline()` function that takes `SimResult` and prints the ASCII table.
- Call it from wherever the CLI currently displays simulation results.

### 8. Test Plan

One new Playwright integration test in `tests/test_gui.py`:

- **test_simulation_timeline_chart**: 
  1. Select a hero and run a simulation.
  2. Assert the chart container is visible.
  3. Assert the view mode toggle exists with "Cumulative" / "Per-Second" options.
  4. Click each toggle option and verify the chart updates (ECharts canvas re-renders).

Damage accuracy verification (SC-002: layers sum to total) can be verified via the bucketing helper directly as a quick spot-check in a non-Playwright test if needed, but the GUI integration test is the primary gate.

## Complexity Tracking

No constitution violations. No complexity justifications needed.
