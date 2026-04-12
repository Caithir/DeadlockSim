# Copilot Instructions — DeadlockSim

DeadlockSim is a damage and combat simulator for the game Deadlock. It calculates bullet DPS, spirit damage, time-to-kill, scaling curves, build optimization, and hero comparisons. All game data is fetched from `assets.deadlock-api.com` and cached locally in `data/api_cache/`.

---

## Spec-Driven Development (SpecKit)

This project uses **SpecKit** for specification-driven development. Non-trivial features follow the pipeline:

1. **Specify** → `specs/<###-feature>/spec.md` (WHAT/WHY)
2. **Plan** → `specs/<###-feature>/plan.md` (HOW)
3. **Tasks** → `specs/<###-feature>/tasks.md` (execution checklist)
4. **Implement** → Execute tasks with test gates

Key files:
- **Constitution**: `.specify/memory/constitution.md` — six core principles that all specs/plans must satisfy
- **Templates**: `.specify/templates/` — spec, plan, tasks, checklist templates
- **Scripts**: `.specify/scripts/powershell/` — `create-new-feature.ps1`, `check-prerequisites.ps1`
- **Agents**: `.github/agents/` — `spec-writer`, `plan-writer`, `task-generator`

To start a new feature:
```powershell
.\.specify\scripts\powershell\create-new-feature.ps1 "Description of feature"
```

---

## Commands

```bash
# Install
pip install -e .

# Run interfaces
deadlock-sim          # CLI (interactive menu)
deadlock-sim-gui      # NiceGUI web interface (localhost)
deadlock-sim-mcp      # MCP server for AI assistant tools

# Tests (require pytest-playwright + Chromium)
python -m pytest tests/
python -m pytest tests/test_gui.py::test_tab_navigation -v   # single test
```

Tests spin up a live NiceGUI server on port 8080 and drive it with Playwright. They are integration tests — there are no unit tests for engine logic.

---

## Architecture

Three strict layers with one-way dependencies: **Data → Engine → UI**.

```
deadlock_sim/
├── api_client.py      # Fetch + cache API data
├── data.py            # Parse API JSON into domain models
├── models.py          # @dataclass domain objects
├── engine/            # Pure, stateless calculation modules
│   ├── damage.py      # Bullet DPS, spirit damage, item/ability damage
│   ├── ttk.py         # Time-to-kill with magazine reloads
│   ├── scaling.py     # Per-boon stat scaling curves
│   ├── builds.py      # Aggregate item stats; BuildOptimizer
│   ├── comparison.py  # Hero comparison and rankings
│   └── simulation.py  # Event-driven combat timeline (CombatSimulator)
└── ui/
    ├── cli.py         # Terminal interface
    └── gui.py         # NiceGUI web interface (9 tabs)
mcp_server.py          # MCP tool interface
```

**Engine modules have zero UI imports.** UI modules call engine functions and format result objects.

---

## Key Conventions

### Models
- All domain objects are `@dataclass` with field defaults — no ORM, no custom `__init__`.
- Calculation inputs are passed as config objects (`CombatConfig`, `AbilityConfig`, `SimSettings`), not as loose keyword arguments.
- Calculations return dedicated result dataclasses (`BulletResult`, `SpiritResult`, `TTKResult`, `BuildResult`, etc.) — never raw tuples or dicts.

### Engine
- All engine methods are `@staticmethod` — classes are namespaces, not instances (e.g., `DamageCalculator.bullet_damage_at_boon(hero, boons, config)`).
- Shred stacks up to 5 sources and is clamped to 100% before application.
- Boon levels run 0–35; each hero has per-boon `damage_gain`, `hp_gain`, and `spirit_gain` fields.
- Cooldown reduction is a fraction (0–1) applied multiplicatively.

### GUI (NiceGUI)
- Global state lives in module-level dicts: `_heroes`, `_items`, `_sim_settings`, `_build_items`.
- The Build tab uses lazy shop loading: `_build_refresh_shop` is triggered on first tab activation via `_on_tab_change`.
- Item icons use `_item_image_url()` — checks `item.image_url` (API) then falls back to `_ITEM_IMAGE` local mapping.
- Category colors are defined in `_CAT_COLORS`.

### Data
- API data is cached in `data/api_cache/` as JSON. Call `api_client.refresh_all_data()` to update.
- `data.py:load_heroes()` and `load_items()` auto-detect the cache and return typed model lists.
- `HeroStats.abilities` is a list of `HeroAbility`; each has `.upgrades` (T1/T2/T3 as `AbilityUpgrade`).
