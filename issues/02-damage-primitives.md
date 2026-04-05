# RFC: Extract Shared Damage Primitives

## Problem

Core damage formulas are duplicated between `DamageCalculator` (damage.py) and `CombatSimulator`/`TargetState` (simulation.py):

- **Resist formula** appears in `DamageCalculator.final_resist()` and `TargetState.effective_bullet_resist()`. Both implement `max(0, min(1, base_resist * (1 - shred)))`. If the game changes how shred interacts with resist, two files need updating.
- **Spirit damage pipeline** — amp, damage_amp, and resist application — is computed separately in `DamageCalculator.calculate_spirit()` (from `AbilityConfig` scalars) and `CombatSimulator._apply_spirit_damage()` (from `TargetState` debuff pools). Same formula, different data sources.
- **Item damage extraction** — `DamageCalculator._extract_item_damage()` is a private method that `simulation.py` calls directly via `DamageCalculator._extract_item_damage(props)`. This couples simulation.py to a private implementation detail.
- If resist rules change (e.g., shred becomes additive instead of multiplicative), both files need synchronized updates — a maintenance and correctness risk.

## Proposed Interface

A new `deadlock_sim/engine/primitives.py` module with 3 pure functions:

```python
def resist_after_shred(base_resist: float, total_shred: float) -> float:
    """Compute effective resist after shred is applied.
    
    Returns: clamped resist value in [0, 1].
    Formula: max(0, min(1, base_resist * (1 - min(1, total_shred))))
    """

def apply_amplifiers(base_damage: float, spirit_amp: float = 0.0, damage_amp: float = 0.0) -> float:
    """Apply multiplicative spirit amp and damage amp to base damage.
    
    Returns: base_damage * (1 + spirit_amp) * (1 + damage_amp)
    """

def extract_item_damage(props: dict) -> tuple[float, str, float, bool, float, float] | None:
    """Parse item damage info from raw_properties dict.
    
    Returns (base_damage, scale_type, stat_scale, is_dps, dps_value, proc_chance) or None.
    Public replacement for DamageCalculator._extract_item_damage().
    """
```

**Usage in DamageCalculator:**
```python
from .primitives import resist_after_shred

eff_resist = resist_after_shred(config.enemy_bullet_resist, total_shred)
final_dps = raw_dps * (1 - eff_resist)
```

**Usage in simulation.py TargetState:**
```python
from .primitives import resist_after_shred

def effective_bullet_resist(self, time: float) -> float:
    shred = self.total_for(DebuffType.BULLET_RESIST_SHRED, time)
    return resist_after_shred(self.base_bullet_resist, shred)
```

**Usage in simulation.py classify_item:**
```python
from .primitives import extract_item_damage

damage_info = extract_item_damage(props)  # was DamageCalculator._extract_item_damage(props)
```

## Dependency Strategy

**In-process** — pure math functions with zero imports from models or other engine modules. The lowest layer in the dependency chain.

## Testing Strategy

- **New boundary tests to write:** Test `resist_after_shred()` with known inputs (0 shred, full shred, over-shred clamping, negative resist). Test `apply_amplifiers()` with combinations of spirit/damage amp. Test `extract_item_damage()` with sample property dicts matching known item formats.
- **Old tests to delete:** None — no existing tests.
- **Test environment needs:** None — pure functions, test with scalar inputs.

## Implementation Recommendations

- The primitives module should own: the resist-after-shred formula, the amplifier math, and the item property parsing heuristic.
- It should hide: clamping logic, the specific order of operations, the priority-ordered key list for item damage parsing.
- It should expose: 3 pure functions with scalar inputs and scalar/tuple outputs.
- Callers should migrate: `DamageCalculator.final_resist()` should delegate to `resist_after_shred()`. `TargetState.effective_bullet_resist()` and `effective_spirit_resist()` should delegate to `resist_after_shred()`. `DamageCalculator._extract_item_damage()` should be replaced by the public `extract_item_damage()`. The private `_extract_item_damage` can remain as a thin wrapper that calls the primitive, or be removed entirely.
