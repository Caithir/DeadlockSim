# RFC: Extract Build/Simulation State into Testable Module

## Problem

The GUI layer manages build and simulation state via module-level globals with no encapsulation:

```python
_build_items: list[Item] = []
_build_hero_name: str = ""
_build_boons: int = 0
_sim_settings: dict = { "duration": 15.0, "accuracy": 0.65, ... }
```

This creates several problems:

- **No validation:** Boons can be negative, items can exceed 12, accuracy can be 5.0. No setter enforces constraints.
- **No encapsulation:** Any function in gui.py can read or mutate any global. State changes are invisible.
- **Cross-tab coupling:** Build tab writes `_build_hero_name`; Simulation tab reads it. Settings tab writes `_sim_settings`; Build and Simulation tabs read it. No invalidation when upstream values change.
- **Untestable:** Testing state transitions requires spinning up a NiceGUI server with Playwright. No unit tests exist for state logic.
- **Config construction scattered:** Converting state to engine config objects (`SimSettings`, `CombatConfig`, `SimConfig`) happens inline in multiple places across tabs.

## Proposed Interface

A new `deadlock_sim/ui/state.py` module with two classes:

```python
class BuildState:
    """Fluent API for build configuration with validation."""
    
    # Properties
    hero_name: str          # read-only property
    boons: int              # read-only property
    items: list[Item]       # returns copy
    
    # Fluent setters with validation
    def set_hero(self, name: str) -> "BuildState": ...     # clears ability config on change
    def set_boons(self, boons: int) -> "BuildState": ...   # validates 0-50
    def add_item(self, item: Item) -> "BuildState": ...    # deduplicates, enforces max 12
    def remove_item(self, index: int) -> "BuildState": ... # bounds-checked
    def clear_items(self) -> "BuildState": ...
    
    # Ability config
    def disable_ability(self, hero_name: str, idx: int) -> "BuildState": ...
    def enable_ability(self, hero_name: str, idx: int) -> "BuildState": ...
    def is_ability_disabled(self, hero_name: str, idx: int) -> bool: ...
    def set_ability_priority(self, hero_name: str, indices: list[int]) -> "BuildState": ...
    
    # Config construction (one-liners for callers)
    def get_build_stats(self) -> BuildStats: ...           # cached, invalidated on change
    def get_combat_config(self, **overrides) -> CombatConfig: ...
    def to_build(self) -> Build: ...
    def to_dict(self) -> dict: ...                         # for serialization/debugging

class SimSettingsState:
    """Simulation knobs with validated setters."""
    
    duration: float = 15.0
    accuracy: float = 0.65
    headshot_rate: float = 0.10
    weapon_uptime: float = 1.0
    ability_uptime: float = 1.0
    # ... other sim fields as typed attributes
    custom_item_dps: dict[str, float]
    custom_item_ehp: dict[str, float]
    
    def to_sim_settings(self, atk_boons: int = 0, def_boons: int = 0) -> SimSettings: ...
```

**Usage (Build tab):**
```python
from deadlock_sim.ui.state import build, sim_settings

build().set_hero("Ivy").set_boons(5)
build().add_item(item)
stats = build().get_build_stats()  # cached
```

**Usage (Simulation tab):**
```python
config = SimConfig(
    attacker=hero,
    attacker_build=build().to_build(),
    settings=sim_settings().to_sim_settings(atk_boons=build().boons),
)
```

## Dependency Strategy

**In-process** — pure state management. The state module depends on `models.py` types and `BuildEngine` for config construction. It does not depend on NiceGUI or any UI framework.

## Testing Strategy

- **New boundary tests to write:** Test `BuildState.add_item()` enforces max 12 items and deduplication. Test `set_boons()` validates range. Test `set_hero()` clears ability config. Test `get_build_stats()` caching is invalidated on item change. Test `to_sim_settings()` produces correct `SimSettings`.
- **Old tests to delete:** None — no existing state tests.
- **Test environment needs:** None — pure Python, no NiceGUI required.

## Implementation Recommendations

- The state module should own: build item management, boon tracking, ability enable/disable, sim settings storage, and config object construction.
- It should hide: validation logic, cache invalidation, the mapping from state fields to `SimSettings`/`CombatConfig` fields.
- It should expose: fluent setters that return `self` for chaining, read-only properties, and `to_*()` conversion methods.
- Callers should migrate: Replace all `_build_items` globals with `build().items`. Replace `_sim_settings` dict access with `sim_settings().accuracy` (typed attributes). Replace inline `SimSettings()` construction with `sim_settings().to_sim_settings()`.
- The module should live in `deadlock_sim/ui/state.py` — it bridges UI and engine, but has no NiceGUI dependency.
