# RFC: Consolidate TTK + Scaling into HeroMetrics Module

## Problem

Three engine modules — `TTKCalculator` (ttk.py), `ScalingCalculator` (scaling.py), and `ComparisonEngine` (comparison.py) — are shallow wrappers over `DamageCalculator`:

- **TTKCalculator** has 2 methods in 140 lines. `calculate()` calls `DamageCalculator.calculate_bullet()` then divides HP by DPS. `ttk_curve()` is `[calculate(..., boon=b) for b in range(36)]`.
- **ScalingCalculator** has 4 methods in 140 lines. `snapshot_at_boon()` calls `DamageCalculator.bullet_damage_at_boon()` and wraps the result. `scaling_curve()` is a trivial list comprehension. `growth_percentage()` is pure arithmetic.
- **ComparisonEngine** has 4 methods in 210 lines. `compare_two()` calls `ScalingCalculator.snapshot_at_boon()` on both heroes. `compare_curve()` is a loop. `rank_heroes()` branches on stat strings.
- Every `_curve()` method is a boilerplate `for boon in range(max_boons+1)` loop with per-boon config reconstruction.
- TTK and Scaling are semantically related (both analyze a single hero's stats across boons) and share the same dependency: `DamageCalculator`.
- The 3-import pattern (`from .ttk import ...; from .scaling import ...; from .comparison import ...`) adds friction for every caller.

## Proposed Interface

Merge `TTKCalculator` and `ScalingCalculator` into a new `HeroMetrics` class in `deadlock_sim/engine/heroes.py`. Keep `ComparisonEngine` separate (it operates on hero pairs/sets, a different concept) but have it depend on `HeroMetrics`.

```python
# deadlock_sim/engine/heroes.py

class HeroMetrics:
    """Combined scaling and TTK analysis for individual heroes."""

    # Scaling
    @staticmethod
    def snapshot(hero: HeroStats, boon_level: int) -> ScalingSnapshot: ...

    @staticmethod
    def scaling_curve(hero: HeroStats, max_boons: int = 35) -> list[ScalingSnapshot]: ...

    @staticmethod
    def growth_percentage(hero: HeroStats, max_boons: int = 35) -> dict[str, float]: ...

    @staticmethod
    def item_boon_scaling(base_effect: float, boon_bonus: float, max_boons: int = 35) -> list[tuple[int, float]]: ...

    # TTK
    @staticmethod
    def ttk(attacker: HeroStats, defender: HeroStats, config: CombatConfig) -> TTKResult: ...

    @staticmethod
    def ttk_curve(attacker: HeroStats, defender: HeroStats, base_config: CombatConfig, max_boons: int = 35) -> list[tuple[int, TTKResult]]: ...

# Backward-compat aliases (thin wrappers, can be removed later)
class TTKCalculator:
    calculate = staticmethod(HeroMetrics.ttk)
    ttk_curve = staticmethod(HeroMetrics.ttk_curve)

class ScalingCalculator:
    snapshot_at_boon = staticmethod(HeroMetrics.snapshot)
    scaling_curve = staticmethod(HeroMetrics.scaling_curve)
    growth_percentage = staticmethod(HeroMetrics.growth_percentage)
    boon_item_scaling = staticmethod(HeroMetrics.item_boon_scaling)
```

**ComparisonEngine** (stays in comparison.py) migrates its imports:
```python
from .heroes import HeroMetrics  # was: from .ttk import TTKCalculator; from .scaling import ScalingCalculator
```

**Callers migrate gradually:**
```python
# Before:
from deadlock_sim.engine.ttk import TTKCalculator
result = TTKCalculator.calculate(attacker, defender, config)

# After:
from deadlock_sim.engine.heroes import HeroMetrics
result = HeroMetrics.ttk(attacker, defender, config)
```

## Dependency Strategy

**In-process** — same pure computation. `HeroMetrics` depends on `DamageCalculator`. `ComparisonEngine` depends on `HeroMetrics`.

Dependency chain: `DamageCalculator` → `HeroMetrics` → `ComparisonEngine`

## Testing Strategy

- **New boundary tests to write:** Test `HeroMetrics.ttk()` with known attacker/defender stats. Test `HeroMetrics.scaling_curve()` produces monotonically increasing DPS. Test that backward-compat aliases produce identical results. Test `ComparisonEngine.rank_heroes()` with a small hero roster.
- **Old tests to delete:** None — no existing engine unit tests.
- **Test environment needs:** None — pure computation with test fixtures.

## Implementation Recommendations

- `HeroMetrics` should own: scaling snapshot computation, TTK calculation, growth percentage calculation, and the boon-level curve generator pattern.
- It should hide: the specific `DamageCalculator` calls, config reconstruction for per-boon curves, the magazine-aware TTK formula.
- It should expose: 6 static methods grouped by concept (scaling group + TTK group), plus result dataclasses.
- The shared `_build_curve()` helper pattern can be extracted to reduce boilerplate across `scaling_curve`, `ttk_curve`, and `compare_curve`.
- `ttk.py` and `scaling.py` can be emptied to re-export from `heroes.py` for backward compatibility, then removed in a future cleanup.
- `ComparisonEngine` stays separate — it operates on hero pairs and hero sets, which is a different abstraction level.
