# Implementation Plan: Ability Upgrade Optimizer

**Branch**: `021-ability-upgrade-optimizer` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/021-ability-upgrade-optimizer/spec.md`

## Summary

Add an engine function that ranks all available (unpicked, affordable) ability upgrades for a hero by their spirit DPS delta, and surface those recommendations in both the GUI Build tab and CLI. The engine iterates each candidate upgrade, computes spirit DPS with and without it via the existing `DamageCalculator.hero_total_spirit_dps()`, and returns a sorted list of `UpgradeCandidate` result dataclasses. The GUI renders these as a "Suggested Upgrades" panel below the existing ability upgrade buttons; the CLI exposes them via a new menu option.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: NiceGUI (GUI), existing engine modules (no new deps)
**Storage**: N/A (in-memory calculations on existing cached API data)
**Testing**: pytest + engine unit tests; Playwright integration tests for GUI
**Target Platform**: Desktop (Windows/Linux/macOS), localhost web UI
**Project Type**: Desktop CLI + Web GUI application
**Performance Goals**: All upgrade candidates scored in <200ms (SC-001)
**Constraints**: Typically 4 abilities × 3 tiers = ≤12 candidates per hero; each requires one `hero_total_spirit_dps` call (~1ms each) — well within budget.
**Scale/Scope**: Single-hero, single-build context; no combinatorial explosion.

## Constitution Check

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Pure Calculation Engine | **PASS** | New `rank_ability_upgrades()` is a `@staticmethod` on a new `AbilityOptimizer` class in `engine/`. Pure function: takes hero, build stats, boons, current upgrades → returns `list[UpgradeCandidate]`. No I/O, no UI imports. |
| II | API-First Data | **PASS** | Uses existing `HeroAbility` and `AbilityUpgrade` models parsed from the API. No new data sources or hardcoded values. |
| III | Strict Layer Separation | **PASS** | Engine function in `engine/damage.py` (or new thin module). UI calls engine and formats results. No upward dependencies. |
| IV | Dual Interface Parity | **PASS** | GUI: suggestion panel in Build tab. CLI: new "Ability Upgrade Optimizer" menu option. Both call the same engine function. |
| V | Simplicity First | **PASS** | Single function + one result dataclass. No framework, no plugin system. `AbilityOptimizer` is a namespace class with one static method — justified because it groups with existing engine patterns but is a distinct concern from `DamageCalculator`. Alternative: add method directly to `DamageCalculator`. Decision: keep on `DamageCalculator` to avoid a new module for a single function — Simplicity First. |
| VI | Mechanic Extensibility | **PASS** | AP costs come from `ABILITY_TIER_COSTS` (parameterized). Spirit DPS calculation delegates to existing `hero_total_spirit_dps()` which respects all game parameters. No new magic numbers. |

## Project Structure

### Documentation (this feature)

```text
specs/021-ability-upgrade-optimizer/
├── spec.md              # Feature specification
├── plan.md              # This file
└── tasks.md             # Phase 2 output (to be generated)
```

### Source Code (repository root)

```text
deadlock_sim/
├── models.py                  # ADD: UpgradeCandidate dataclass
├── engine/
│   ├── __init__.py            # ADD: export UpgradeCandidate
│   └── damage.py              # ADD: DamageCalculator.rank_ability_upgrades()
└── ui/
    ├── gui.py                 # MODIFY: add suggestion panel in Build tab
    └── cli.py                 # MODIFY: add "Ability Upgrade Optimizer" menu option
tests/
└── test_engine.py             # ADD: tests for rank_ability_upgrades()
```

## Design

### 1. New Data Model — `UpgradeCandidate`

**File**: `deadlock_sim/models.py`

```python
@dataclass
class UpgradeCandidate:
    """A ranked ability upgrade recommendation."""
    ability_index: int          # index into hero.abilities
    ability_name: str           # human-readable name
    tier: int                   # tier number (1, 2, or 3)
    ap_cost: int                # ability points required
    spirit_dps_delta: float     # DPS increase if this upgrade is taken
```

This follows the project convention of dedicated result dataclasses (like `BulletResult`, `SpiritResult`, etc.).

### 2. Engine Function — `DamageCalculator.rank_ability_upgrades()`

**File**: `deadlock_sim/engine/damage.py`

```python
@staticmethod
def rank_ability_upgrades(
    hero: HeroStats,
    current_upgrades: dict[int, list[int]],
    ap_remaining: int,
    current_spirit: int = 0,
    cooldown_reduction: float = 0.0,
    spirit_amp: float = 0.0,
    enemy_spirit_resist: float = 0.0,
    resist_shred: float = 0.0,
    boons: int = 0,
    weapon_damage_bonus: float = 0.0,
    melee_damage_pct: float = 0.0,
) -> list[UpgradeCandidate]:
```

**Algorithm**:
1. Compute baseline spirit DPS via `hero_total_spirit_dps(hero, ..., ability_upgrades=current_upgrades)`.
2. For each ability index `i` (0..len(hero.abilities)-1):
   a. Determine `max_tier_purchased` from `current_upgrades.get(i, [])`.
   b. `next_tier = max(current_tiers) + 1` if any, else `1`.
   c. If `next_tier > 3` → skip (fully upgraded).
   d. `ap_cost = ABILITY_TIER_COSTS[next_tier - 1]`.
   e. If `ap_cost > ap_remaining` → skip (can't afford).
   f. Build `trial_upgrades = {**current_upgrades, i: current_tiers + [next_tier]}`.
   g. Compute trial DPS via `hero_total_spirit_dps(hero, ..., ability_upgrades=trial_upgrades)`.
   h. `delta = trial_dps - baseline_dps`.
   i. Append `UpgradeCandidate(i, ability.name, next_tier, ap_cost, delta)`.
3. Sort by `spirit_dps_delta` descending.
4. Return the sorted list.

**Key decisions**:
- Only evaluates the *next* available tier per ability (not multi-tier lookahead). This keeps complexity O(n) where n = number of abilities (typically 4). Multi-tier lookahead would require combinatorial search and violates Simplicity First for marginal benefit.
- Reuses `hero_total_spirit_dps()` directly — no parallel computation path that could diverge.
- Non-damaging upgrades (utility-only) will naturally show `delta ≈ 0` and sort to the bottom, which is correct behavior. The UI can optionally label these.

### 3. GUI Integration — Build Tab Suggestion Panel

**File**: `deadlock_sim/ui/gui.py`

**Location**: Inside the existing `refresh_build_display()` function, after the ability upgrade buttons area (after line ~1980 in current code), add a "Suggested Upgrades" section.

**Rendering**:
- Only shown when `ap_remaining > 0` and at least one candidate exists.
- Rendered as a compact list below the ability tier buttons.
- Each row shows: ability name, tier, AP cost, and `+X.X Spirit DPS` delta.
- Clicking a suggestion applies the upgrade (calls existing `state.build_ability_upgrades` setter) and refreshes.
- Styled consistently with the existing ability upgrade section (same border colors, fonts).

**Data flow**:
```
refresh_build_display()
  → builds current_upgrades map (already computed)
  → calls DamageCalculator.rank_ability_upgrades(hero, current_upgrades, ap_remaining, ...)
  → renders each UpgradeCandidate in a clickable row
  → on click: apply upgrade → refresh_build_display() (loop)
```

### 4. CLI Integration

**File**: `deadlock_sim/ui/cli.py`

Add a new menu option (e.g., option 9 or appended to existing menu) titled "Ability Upgrade Optimizer". Flow:

1. Prompt for hero name (reuse existing hero selection pattern).
2. Prompt for boon level (or soul count).
3. Prompt for already-taken upgrades (or assume none).
4. Call `DamageCalculator.rank_ability_upgrades()`.
5. Print a formatted table:
   ```
   Rank | Ability            | Tier | AP Cost | Spirit DPS Delta
   ─────┼────────────────────┼──────┼─────────┼─────────────────
    1   | Afterburn          | T1   |    1    | +12.3
    2   | Concussive Comb.   | T1   |    1    | +8.7
    3   | Catalyst           | T2   |    2    | +5.1
   ```

### 5. Tests

**File**: `tests/test_engine.py`

Add tests for `rank_ability_upgrades()`:

- **test_rank_returns_sorted_candidates**: Call with a hero with known abilities, verify results are sorted by delta descending.
- **test_rank_respects_ap_budget**: Call with `ap_remaining=1`, verify only T1 candidates (cost=1) are returned.
- **test_rank_skips_fully_upgraded**: Set ability 0 to T3, verify it doesn't appear in results.
- **test_rank_empty_when_no_ap**: Call with `ap_remaining=0`, verify empty list.
- **test_rank_includes_next_tier_only**: With T1 taken on ability 0, verify T2 (not T1 or T3) is the candidate for that ability.

## Complexity Tracking

No constitution violations. No complexity exceptions needed.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Single-tier vs multi-tier lookahead | Single (next tier only) | Simplicity First; 4 candidates is instantly interpretable. Multi-tier combinatorial adds complexity with minimal user value. |
| New module vs existing module | Add to `DamageCalculator` in `damage.py` | One function doesn't justify a new module. Follows Simplicity First. |
| Utility upgrades (zero delta) | Include with delta=0, sort to bottom | Honest representation; user can see "this upgrade doesn't add DPS" which is itself useful info. |
