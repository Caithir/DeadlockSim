<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.1.0 (MINOR — new principle added)

Modified principles: None

Added sections:
  - Principle VI: Mechanic Extensibility (beta-game volatility)

Removed sections: N/A

Templates reviewed:
  - .specify/templates/plan-template.md  ✅ aligned
  - .specify/templates/spec-template.md  ✅ aligned
  - .specify/templates/tasks-template.md ✅ aligned

Deferred TODOs: None.
-->

# DeadlockSim Constitution

## Core Principles

### I. Pure Calculation Engine

All damage, TTK, scaling, and combat calculations MUST be implemented as
stateless pure functions in the `deadlock_sim/engine/` package. Engine code
MUST NOT perform I/O, import from UI modules, or hold mutable global state.
Every calculation MUST be independently verifiable by passing only data models
as arguments and inspecting the returned result.

**Rationale**: Purity keeps simulation results reproducible, enables testing
without infrastructure mocks, and ensures the CLI and GUI share identical
calculation logic with no risk of divergence.

### II. API-First Data

All hero and item game data MUST originate from the Deadlock Assets API
(`assets.deadlock-api.com`). No local YAML, CSV, or hardcoded data files
MUST serve as the source of truth. Disk caching (`data/api_cache/`) is
permitted for performance and offline resilience but MUST be treated as a
derivative cache — never as the canonical dataset.

**Rationale**: The game updates frequently; a single authoritative external
source prevents data drift and eliminates the maintenance burden of
hand-maintained files (learned from the prior YAML approach that was removed).

### III. Strict Layer Separation

The codebase MUST maintain four distinct layers with unidirectional
dependencies:

```
models  ←  engine  ←  data / api_client  ←  ui (cli | gui)
```

- `models` MUST NOT import from any other project layer.
- `engine` MUST import only from `models`.
- `data` and `api_client` MUST import only from `models` (and `engine` where
  needed for derived data).
- `ui` modules MUST import from lower layers but MUST NOT be imported by them.

Circular imports and upward dependencies are forbidden.

**Rationale**: Clean boundaries make each layer replaceable and testable in
isolation, and prevent coupling that plagues long-lived GUI applications.

### IV. Dual Interface Parity

The CLI (`deadlock_sim/ui/cli.py`) and GUI (`deadlock_sim/ui/gui.py`) MUST
expose equivalent simulation capabilities. Neither interface MUST implement
business logic or calculation code; both MUST delegate entirely to the engine
and data layers. Adding a capability to one interface MUST be accompanied by
equivalent support in the other, or an explicit recorded exception in the
feature spec.

**Rationale**: Users MUST be able to switch between CLI and GUI without losing
access to any simulation feature.

### V. Simplicity First

Solutions MUST use the minimum complexity required to satisfy the current
requirement. Abstractions MUST NOT be introduced for a single call-site.
Frameworks, plugin systems, and generic utilities MUST NOT be added
speculatively. When three similar code paths exist, extraction SHOULD be
evaluated — but only then.

**Rationale**: Premature abstractions add maintenance cost without current
value. The project's surface area is small enough that simplicity is always
achievable.

### VI. Mechanic Extensibility

Every base calculation, stat, and mechanic MUST be implemented so that its
parameters can be changed or overridden without restructuring the call site.
Concretely:

- Hero stats and combat parameters MUST be expressed as fields on data model
  dataclasses (`HeroStats`, `CombatConfig`, `AbilityConfig`, etc.), not as
  in-line constants or magic numbers inside engine functions.
- Engine functions MUST accept the full relevant config object rather than
  individual scalar arguments, so new fields can be added to the config
  without changing any function signatures.
- When a game mechanic changes (e.g., shred stacking formula, headshot
  multiplier baseline, resist cap), the fix MUST be locatable in a single
  model field or a single engine function — not scattered across callers.
- Hardcoded numeric literals that represent game-defined values (damage
  coefficients, resist formulas, stack limits) MUST be traced to a named
  constant or model field with a comment referencing the mechanic name, so
  they can be updated when the game patches.

**Rationale**: Deadlock is in beta; fundamental mechanics (damage formulas,
resist caps, spirit scaling, shred rules) change between patches. Centralising
every tunable value means a patch update is a data or constant change, not a
surgery across the engine. This principle deliberately creates tension with
Principle V — resolve it by parameterising game-defined values freely while
still refusing speculative *feature* abstractions.

## Technology Stack

- **Language**: Python 3.10+ (type annotations via `from __future__ import annotations`)
- **GUI framework**: NiceGUI ≥ 3.0
- **HTTP client**: requests ≥ 2.28
- **Build system**: setuptools ≥ 68.0 via `pyproject.toml`
- **Package manager**: uv (lock file at `uv.lock`)
- **Data models**: stdlib `dataclasses` — no ORM, no third-party validation
  library unless complexity demands it
- **Entry points**: `deadlock-sim` (CLI), `deadlock-sim-gui` (GUI)

New runtime dependencies MUST be added to `pyproject.toml` and the lock file
regenerated. Dev-only tooling MUST be kept in a separate dependency group.

## Development Workflow

- **Feature specs**: All non-trivial features MUST have a spec in
  `specs/<###-feature-name>/spec.md` before implementation begins.
- **Constitution Check**: Every implementation plan (`plan.md`) MUST include a
  Constitution Check section verifying compliance with all six principles
  before Phase 0 research.
- **Engine changes**: Any modification to `engine/` MUST be verified against
  known calculation values via spot-check or unit test before merging.
- **Data mapping changes**: Changes to `data.py` hero/item field mappings MUST
  be cross-checked against live API responses to confirm field names and types.
- **UI-only changes**: MUST NOT alter engine behavior or data mapping logic. If
  a UI change requires engine changes, they MUST be separated into distinct
  commits with clear scope labels.
- **Commit discipline**: Commits MUST use conventional prefixes (`feat:`,
  `fix:`, `docs:`, `refactor:`, `chore:`). Changes that affect calculation
  correctness MUST be explicitly noted in the commit message.

## Governance

This constitution supersedes all other documented practices and informal
conventions. In case of conflict, the constitution prevails.

**Amendment procedure**:
1. Open a PR describing the proposed change and its rationale.
2. Increment `CONSTITUTION_VERSION` per semantic versioning rules:
   - MAJOR: principle removed or redefined in a backward-incompatible way.
   - MINOR: new principle or section added; existing principle materially expanded.
   - PATCH: wording clarification, typo fix, or non-semantic refinement.
3. Update `LAST_AMENDED_DATE` to the amendment date (ISO 8601).
4. Propagate changes to affected templates and this file in the same PR.

**Compliance**: All PRs and feature plans MUST verify compliance with all six
core principles. Complexity violations MUST be documented in the plan's
Complexity Tracking table with explicit justification.

**Versioning policy**: `MAJOR.MINOR.PATCH`. The version line below is the
single source of truth — it MUST match the Sync Impact Report above.

---

**Version**: 1.1.0 | **Ratified**: 2026-03-24 | **Last Amended**: 2026-03-24
