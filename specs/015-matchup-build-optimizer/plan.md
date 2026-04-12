# Implementation Plan: Matchup-Specific Build Optimizer

**Branch**: `015-matchup-build-optimizer` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/015-matchup-build-optimizer/spec.md`

## Summary

Extend the item scoring and build optimization engine so that item scores and build recommendations account for a defender's hero stats and optional build. The `ScoringConfig` gains defender fields, `ItemScorer` routes defender stats into DPS calculations and simulation configs, `BuildOptimizer` passes defender context through to the scorer, and the GUI Build Lab tab gains a defender hero selector plus an optional "load saved build as defender" control. The CLI `optimize-build` menu gets equivalent defender selection.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: NiceGUI (GUI), dataclasses (models)
**Storage**: Browser localStorage (`deadlocksim_saved_builds` key — existing, for loading defender builds)
**Testing**: pytest + Playwright (integration tests against live NiceGUI server)
**Target Platform**: Web browser (localhost NiceGUI server) + terminal CLI
**Project Type**: Desktop web app (single-page NiceGUI) + CLI
**Performance Goals**: < 2s to rescore all candidates when defender changes; < 500ms for fast-mode scoring
**Constraints**: No new runtime dependencies; defender data comes from existing hero/item data
**Scale/Scope**: Modifications to 3 engine files, 2 UI files, 1 state file; no new modules

## Constitution Check

*GATE: Must pass before implementation. Re-checked after design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | **Pure Calculation Engine** | ✅ Compliant | All matchup-aware scoring stays in `engine/scoring.py` and `engine/builds.py`. New logic is stateless — defender stats passed via config objects. No I/O or UI imports in engine. |
| II | **API-First Data** | ✅ N/A | No new game data. Defender heroes and items come from the existing API-cached data loaded by `data.py`. |
| III | **Strict Layer Separation** | ✅ Compliant | `ScoringConfig` gains defender fields in engine layer. GUI reads defender selection and constructs config, then passes to engine. No upward dependencies. |
| IV | **Dual Interface Parity** | ✅ Compliant | CLI `optimize-build` menu will gain a "Select defender hero" prompt. Both CLI and GUI pass the same `ScoringConfig` to the same engine methods. |
| V | **Simplicity First** | ✅ Compliant | No new modules, no new abstractions. Adds 3 optional fields to `ScoringConfig`, threads them through existing methods. Defender build loading reuses existing saved-builds infrastructure. |
| VI | **Mechanic Extensibility** | ✅ Compliant | Defender stats flow through `BuildStats` and `CombatConfig`, which are already parameterized dataclasses. Adding a new resist type or stat to the defender requires only a field addition to existing models. |

## Project Structure

### Documentation (this feature)

```text
specs/015-matchup-build-optimizer/
├── spec.md              # Feature requirements
├── plan.md              # This file
└── tasks.md             # Execution checklist (generated separately)
```

### Source Code (files to modify)

```text
deadlock_sim/
├── engine/
│   ├── scoring.py           # MODIFY: ScoringConfig + ItemScorer (defender-aware scoring)
│   └── builds.py            # MODIFY: BuildOptimizer (pass defender context)
├── ui/
│   ├── state.py             # MODIFY: BuildState (defender hero + defender build fields)
│   ├── gui.py               # MODIFY: Build Lab tab (defender selector UI)
│   └── cli.py               # MODIFY: optimize-build menu (defender hero prompt)
tests/
└── test_engine.py           # ADD: matchup scoring tests
```

**Structure Decision**: All changes modify existing files. No new modules needed — `ScoringConfig` already exists as the extensibility point for scoring parameters.

---

## Design

### 1. Engine Changes

#### 1a. `ScoringConfig` Extensions (`engine/scoring.py`)

Add three optional fields to the existing `ScoringConfig`:

```python
@dataclass
class ScoringConfig:
    """Configuration for item scoring, decoupled from UI globals."""

    sim_settings: SimSettings | None = None
    ability_schedule: list[AbilityUse] = field(default_factory=list)
    custom_item_dps: dict[str, float] = field(default_factory=dict)
    custom_item_ehp: dict[str, float] = field(default_factory=dict)

    # NEW: Matchup-specific defender configuration
    defender_hero: HeroStats | None = None        # Target hero (None = generic dummy)
    defender_build: Build | None = None            # Defender's item build (None = base stats only)
    defender_boons: int = 0                        # Defender's boon level
```

These fields are all optional with `None`/`0` defaults, so existing callers are unaffected.

#### 1b. Fast-Mode Matchup Scoring (`ItemScorer._score_fast`)

When `cfg.defender_hero` is set, the fast scorer computes DPS **against the defender's actual resist/HP** instead of using zero resist and infinite HP:

1. Aggregate `cfg.defender_build` via `BuildEngine.aggregate_stats()` to get defender `BuildStats`.
2. Compute defender effective HP via `BuildEngine.defender_effective_hp()`.
3. Compute defender bullet resist (base boon resist + item resist) and spirit resist.
4. Pass `enemy_bullet_resist`, `enemy_spirit_resist`, `enemy_hp` into `build_to_attacker_config()`.
5. The EHP calculation remains attacker-relative (how tanky the attacker is) — it does not change with defender.

Key helper (new static method on `ItemScorer`):

```python
@staticmethod
def _resolve_defender(cfg: ScoringConfig) -> tuple[float, float, float]:
    """Extract (bullet_resist, spirit_resist, effective_hp) from defender config.
    
    Returns (0.0, 0.0, 0.0) when no defender is set (generic scoring).
    """
```

This helper is used by both `_score_fast` and `_score_sim` to avoid duplication.

#### 1c. Simulation-Mode Matchup Scoring (`ItemScorer._score_sim`)

When `cfg.defender_hero` is set, replace the hardcoded `HeroStats(name="Dummy Target", base_hp=2500)` with the actual defender hero. Pass `cfg.defender_build` into `SimConfig.defender_build`:

```python
defender = cfg.defender_hero or HeroStats(name="Dummy Target", base_hp=2500, base_regen=0)
defender_build = cfg.defender_build or Build()

# In SimConfig construction:
SimConfig(
    attacker=hero,
    attacker_build=Build(items=test_items),
    defender=defender,
    defender_build=defender_build,
    settings=settings,
    ability_schedule=ability_schedule,
)
```

The simulation engine already handles `defender_build` in `SimConfig` — it aggregates defender stats internally. No changes to `simulation.py` needed.

#### 1d. `BuildOptimizer` Matchup Awareness (`engine/builds.py`)

`BuildOptimizer.best_dps_items()` currently optimizes raw DPS with no defender context. Add an optional `scoring_config: ScoringConfig | None` parameter so it can route through the matchup-aware scorer:

```python
@staticmethod
def best_dps_items(
    items: dict[str, Item],
    hero: HeroStats,
    budget: int,
    boons: int = 0,
    max_items: int = 12,
    exclude_conditional: bool = True,
    scoring_config: ScoringConfig | None = None,  # NEW
) -> Build:
```

When `scoring_config` is provided and has a `defender_hero`, the greedy loop evaluates DPS against the defender's resist profile instead of raw (unresisted) DPS. It does this by calling `build_to_attacker_config` with defender resist/HP values extracted from the scoring config.

`best_ttk_items()` already accepts a `defender: HeroStats` parameter. Extend it to also accept `defender_build: Build | None = None`:

```python
@staticmethod
def best_ttk_items(
    items: dict[str, Item],
    hero: HeroStats,
    defender: HeroStats,
    budget: int,
    boons: int = 0,
    accuracy: float = 0.5,
    headshot_rate: float = 0.15,
    max_items: int = 12,
    exclude_conditional: bool = True,
    defender_build: Build | None = None,  # NEW
) -> Build:
```

When `defender_build` is provided, pass it to `BuildEngine.evaluate_build()` (which already supports `defender_build`).

### 2. State Layer Changes (`ui/state.py`)

Add defender state to `BuildState`:

```python
class BuildState:
    def __init__(self) -> None:
        # ... existing fields ...
        self._defender_hero_name: str = ""
        self._defender_build_items: list[Item] = []
        self._defender_boons: int = 0

    @property
    def defender_hero_name(self) -> str:
        return self._defender_hero_name

    def set_defender_hero(self, name: str) -> "BuildState":
        self._defender_hero_name = name
        return self

    def set_defender_build(self, items: list[Item], boons: int = 0) -> "BuildState":
        self._defender_build_items = list(items)
        self._defender_boons = boons
        return self

    def clear_defender(self) -> "BuildState":
        self._defender_hero_name = ""
        self._defender_build_items.clear()
        self._defender_boons = 0
        return self

    def to_scoring_config(self, heroes: dict[str, HeroStats], **kwargs) -> ScoringConfig:
        """Build a ScoringConfig with defender context from current state."""
        cfg = ScoringConfig(**kwargs)
        if self._defender_hero_name and self._defender_hero_name in heroes:
            cfg.defender_hero = heroes[self._defender_hero_name]
            cfg.defender_build = Build(items=list(self._defender_build_items))
            cfg.defender_boons = self._defender_boons
        return cfg
```

### 3. GUI Changes (`ui/gui.py`)

#### 3a. Build Lab Tab — Defender Selector

In the Build Lab tab (likely near the hero selector or in a "Matchup" sub-section), add:

1. **Defender hero dropdown** (`ui.select`) — populated from `_heroes.keys()`, with a "None (generic)" option at the top. Changing this updates `state.build_state.set_defender_hero()`.

2. **"Load Defender Build" button** — opens a dialog listing saved builds filtered to the selected defender hero. Uses the existing `_load_saved_builds()` localStorage reader. Selecting a build calls `state.build_state.set_defender_build(items, boons)`.

3. **Defender info label** — shows "vs. {hero_name}" or "vs. {hero_name} ({build_name})" when a defender is selected.

4. **Wire scoring**: When `_build_run_scorer()` is invoked, construct `ScoringConfig` via `state.build_state.to_scoring_config()` and pass it to `ItemScorer.score_candidates()`.

#### 3b. Score Display Changes

No changes to score column layout. The scores themselves reflect matchup context because the engine now computes against the defender's profile. The only visual addition is the "vs. X" indicator so the player knows scores are matchup-specific.

### 4. CLI Changes (`ui/cli.py`)

In the `_optimize_build()` menu flow:

1. After hero selection and before running the optimizer, add a prompt: "Select defender hero (0 for generic):".
2. If a defender is selected, optionally prompt for defender boon level.
3. Pass defender hero and boons to `BuildOptimizer.best_dps_items()` / `best_ttk_items()` via `ScoringConfig`.

No saved-build loading in CLI (CLI has no localStorage). Defender is base stats + boons only in CLI mode. This is a reasonable parity simplification since CLI users can still specify a defender hero with boons.

### 5. Defender Resist/HP Resolution Logic

Central helper method to avoid duplicating resist math:

```python
@staticmethod
def _resolve_defender(cfg: ScoringConfig) -> tuple[float, float, float]:
    """Return (bullet_resist, spirit_resist, effective_hp) for the defender.
    
    When cfg.defender_hero is None, returns (0.0, 0.0, 0.0) — generic scoring.
    When set, computes from defender hero base stats + boons + optional build.
    """
    if cfg.defender_hero is None:
        return (0.0, 0.0, 0.0)
    
    defender_bs = BuildStats()
    if cfg.defender_build:
        defender_bs = BuildEngine.aggregate_stats(cfg.defender_build)
    
    # Bullet resist: boon resist + item resist (multiplicative)
    boon_resist = cfg.defender_hero.bullet_resist_gain * cfg.defender_boons
    total_bullet_resist = 1.0 - (1.0 - boon_resist) * (1.0 - defender_bs.bullet_resist_pct)
    
    # Spirit resist: boon resist + item resist (multiplicative)
    boon_spirit_resist = cfg.defender_hero.spirit_resist_gain * cfg.defender_boons
    total_spirit_resist = 1.0 - (1.0 - boon_spirit_resist) * (1.0 - defender_bs.spirit_resist_pct)
    
    # Effective HP
    ehp = BuildEngine.defender_effective_hp(cfg.defender_hero, defender_bs, cfg.defender_boons)
    
    return (total_bullet_resist, total_spirit_resist, ehp)
```

This is placed as a `@staticmethod` on `ItemScorer` (single class, two call sites: `_score_fast` and `_score_sim`).

---

## Edge Cases

| Edge Case | Resolution |
|-----------|------------|
| Defender build has removed/patched items | `set_defender_build` filters out items not in current `load_items()`. Missing items silently dropped. |
| Defender and attacker are the same hero | Allowed — scores reflect self-matchup (mirror match). No special handling. |
| Defender ability upgrades | Out of scope for this feature. Defender abilities are not factored into scoring (defender is passive in fast mode, uses base abilities in sim mode). |
| Defender boons in sim mode | Passed through `settings.defender_boons` in SimConfig, which the simulation engine already supports. |
| `defender_build` without `defender_hero` | No-op — `_resolve_defender` returns generic (0, 0, 0) since hero is None. |

---

## Complexity Tracking

No constitution violations — no complexity exceptions needed.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
