# Implementation Plan: Defensive Item Scorer

**Branch**: `022-defensive-item-scorer` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/022-defensive-item-scorer/spec.md`

## Summary

Add a defensive scoring mode to the existing `ItemScorer` that ranks candidate items by **survival time delta** against a specific attacker's damage profile. The attacker is defined as a hero + saved build. The engine scores each defensive item by simulating the attacker's DPS against the defender's baseline build, then re-simulating with each candidate item added, measuring the time-to-kill difference. A fast (analytical) mode is also provided using EHP deltas weighted by the attacker's damage type split. The GUI Build tab gains a mode toggle (Offensive / Defensive) and an attacker selector; the CLI gains a corresponding menu option.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: NiceGUI ≥ 3.0, stdlib dataclasses
**Storage**: Browser localStorage (saved builds), `data/api_cache/` (hero/item data)
**Testing**: pytest + Playwright integration tests
**Target Platform**: Windows/Linux, localhost web server
**Project Type**: Desktop simulation tool (CLI + GUI)
**Performance Goals**: Fast mode < 200ms for 50 candidates; sim mode < 5s for 50 candidates
**Constraints**: Engine must remain pure/stateless; no new runtime dependencies
**Scale/Scope**: ~50 vitality items to score, 1 attacker config at a time

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Pure Calculation Engine ✅
All defensive scoring logic lives in `deadlock_sim/engine/scoring.py` as `@staticmethod` methods on `ItemScorer`. No I/O, no UI imports, no mutable global state. The simulation is delegated to the existing `CombatSimulator`.

### II. API-First Data ✅
No new data sources. Hero stats, item stats, and damage profiles all originate from the API cache. Saved builds reference items by name, resolved against `load_items()`.

### III. Strict Layer Separation ✅
- `models.py`: New `DefensiveScore` dataclass added.
- `engine/scoring.py`: New `_score_defensive_fast` and `_score_defensive_sim` methods.
- `ui/gui.py`: Mode toggle and attacker selector UI.
- `ui/cli.py`: Defensive scoring menu option.
- Dependencies flow one-way: models ← engine ← ui.

### IV. Dual Interface Parity ✅
Both CLI and GUI expose defensive scoring. The CLI adds a "Defensive Item Scoring" menu option that prompts for attacker hero + build. The GUI adds a toggle and attacker dropdown in the Build tab.

### V. Simplicity First ✅
Reuses existing `CombatSimulator` for sim-mode scoring — no new simulation engine. The fast mode reuses `_compute_ehp` with attacker damage-type weighting. No new frameworks or plugin systems.

### VI. Mechanic Extensibility ✅
Attacker damage profile is derived from existing `SimResult` fields (`bullet_damage`, `spirit_damage`, `melee_damage`), so any future damage types or mechanics automatically factor in. Defensive stats (resist, HP, shields, lifesteal) are already parameterized on `BuildStats` and `HeroStats`.

## Project Structure

### Documentation (this feature)

```text
specs/022-defensive-item-scorer/
├── spec.md              # Feature specification
├── plan.md              # This file
└── tasks.md             # Phase 2 output (created by task generator)
```

### Source Code (modified files)

```text
deadlock_sim/
├── models.py                  # ADD: DefensiveScore dataclass
├── engine/
│   └── scoring.py             # MODIFY: Add defensive scoring modes to ItemScorer
│                              #   - Extend ScoringConfig with attacker fields
│                              #   - Add _score_defensive_fast()
│                              #   - Add _score_defensive_sim()
│                              #   - Add _compute_survival_time()
└── ui/
    ├── gui.py                 # MODIFY: Build tab mode toggle + attacker selector
    │                          #   - Add "Offensive/Defensive" radio toggle
    │                          #   - Add attacker hero + build selector (from saved builds)
    │                          #   - Wire defensive sort options into shop refresh
    ├── state.py               # MODIFY: Add attacker config to _PageState
    └── cli.py                 # MODIFY: Add defensive scoring menu option
```

## Design

### 1. Data Models (`models.py`)

```python
@dataclass
class DefensiveScore:
    """Scoring result for a single candidate defensive item."""
    item_name: str = ""
    # Survival time deltas (seconds gained)
    survival_time_delta: float = 0.0       # sim mode: TTK with item - TTK without
    fast_survival_delta: float = 0.0       # fast mode: EHP-based estimate
    # EHP deltas (against attacker's damage profile)
    ehp_delta: float = 0.0                 # raw EHP change
    bullet_ehp_delta: float = 0.0          # EHP vs bullet damage
    spirit_ehp_delta: float = 0.0          # EHP vs spirit damage
    # Efficiency
    survival_per_soul: float = 0.0         # survival_time_delta / cost
    ehp_per_soul: float = 0.0             # ehp_delta / cost
    # Attacker context
    attacker_name: str = ""
    attacker_dps: float = 0.0
    attacker_bullet_pct: float = 0.0       # fraction of damage that is bullet
    attacker_spirit_pct: float = 0.0       # fraction of damage that is spirit
```

### 2. Scoring Config Extension (`engine/scoring.py`)

Extend the existing `ScoringConfig`:

```python
@dataclass
class ScoringConfig:
    # ... existing fields ...
    sim_settings: SimSettings | None = None
    ability_schedule: list[AbilityUse] = field(default_factory=list)
    custom_item_dps: dict[str, float] = field(default_factory=dict)
    custom_item_ehp: dict[str, float] = field(default_factory=dict)
    # NEW: Defensive scoring
    scoring_mode: str = "offensive"        # "offensive" or "defensive"
    attacker_hero: HeroStats | None = None
    attacker_build: Build | None = None
    attacker_boons: int = 0
    attacker_ability_upgrades: dict[int, list[int]] = field(default_factory=dict)
    attacker_ability_schedule: list[AbilityUse] = field(default_factory=list)
```

### 3. Defensive Scoring Engine (`engine/scoring.py`)

#### Fast Mode: `_score_defensive_fast()`

1. Run a single baseline DPS calculation for the attacker (using `DamageCalculator.calculate_bullet` + `hero_total_spirit_dps`) to determine the **damage type split** (% bullet vs % spirit).
2. For the **defender** (the player's hero), compute baseline EHP weighted by the attacker's damage profile:
   - `weighted_ehp = bullet_pct * ehp_vs_bullet + spirit_pct * ehp_vs_spirit`
   - where `ehp_vs_bullet = raw_hp / (1 - bullet_resist)` and `ehp_vs_spirit = raw_hp / (1 - spirit_resist)`
3. For each candidate item, recompute `weighted_ehp` with the item added.
4. `survival_time_delta ≈ (weighted_ehp_with_item - weighted_ehp_baseline) / attacker_total_dps`
5. Return `DefensiveScore` for each candidate.

```python
@staticmethod
def _score_defensive_fast(
    defender: HeroStats,
    defender_build: Build,
    candidates: list[Item],
    defender_boons: int,
    cfg: ScoringConfig,
) -> dict[str, DefensiveScore]:
    ...
```

#### Sim Mode: `_score_defensive_sim()`

1. Run a baseline simulation: attacker (with their build) vs defender (with baseline build). Record `kill_time` or extrapolate from `overall_dps` if the target survives.
2. For each candidate item, add it to the defender's build and re-run the simulation.
3. `survival_time_delta = new_kill_time - baseline_kill_time` (positive = survived longer).
4. Return `DefensiveScore` for each candidate.

```python
@staticmethod
def _score_defensive_sim(
    defender: HeroStats,
    defender_build: Build,
    candidates: list[Item],
    defender_boons: int,
    cfg: ScoringConfig,
) -> dict[str, DefensiveScore]:
    ...
```

Key implementation detail: When the defender doesn't die in the simulation window, estimate survival time as `defender_hp / attacker_dps` for comparison purposes.

#### Survival Time Helper

```python
@staticmethod
def _estimate_survival_time(
    result: SimResult,
    defender_total_hp: float,
) -> float:
    """Estimate survival time from a sim result.
    
    If kill_time is set, use it directly.
    Otherwise, extrapolate: defender_hp / attacker_dps.
    """
    if result.kill_time is not None:
        return result.kill_time
    if result.overall_dps > 0:
        return defender_total_hp / result.overall_dps
    return float('inf')
```

#### Updated `score_candidates()` Entry Point

The existing `score_candidates` method gains awareness of `cfg.scoring_mode`:

```python
@staticmethod
def score_candidates(...) -> dict[str, ItemScore] | dict[str, DefensiveScore]:
    cfg = config or ScoringConfig()
    if cfg.scoring_mode == "defensive":
        if mode == "fast":
            return ItemScorer._score_defensive_fast(hero, baseline_build, candidates, boons, cfg)
        return ItemScorer._score_defensive_sim(hero, baseline_build, candidates, boons, cfg)
    # ... existing offensive logic ...
```

Alternatively (and preferably for type clarity), add a separate entry point:

```python
@staticmethod
def score_defensive(
    defender: HeroStats,
    defender_build: Build,
    candidates: list[Item],
    defender_boons: int,
    mode: str = "fast",
    config: ScoringConfig | None = None,
) -> dict[str, DefensiveScore]:
    """Score candidate items for defensive value against an attacker."""
    cfg = config or ScoringConfig()
    if mode == "fast":
        return ItemScorer._score_defensive_fast(defender, defender_build, candidates, defender_boons, cfg)
    return ItemScorer._score_defensive_sim(defender, defender_build, candidates, defender_boons, cfg)
```

**Decision**: Use a separate `score_defensive()` method to keep the return type unambiguous and avoid complicating the existing `score_candidates` signature.

### 4. Edge Case Handling

| Edge Case | Resolution |
|-----------|------------|
| Mixed offense/defense items (e.g., Leech) | Score them normally — lifesteal contributes to effective survival time in sim mode. In fast mode, include lifesteal as bonus EHP: `lifesteal_ehp = lifesteal_pct * attacker_dps * expected_fight_duration`. |
| Active defensive items (Metal Skin) | Sim mode handles these via existing `ActiveUse` scheduling. Fast mode uses `custom_item_ehp` overrides from sim settings. |
| Attacker shred items | Both modes incorporate attacker shred. In sim mode, the `CombatSimulator` already applies shred debuffs. In fast mode, compute the attacker's shred from their `BuildStats` and reduce the defender's effective resist. |
| No attacker selected | Return empty dict. GUI shows prompt "Select an attacker to score defensive items." |
| Attacker with zero DPS | Return all-zero scores. Guard division by zero. |

### 5. GUI Changes (`ui/gui.py`)

#### Build Tab Additions

1. **Mode Toggle**: Radio group with "Offensive" (default) and "Defensive" options, placed next to the existing Sort By dropdown.

2. **Attacker Selector** (visible only in defensive mode):
   - Hero dropdown (same style as existing hero selects).
   - Saved build dropdown (populated from `localStorage` saved builds, filtered by selected attacker hero).
   - Attacker boons input (auto-derived from saved build's total cost, editable).

3. **Sort Options**: When defensive mode is active, the sort dropdown changes to defensive-specific options:
   ```python
   _DEFENSIVE_SORT_KEYS: dict[str, str] = {
       "🛡 Survival Time Δ":    "survival_time_delta",
       "🛡 EHP Δ":              "ehp_delta",
       "🛡 Survival/Soul":      "survival_per_soul",
       "🛡 EHP/Soul":           "ehp_per_soul",
   }
   _DEFENSIVE_SIM_SORT_KEYS: dict[str, tuple[str, str]] = {
       "⚔🛡 Sim Survival Δ":    ("survival_time_delta", "sim"),
   }
   ```

4. **Score Badge Display**: When a defensive score is active, the shop card badge shows the survival time delta (e.g., "+1.8s") instead of DPS delta.

5. **Attacker DPS Summary**: Small info row showing "Attacker: Haze (Gun Build) — 285 DPS (78% bullet, 22% spirit)" so the user understands the scoring context.

#### State Changes (`ui/state.py` or `_PageState`)

Add to `_PageState`:

```python
# Defensive scoring
self.defensive_mode: bool = False
self.attacker_hero_name: str = ""
self.attacker_build_data: dict | None = None  # saved build dict from localStorage
```

### 6. CLI Changes (`ui/cli.py`)

Add a new menu option "Defensive Item Scoring" that:

1. Prompts for the attacker hero (from loaded heroes).
2. Prompts to build an attacker item set (reusing `_select_items()`).
3. Prompts for the defender hero + build.
4. Runs `ItemScorer.score_defensive()` and displays results as a table:

```
  Defensive Item Rankings vs Haze (Gun Build, 285 DPS)
  ─────────────────────────────────────────────────────
  #  Item                    Surv Δ   EHP Δ    /Soul
  1  Metal Skin              +3.2s    +820     +0.13s
  2  Fortitude               +2.1s    +540     +0.08s
  3  Bullet Armor            +1.8s    +450     +0.09s
  ...
```

### 7. Attacker Profile Construction

When loading an attacker from a saved build:

```python
def _build_attacker_config_from_saved(
    saved_build: dict,
    heroes: dict[str, HeroStats],
    items: dict[str, Item],
) -> ScoringConfig:
    """Construct a ScoringConfig with attacker fields from a saved build dict."""
    hero_name = saved_build["hero_name"]
    hero = heroes[hero_name]
    item_names = saved_build.get("items", [])
    build_items = [items[n] for n in item_names if n in items]
    build = Build(items=build_items)
    boons = souls_to_boons(build.total_cost + saved_build.get("extra_souls", 0))
    
    # Build ability schedule from saved data
    ability_upgrades = saved_build.get("ability_upgrades", {}).get(hero_name, {})
    upgrade_map = {int(k): list(range(1, v + 1)) for k, v in ability_upgrades.items()}
    
    return ScoringConfig(
        scoring_mode="defensive",
        attacker_hero=hero,
        attacker_build=build,
        attacker_boons=boons,
        attacker_ability_upgrades=upgrade_map,
    )
```

This helper lives in `ui/gui.py` (or `ui/state.py`) since it bridges localStorage data with engine config — it's a UI-layer concern.

## Complexity Tracking

No constitution violations. All changes follow existing patterns:

| Decision | Rationale |
|----------|-----------|
| Separate `score_defensive()` method vs overloading `score_candidates()` | Keeps return types unambiguous (`DefensiveScore` vs `ItemScore`). Two call sites (GUI fast and sim sort). Justified by Principle V — separate method is simpler than union return type. |
| Fast mode uses weighted EHP instead of full sim | Performance: scoring 50 items in < 200ms. Sim mode available for precision. Follows existing fast/sim split pattern in `ItemScorer`. |
| Attacker profile stored on `_PageState` (not `BuildState`) | `BuildState` represents the *player's* build. The attacker is a UI-level concern for scoring context, not a build property. Keeps `state.py` focused on the player's configuration. |
