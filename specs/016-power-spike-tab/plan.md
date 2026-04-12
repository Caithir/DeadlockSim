# Implementation Plan: Power Spike Tab

**Branch**: `016-power-spike-tab` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/016-power-spike-tab/spec.md`

## Summary

Add a "Power Spikes" GUI tab that charts how a hero's stats evolve as items are purchased in sequence. The engine computes power curve data points at each cumulative soul threshold (item purchase events), supporting 4 parallel slot-count lines (9/10/11/12), auto-sell logic (50% refund, lowest-value item), user-defined sell/swap overrides, and selectable Y-axis metrics (Total DPS, Bullet DPS, Spirit DPS, EHP, Sim DPS). The GUI renders an interactive step-function chart with drag-to-reorder item sequencing.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: NiceGUI ≥ 3.0 (charts via `ui.echart` / ECharts), existing engine modules
**Storage**: N/A (in-memory; optional save via existing build persistence)
**Testing**: pytest + Playwright (integration tests match existing pattern)
**Target Platform**: localhost web UI (NiceGUI)
**Project Type**: desktop-app (web-based GUI)
**Performance Goals**: Chart renders with 12 items across 4 slot lines in < 2 seconds (SC-001)
**Constraints**: No new runtime dependencies; use NiceGUI's built-in ECharts
**Scale/Scope**: Single new tab + one new engine module + new models

## Constitution Check

### I. Pure Calculation Engine
**COMPLIANT.** All power curve computation lives in a new `engine/powerspike.py` module. It takes dataclass inputs and returns dataclass results. No I/O, no UI imports.

### II. API-First Data
**COMPLIANT.** No new game data sources. Hero/item data comes from the existing API cache. The 50% sell refund rate is a game-defined constant parameterized as a field on the config dataclass.

### III. Strict Layer Separation
**COMPLIANT.** Dependency flow: `models.py` ← `engine/powerspike.py` ← `ui/gui.py`. The new engine module imports only from `models` and other engine modules (`builds`, `damage`, `simulation`). UI imports from engine. No circular or upward dependencies.

### IV. Dual Interface Parity
**EXCEPTION DOCUMENTED.** The power spike chart is a visual-first feature. The CLI will expose a text-based summary (tabular power curve data per purchase step) but will not render charts. The drag-to-reorder interaction is GUI-only. This is an inherent limitation of terminal interfaces, not a feature gap.

### V. Simplicity First
**COMPLIANT.** One new engine module, one new set of models, one new GUI tab function. No plugin systems, no abstract chart renderers. The `PowerCurveEngine` is a single class with static methods, matching the existing engine pattern.

### VI. Mechanic Extensibility
**COMPLIANT.** Sell refund rate (50%) is a named field on `PowerCurveConfig`, not a magic number. Slot counts (9–12) are parameterized. Shop tier bonus thresholds are already externalized in `_SHOP_TIER_DATA`. All game-tunable values are in model fields or named constants.

## Project Structure

### Documentation (this feature)

```text
specs/016-power-spike-tab/
├── spec.md              # Feature specification
├── plan.md              # This file
└── tasks.md             # Phase 2 output (created later)
```

### Source Code (repository root)

```text
deadlock_sim/
├── models.py                    # ADD: PowerCurveConfig, PurchaseEvent, PowerCurvePoint, PowerCurveResult
├── engine/
│   ├── __init__.py              # MODIFY: export PowerCurveEngine
│   └── powerspike.py            # NEW: power curve computation engine
└── ui/
    ├── gui.py                   # MODIFY: add Power Spikes tab
    ├── state.py                 # MODIFY: add purchase order state
    └── cli.py                   # MODIFY: add power curve text summary
```

**Structure Decision**: Single new engine module (`powerspike.py`) following the same pattern as `simulation.py`, `scoring.py`, etc. No sub-packages needed — the feature is self-contained.

---

## Design

### 1. New Data Models (`models.py`)

```python
@dataclass
class PurchaseEvent:
    """A single step in a build's purchase sequence."""
    action: str                   # "buy" | "sell" | "swap"
    item: Item                    # item being bought (or sold)
    swap_target: Item | None = None  # for "swap": the item being sold to make room
    cumulative_souls: int = 0     # soul count after this event

@dataclass
class PowerCurveConfig:
    """Input configuration for power curve computation."""
    hero: HeroStats = field(default_factory=lambda: HeroStats(name="Unknown"))
    purchase_order: list[PurchaseEvent] = field(default_factory=list)
    slot_counts: list[int] = field(default_factory=lambda: [9, 10, 11, 12])
    sell_refund_rate: float = 0.5           # game-defined 50% refund
    metrics: list[str] = field(default_factory=lambda: ["total_dps"])
    # Metrics: "total_dps", "bullet_dps", "spirit_dps", "ehp", "sim_dps"
    
    # Sim settings (used only when "sim_dps" metric is requested)
    sim_settings: SimSettings | None = None
    ability_upgrades: dict[int, list[int]] = field(default_factory=dict)
    
    # Combat assumptions
    accuracy: float = 0.65
    headshot_rate: float = 0.0
    defender: HeroStats | None = None       # default target dummy

@dataclass
class PowerCurvePoint:
    """A single data point on one power curve line."""
    cumulative_souls: int
    active_items: list[str]                  # item names currently held
    sold_item: str | None = None             # item auto-sold at this step (if any)
    metrics: dict[str, float] = field(default_factory=dict)
    # Keys match PowerCurveConfig.metrics; values are computed stat values

@dataclass
class PowerCurveResult:
    """Complete power curve output for all slot configurations."""
    hero_name: str
    curves: dict[int, list[PowerCurvePoint]]  # slot_count → ordered points
    purchase_events: list[PurchaseEvent]       # canonical buy order
```

### 2. Engine Module (`engine/powerspike.py`)

```python
class PowerCurveEngine:
    """Compute power curves across item purchase sequences."""

    @staticmethod
    def compute_curves(config: PowerCurveConfig) -> PowerCurveResult:
        """Main entry point: compute power curve for all slot counts."""
        ...

    @staticmethod
    def _evaluate_at_step(
        hero: HeroStats,
        active_items: list[Item],
        cumulative_souls: int,
        config: PowerCurveConfig,
    ) -> dict[str, float]:
        """Compute requested metrics for a given item set and soul count."""
        ...

    @staticmethod
    def _auto_sell_item(
        active_items: list[Item],
        refund_rate: float,
    ) -> tuple[list[Item], Item, int]:
        """Remove the lowest-value item, return (new_items, sold_item, refund)."""
        ...

    @staticmethod
    def _build_slot_sequence(
        purchase_order: list[PurchaseEvent],
        max_slots: int,
        refund_rate: float,
    ) -> list[tuple[int, list[Item], str | None]]:
        """Walk purchase order, applying auto-sell when items exceed max_slots.
        
        Returns list of (cumulative_souls, active_items, sold_item_name).
        """
        ...
```

**Key implementation details:**

- `_evaluate_at_step` delegates to existing engine functions:
  - `BuildEngine.aggregate_stats(Build(items=active_items))` → `BuildStats`
  - `BuildEngine.build_to_attacker_config(bs, boons, spirit_gain)` → `CombatConfig`
  - `DamageCalculator.calculate_bullet(hero, config)` → `BulletResult` for bullet DPS
  - `DamageCalculator.hero_total_spirit_dps(hero, ...)` for spirit DPS
  - `BuildEngine.defender_effective_hp(...)` for EHP (using hero as own defender for self-EHP)
  - `CombatSimulator.run(SimConfig(...))` for sim DPS (expensive; computed on demand)
- Boons at each step = `souls_to_boons(cumulative_souls)` — boon progression is built into the X axis
- Shop tier bonuses are automatically included via `BuildEngine.aggregate_stats`
- For each slot count, the engine walks the same purchase order but triggers auto-sell when `len(active_items) > max_slots`
- Auto-sell picks the item with the lowest `item.cost` (proxy for "lowest value"); the 50% refund is subtracted from the cumulative soul cost of subsequent items

### 3. GUI Tab (`ui/gui.py`)

New function `_build_power_spike_tab(state: BuildState)` added alongside existing tab builders.

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│  [Hero: ___]  [Metric toggles: ☑DPS ☐Bullet ...]  │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │           ECharts Step Line Chart             │   │
│  │  Y: selected metrics                          │   │
│  │  X: cumulative souls                          │   │
│  │  Lines: 9-slot, 10-slot, 11-slot, 12-slot    │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  Purchase Order (drag to reorder):                  │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐              │
│  │ 1. │ │ 2. │ │ 3. │ │ 4. │ │ 5. │  ...         │
│  │Item│ │Item│ │Item│ │Item│ │Item│              │
│  └────┘ └────┘ └────┘ └────┘ └────┘              │
│                                                     │
│  [Compute Sim DPS]  (only when sim_dps toggled)    │
└─────────────────────────────────────────────────────┘
```

**Chart implementation:**
- `ui.echart(options)` with ECharts `type: 'line'` and `step: 'end'` for step-function appearance
- 4 series (one per slot count), each with distinct color and label
- Multiple Y-axis metric lines use ECharts multi-axis support or normalized overlay
- Tooltip shows item purchased, items sold, current item set at each X point

**Drag-to-reorder:**
- NiceGUI's `ui.sortable` (or a custom `ui.row` with drag events via `ui.element`) for the purchase order list
- On reorder, rebuild `purchase_order` and call `PowerCurveEngine.compute_curves()`, update chart

**Data flow:**
1. User selects hero + items in the Build tab (shared state via `BuildState`)
2. Power Spikes tab reads `state.items` and defaults to cost-ascending purchase order
3. User can drag-to-reorder
4. On any change, engine recomputes → chart updates
5. "Compute Sim DPS" button triggers expensive simulation for each step

### 4. State Extension (`ui/state.py`)

Add to `BuildState`:

```python
@property
def purchase_order(self) -> list[Item]:
    """Items in their planned purchase sequence (default: cost ascending)."""
    ...

def set_purchase_order(self, order: list[Item]) -> None:
    """Set explicit purchase order."""
    ...

def add_sell_event(self, sell_item: Item, buy_item: Item, after_index: int) -> None:
    """Insert a sell/swap event into the purchase sequence."""
    ...
```

### 5. CLI Summary (`ui/cli.py`)

Add a "Power Curve" menu option that prints a table:

```
Purchase Order Power Curve (12 slots):
Step  Souls   Item Bought       Bullet DPS  Spirit DPS  EHP
  1     500   Headshot Booster    142.3        0.0      650
  2    1750   Mystic Shot         142.3       28.4      650
  3    4750   Toxic Bullets       168.1       28.4      650
  ...
```

Text-mode only; no chart rendering. Covers all 4 slot lines if requested.

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `deadlock_sim/models.py` | MODIFY | Add `PurchaseEvent`, `PowerCurveConfig`, `PowerCurvePoint`, `PowerCurveResult` |
| `deadlock_sim/engine/powerspike.py` | CREATE | `PowerCurveEngine` with `compute_curves`, `_evaluate_at_step`, `_auto_sell_item`, `_build_slot_sequence` |
| `deadlock_sim/engine/__init__.py` | MODIFY | Export `PowerCurveEngine`, `PowerCurveConfig`, `PowerCurveResult` |
| `deadlock_sim/ui/gui.py` | MODIFY | Add `_build_power_spike_tab()`, register new tab in `run_gui()` |
| `deadlock_sim/ui/state.py` | MODIFY | Add `purchase_order`, `set_purchase_order`, `add_sell_event` |
| `deadlock_sim/ui/cli.py` | MODIFY | Add power curve text table menu option |
| `tests/test_engine.py` | MODIFY | Add tests for `PowerCurveEngine` |

---

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| CLI lacks chart visualization (Principle IV exception) | Terminal cannot render interactive charts | A text table of power curve data points provides equivalent data access; the chart is a presentation concern, not a capability gap |
