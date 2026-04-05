# RFC: Extract Item Scoring Engine from GUI

## Problem

Two functions in the GUI layer (`_compute_impact_scores` and `_sim_item_scores` in `gui.py`) contain engine-level computation — orchestrating `BuildEngine`, `DamageCalculator`, and `CombatSimulator` calls to compute per-item DPS/EHP deltas for the shop display. This violates the Data→Engine→UI architectural rule:

- **Tight coupling to UI globals:** Both functions read module-level `_build_items`, `_sim_settings`, `_heroes`, and closure-captured NiceGUI widget values.
- **Inaccessible to CLI/MCP:** Neither the CLI nor the MCP server can access item scoring logic — only the GUI's Build tab can rank items by impact.
- **Untested:** Zero tests cover scoring correctness. The only tests are Playwright smoke tests that verify the shop loads.
- **Performance unobservable:** `_sim_item_scores` runs N full combat simulations (one per candidate item) on every shop refresh. No profiling, no caching, no visibility into computation time.

## Proposed Interface

A new `deadlock_sim/engine/scoring.py` module with a single static entry point:

```python
@dataclass
class ScoringConfig:
    """Configuration for item scoring, decoupled from UI globals."""
    sim_settings: SimSettings | None = None
    ability_schedule: list[AbilityUse] = field(default_factory=list)
    custom_item_dps: dict[str, float] = field(default_factory=dict)
    custom_item_ehp: dict[str, float] = field(default_factory=dict)

@dataclass
class ItemScore:
    """All computed metrics for a single candidate item."""
    item_name: str
    dps_delta: float = 0.0
    spirit_dps_delta: float = 0.0
    ehp_delta: float = 0.0
    dps_per_soul: float = 0.0
    ehp_per_soul: float = 0.0
    sim_dps_delta: float = 0.0
    sim_ehp_delta: float = 0.0
    sim_dps_per_soul: float = 0.0
    sim_ehp_per_soul: float = 0.0

class ItemScorer:
    @staticmethod
    def score_candidates(
        hero: HeroStats,
        baseline_build: Build,
        candidates: list[Item],
        boons: int = 0,
        mode: str = "fast",        # "fast" | "sim_gun" | "sim_spirit" | "sim_hybrid"
        config: ScoringConfig | None = None,
    ) -> dict[str, ItemScore]:
        """Score each candidate item against a baseline build.
        
        Returns dict[item_name -> ItemScore] with all computed metrics.
        """
```

**Usage (GUI):**
```python
scores = ItemScorer.score_candidates(hero, Build(items=_build_items), filtered, boons=10, mode="fast")
filtered.sort(key=lambda i: -scores[i.name].dps_delta)
```

**Usage (MCP):**
```python
scores = ItemScorer.score_candidates(hero, build, all_items, boons=5, mode="sim_gun",
    config=ScoringConfig(sim_settings=SimSettings(duration=10)))
```

The module hides: baseline computation, mode-dependent engine orchestration, EHP calculation with resist factoring, cost normalization, custom value overlays.

## Dependency Strategy

**In-process** — pure computation, no I/O. The scorer imports `BuildEngine`, `DamageCalculator`, and `CombatSimulator` from the engine layer; receives all data via parameters.

## Testing Strategy

- **New boundary tests to write:** Test `ItemScorer.score_candidates()` with known hero stats and items. Verify that adding a weapon damage item produces positive `dps_delta`. Verify that adding a vitality item produces positive `ehp_delta`. Verify `sim_gun` mode produces non-zero `sim_dps_delta`. Verify custom DPS overrides are applied.
- **Old tests to delete:** None — there are no existing tests for scoring.
- **Test environment needs:** None — pure in-process computation with test fixtures.

## Implementation Recommendations

- The scoring module should own: baseline computation, per-item delta calculation, mode routing (fast vs. simulation), cost normalization, and custom value overlays.
- It should hide: the specific engine calls needed for each mode, the SimConfig construction for simulation scoring, the EHP formula (base HP + boon scaling + item HP + shields ÷ resist).
- It should expose: a single `score_candidates()` entry point returning structured `ItemScore` results.
- Callers should migrate: GUI's `_compute_impact_scores()` and `_sim_item_scores()` should be replaced by calls to `ItemScorer.score_candidates()`. The GUI only handles filtering, sorting, and rendering.
