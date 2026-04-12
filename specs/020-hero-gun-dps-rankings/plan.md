# Implementation Plan: Hero Gun DPS Rankings

**Branch**: `020-hero-gun-dps-rankings` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/020-hero-gun-dps-rankings/spec.md`

## Summary

Add a "Gun DPS Rankings" view that ranks all heroes by raw gun DPS at two boon levels (0 and 35), displayed as both a sortable table and a horizontal bar chart. The engine already has `ComparisonEngine.rank_heroes()` with a `"dps"` stat — but the underlying `HeroMetrics.snapshot()` uses raw `hero.pellets` instead of `DamageCalculator.effective_pellets()`, which must be fixed. The GUI gets a new tab; the CLI already has `display_rankings()` which covers this with no changes needed.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: NiceGUI ≥ 3.0 (GUI bar chart via `ui.echart`), existing engine modules  
**Storage**: N/A (read-only from API cache)  
**Testing**: pytest + Playwright integration tests  
**Target Platform**: localhost web UI + CLI terminal  
**Project Type**: desktop web app + CLI  
**Performance Goals**: Rankings load in <1s (SC-002) — trivial since it's ~35 heroes × 2 snapshots  
**Constraints**: None  
**Scale/Scope**: ~35 heroes, 2 boon levels

## Constitution Check

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Pure Calculation Engine | **PASS** | All ranking logic stays in `engine/comparison.py` and `engine/heroes.py`. No new engine code in UI. |
| II | API-First Data | **PASS** | Hero stats come from API cache via `load_heroes()`. No hardcoded data. |
| III | Strict Layer Separation | **PASS** | GUI calls `ComparisonEngine.rank_heroes()` → `HeroMetrics.snapshot()` → `DamageCalculator`. One-way dependency maintained. |
| IV | Dual Interface Parity | **PASS** | CLI already has `display_rankings()` with `stat="dps"` at any boon level. GUI adds visual equivalent. No CLI changes needed — exception documented below. |
| V | Simplicity First | **PASS** | Reuses existing `rank_heroes()` and `RankEntry`. No new abstractions. Bar chart uses NiceGUI's built-in `ui.echart`. |
| VI | Mechanic Extensibility | **PASS** | DPS calculation is parameterized through `HeroStats` fields (`base_bullet_damage`, `damage_gain`, `pellets`, `base_fire_rate`). No magic numbers added. |

**Dual Interface Note**: The CLI already supports `Hero Rankings → dps` at any chosen boon level. The GUI adds a visual bar chart + dual-boon comparison that the CLI doesn't have. This is a presentation-layer enhancement, not a capability gap — the CLI user can run rankings at boon 0 and boon 35 separately to get the same data.

## Design

### Bug Fix: `HeroMetrics.snapshot()` Must Use `effective_pellets()`

**Problem**: `HeroMetrics.snapshot()` computes `per_bullet = bullet_dmg * hero.pellets`, which overstates DPS for heroes like Drifter where `max_pellets_per_target=1`. All existing callers of `rank_heroes(stat="dps")` inherit this bug.

**Fix**: Change `hero.pellets` → `DamageCalculator.effective_pellets(hero)` in `snapshot()`.

```python
# deadlock_sim/engine/heroes.py — HeroMetrics.snapshot()
# BEFORE:
per_bullet = bullet_dmg * hero.pellets

# AFTER:
per_bullet = bullet_dmg * DamageCalculator.effective_pellets(hero)
```

This is a correctness fix, not a feature change. It affects `snapshot()`, which feeds `rank_heroes()`, `compare_two()`, and `scaling_curve()`.

### Engine: No New Code Needed

`ComparisonEngine.rank_heroes(heroes, "dps", boon_level=0)` already returns `list[RankEntry]` sorted by DPS. Call it twice (boon 0, boon 35) to get both datasets.

### Data Model: `GunDpsRanking`

A lightweight result dataclass to pair boon-0 and boon-35 rankings for each hero, consumed by the GUI:

```python
# deadlock_sim/models.py
@dataclass
class GunDpsRanking:
    """Gun DPS ranking entry with values at two boon levels."""
    hero_name: str
    dps_boon_0: float
    dps_boon_35: float
    rank_boon_0: int
    rank_boon_35: int
```

A static factory in `ComparisonEngine` merges two `rank_heroes()` calls:

```python
# deadlock_sim/engine/comparison.py
@staticmethod
def gun_dps_rankings(heroes: dict[str, HeroStats]) -> list[GunDpsRanking]:
    """Rank all heroes by gun DPS at boon 0 and boon 35."""
    rank_0 = ComparisonEngine.rank_heroes(heroes, "dps", boon_level=0)
    rank_35 = ComparisonEngine.rank_heroes(heroes, "dps", boon_level=35)
    
    by_name_0 = {e.hero_name: e for e in rank_0}
    by_name_35 = {e.hero_name: e for e in rank_35}
    
    results = []
    for name in by_name_35:
        e0 = by_name_0.get(name)
        e35 = by_name_35[name]
        results.append(GunDpsRanking(
            hero_name=name,
            dps_boon_0=e0.value if e0 else 0.0,
            dps_boon_35=e35.value,
            rank_boon_0=e0.rank if e0 else 0,
            rank_boon_35=e35.rank,
        ))
    # Sort by boon 35 DPS descending (default view)
    results.sort(key=lambda r: r.dps_boon_35, reverse=True)
    return results
```

### GUI: New "Rankings" Tab

**Location**: New top-level tab after "Hero Stats" — not a sub-view of TTK Heatmap (FR-005 says "within TTK Heatmap tab", but that tab doesn't exist yet — spec 017 is still in Draft). A standalone tab is simpler and avoids a dependency on an unimplemented feature. If/when TTK Heatmap is built, the rankings view can be relocated.

**Tab contents**:

1. **Bar chart** (ECharts via `ui.echart`) — horizontal bars, hero names on Y-axis, two bars per hero (boon 0 lighter, boon 35 darker). Tooltip shows exact DPS on hover.
2. **Sortable table** (`ui.table`) — columns: Rank, Hero, DPS (Boon 0), DPS (Boon 35). Sortable by any column.

**Function**: `_build_rankings_tab()` in `gui.py`.

**Rendering flow**:
1. On tab activation, call `ComparisonEngine.gun_dps_rankings(heroes)`.
2. Build ECharts option dict with horizontal bar series.
3. Build NiceGUI table rows from the same data.

### CLI: No Changes

`display_rankings(heroes, "dps", boon_level=N)` already works. Users can call it at boon 0 and 35 manually.

## Project Structure

### Files Modified

```
deadlock_sim/
├── models.py              # Add GunDpsRanking dataclass
├── engine/
│   ├── heroes.py          # Fix snapshot() to use effective_pellets()
│   └── comparison.py      # Add gun_dps_rankings() factory method
└── ui/
    └── gui.py             # Add _build_rankings_tab(), wire new tab
```

### Files Created

None.

### Files Unchanged

```
deadlock_sim/ui/cli.py     # Already has display_rankings()
deadlock_sim/engine/damage.py  # effective_pellets() already exists
tests/test_engine.py       # Extend with new test cases (below)
```

## Test Plan

### Engine Tests (`tests/test_engine.py`)

1. **`test_effective_pellets_in_snapshot`**: Verify `HeroMetrics.snapshot()` uses `effective_pellets()` — Drifter's DPS should reflect 1 pellet per target, not the raw pellet count.
2. **`test_gun_dps_rankings_returns_all_heroes`**: Call `gun_dps_rankings()`, verify every hero in `load_heroes()` has an entry.
3. **`test_gun_dps_rankings_sorted_by_boon_35`**: Verify the result list is sorted descending by `dps_boon_35`.
4. **`test_gun_dps_rankings_boon_35_gte_boon_0`**: For every hero, `dps_boon_35 >= dps_boon_0` (damage_gain is non-negative).

### GUI Tests (`tests/test_gui.py`)

5. **`test_rankings_tab_loads`**: Navigate to Rankings tab, verify the bar chart and table render with hero names visible.
6. **`test_rankings_table_has_all_heroes`**: Count table rows, verify it matches the number of heroes.

## Complexity Tracking

No constitution violations. No complexity exceptions needed.

| Area | Complexity | Justification |
|------|-----------|---------------|
| New dataclass (`GunDpsRanking`) | Low | Pairs two existing `RankEntry` results — avoids passing two lists through UI |
| New factory method (`gun_dps_rankings`) | Low | Thin wrapper over two `rank_heroes()` calls |
| New GUI tab | Medium | ECharts config for horizontal grouped bar chart requires ~30 lines of option dict |
| Bug fix (`effective_pellets`) | Low | Single-line change in `snapshot()` |
