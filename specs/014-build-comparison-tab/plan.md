# Implementation Plan: Build Comparison Tab

**Branch**: `014-build-comparison-tab` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/014-build-comparison-tab/spec.md`

## Summary

Add a dedicated Build Comparison GUI tab that lets players load two saved builds into side-by-side comparison slots, view stat deltas (DPS, EHP, TTK, spirit DPS, bullet DPS) with color-coded directional indicators, highlight item differences between builds, and perform in-place item swaps with immediate delta recalculation. The engine layer gets a new pure `BuildComparison` module; the GUI gets a new tab wired to browser localStorage saved builds.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: NiceGUI (GUI), dataclasses (models)
**Storage**: Browser localStorage (`deadlocksim_saved_builds` key — existing)
**Testing**: pytest + Playwright (integration tests against live NiceGUI server)
**Target Platform**: Web browser (localhost NiceGUI server)
**Project Type**: Desktop web app (single-page NiceGUI)
**Performance Goals**: < 1s to load two builds and display comparison; < 500ms for item swap delta
**Constraints**: No server-side persistence; saved builds are client-side JSON
**Scale/Scope**: Single new tab (6th tab); ~1 new engine module, ~1 new GUI builder function

## Constitution Check

*GATE: Must pass before implementation. Re-checked after design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | **Pure Calculation Engine** | ✅ Compliant | All comparison/delta logic lives in `engine/comparison.py` as `@staticmethod` methods. No I/O or UI imports. |
| II | **API-First Data** | ✅ N/A | No new game data needed. Builds reference existing heroes and items loaded from API cache. |
| III | **Strict Layer Separation** | ✅ Compliant | New engine functions in `engine/comparison.py`. GUI tab calls engine, never the reverse. |
| IV | **Dual Interface Parity** | ⚠️ Exception | Build comparison is inherently visual (two-column layout, color-coded deltas). The CLI has no saved builds infrastructure. A CLI `compare-builds` command is deferred to a follow-up spec. This exception is documented and accepted. |
| V | **Simplicity First** | ✅ Compliant | One new dataclass (`BuildComparisonResult`), one new engine method, one new GUI builder function. No frameworks, no plugin systems. |
| VI | **Mechanic Extensibility** | ✅ Compliant | Stat comparison uses the existing `BuildResult` fields. Adding a new stat to `BuildResult` automatically makes it available for comparison without changing the comparison logic. |

## Project Structure

### Documentation (this feature)

```text
specs/014-build-comparison-tab/
├── spec.md              # Feature requirements
├── plan.md              # This file
└── tasks.md             # Execution checklist (generated separately)
```

### Source Code (files to modify/create)

```text
deadlock_sim/
├── models.py                    # ADD: BuildComparisonResult, StatDelta dataclasses
├── engine/
│   └── comparison.py            # ADD: compare_builds() static method
└── ui/
    └── gui.py                   # ADD: _build_comparison_tab() builder function, new tab wiring
tests/
└── test_engine.py               # ADD: test_compare_builds spot-check
```

**Structure Decision**: All changes fit within the existing project structure. No new files needed — only additions to existing modules.

---

## Design

### 1. New Data Models (`models.py`)

```python
@dataclass
class StatDelta:
    """A single stat comparison between two builds."""
    stat_name: str           # human-readable label, e.g. "Bullet DPS"
    value_a: float           # build A value
    value_b: float           # build B value
    delta: float             # value_a - value_b
    higher_is_better: bool = True  # True for DPS/EHP, False for TTK

@dataclass
class BuildComparisonResult:
    """Full comparison output between two builds."""
    result_a: BuildResult
    result_b: BuildResult
    deltas: list[StatDelta]
    items_only_a: list[str]   # item names in A but not B
    items_only_b: list[str]   # item names in B but not A
    items_shared: list[str]   # item names in both
```

**Rationale**: Follows convention of dedicated result dataclasses (like `BulletResult`, `TTKResult`). `StatDelta.higher_is_better` lets the UI determine green/red coloring without hardcoding stat semantics in the GUI.

### 2. Engine: `ComparisonEngine.compare_builds()` (`engine/comparison.py`)

New `@staticmethod` on the existing `ComparisonEngine` class:

```python
@staticmethod
def compare_builds(
    hero: HeroStats,
    build_a: Build,
    build_b: Build,
    boons: int = 0,
    accuracy: float = 1.0,
    headshot_rate: float = 0.0,
    defender: HeroStats | None = None,
    defender_build: Build | None = None,
    enabled_conditionals: set[str] | None = None,
    ability_upgrades_a: dict[int, list[int]] | None = None,
    ability_upgrades_b: dict[int, list[int]] | None = None,
    cooldown_reduction_a: float = 0.0,
    cooldown_reduction_b: float = 0.0,
    spirit_amp_a: float = 0.0,
    spirit_amp_b: float = 0.0,
    spirit_resist_shred_a: float = 0.0,
    spirit_resist_shred_b: float = 0.0,
) -> BuildComparisonResult:
```

**Logic**:
1. Call `BuildEngine.evaluate_build()` for both builds → `result_a`, `result_b`.
2. Compute spirit DPS for each build via `DamageCalculator.hero_total_spirit_dps()`.
3. Populate `result_a.spirit_dps` and `result_b.spirit_dps` and `combined_dps`.
4. Build `StatDelta` list for: Bullet DPS (sustained), Spirit DPS, Combined DPS, EHP, TTK (if defender provided), Magazine Size, Fire Rate.
5. Compute item set differences: `items_only_a`, `items_only_b`, `items_shared`.
6. Return `BuildComparisonResult`.

**Dependencies**: Imports only from `models` and sibling engine modules (`builds`, `damage`). No UI imports.

### 3. GUI: `_build_comparison_tab()` (`ui/gui.py`)

New tab builder function following the existing pattern (`_build_eval_tab`, `_build_saved_builds_tab`, etc.).

**Layout**:
```
┌─────────────────────────────────────────────────────┐
│  Build A [dropdown ▾]    Build B [dropdown ▾]       │
│                                                     │
│  ┌─────────────┐  ┌──────────┐  ┌─────────────┐   │
│  │  Build A     │  │  Deltas  │  │  Build B     │   │
│  │  Hero: ...   │  │  ▲ +42   │  │  Hero: ...   │   │
│  │  Items: ...  │  │  ▼ -15   │  │  Items: ...  │   │
│  │  DPS: 245    │  │  ▲ +1.2s │  │  DPS: 203    │   │
│  │  EHP: 1800   │  │  ...     │  │  EHP: 2100   │   │
│  └─────────────┘  └──────────┘  └─────────────┘   │
│                                                     │
│  Item Differences:                                  │
│  [Only in A: Toxic Bullets]  [Only in B: Mystic S.] │
│  [Shared: 5 items]                                  │
│                                                     │
│  ── Quick Swap (Build A) ──                         │
│  Remove: [item dropdown] → Add: [item dropdown]     │
│  [Apply Swap]                                       │
└─────────────────────────────────────────────────────┘
```

**Wiring**:
- Two `ui.select` dropdowns populated from `_load_saved_builds()` (reuse existing localStorage reader from saved builds tab).
- On selection change → call `ComparisonEngine.compare_builds()` → refresh display.
- Delta column uses green (`#4caf50`) for better, red (`#f44336`) for worse, based on `StatDelta.higher_is_better` and `delta` sign.
- Item differences displayed as color-coded chips (amber for unique-to-A, blue for unique-to-B, gray for shared).
- Quick Swap section: two dropdowns (remove item, add item from shop) → mutate the loaded build's item list in memory → re-run comparison. Does NOT save to localStorage unless explicitly saved.

**State**: The comparison tab holds its own local state (two loaded build dicts and their computed `BuildResult`s). It does NOT share `_PageState.build_items` with the Build Lab tab — comparison slots are independent.

**Tab registration** (in `run_gui()`):
```python
with ui.tabs().classes("w-full") as tabs:
    tab_build = ui.tab("Build")
    tab_saved = ui.tab("Saved Builds")
    tab_compare = ui.tab("Compare")     # NEW
    tab_sim = ui.tab("Simulation")
    tab_settings = ui.tab("Settings")
    tab_hero = ui.tab("Hero Stats")
```

### 4. Saved Build Loading

The comparison tab reuses the existing localStorage key (`deadlocksim_saved_builds`) and the same JSON schema written by `save_current_build()`. No changes to the save format.

**Build reconstruction from saved data**:
```python
def _reconstruct_build(saved: dict, items: dict[str, Item]) -> tuple[str, Build, dict[int, list[int]], int]:
    """Parse a saved build dict into (hero_name, Build, ability_upgrades, extra_souls)."""
    hero_name = saved.get("hero_name", "")
    item_names = saved.get("items", [])
    build_items = [items[n] for n in item_names if n in items]
    extra_souls = saved.get("extra_souls", 0)
    ability_upgrades = {}
    for idx_str, tier in saved.get("ability_upgrades", {}).get(hero_name, {}).items():
        ability_upgrades[int(idx_str)] = list(range(1, tier + 1))
    return hero_name, Build(items=build_items), ability_upgrades, extra_souls
```

This is a helper used only within the comparison tab. It handles the edge case of missing items (post-patch) by silently skipping them.

### 5. Cross-Hero Comparison

The spec raises the edge case of comparing builds for different heroes. The plan handles this:
- Both dropdowns list ALL saved builds (with hero name shown in the label).
- If heroes differ, comparison still works — `evaluate_build` is called per-hero with respective hero stats. TTK comparison is only shown when both builds target the same defender.
- A subtle info banner appears: "Comparing builds for different heroes — stat deltas reflect hero base stat differences too."

### 6. CLI Parity Exception

Per Constitution Principle IV, CLI parity is required. However:
- The CLI has no saved builds infrastructure (no localStorage equivalent).
- Build comparison is inherently a visual, interactive feature (side-by-side columns, colored deltas, item swaps).
- Adding a CLI `compare-builds` command would require a separate persistence mechanism (JSON file) and would be a separate feature.

**Decision**: Document this as an explicit exception. The engine method `ComparisonEngine.compare_builds()` is fully available for CLI use if/when CLI saved builds are added. The MCP server could also expose this.

### 7. Test Strategy

**Engine test** (`test_engine.py`):
- `test_compare_builds_same_hero`: Two builds for the same hero, verify deltas are mathematically correct (value_a - value_b).
- `test_compare_builds_item_diff`: Verify `items_only_a`, `items_only_b`, `items_shared` are correct.

**GUI test** (`test_gui.py`):
- `test_comparison_tab_loads`: Navigate to Compare tab, verify dropdowns appear.
- `test_comparison_tab_with_builds`: Pre-populate localStorage with two builds, load them, verify stat rows render with correct values.

---

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| CLI parity exception (Principle IV) | Build comparison is visual and depends on saved builds (localStorage). CLI lacks persistence infrastructure. | A file-based CLI save system would be a separate feature with its own spec. The engine method is CLI-ready when persistence exists. |
