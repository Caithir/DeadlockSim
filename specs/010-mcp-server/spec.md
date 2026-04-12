# Feature Specification: MCP Server

**Feature Branch**: `010-mcp-server`  
**Created**: 2026-04-06  
**Status**: Implemented  

## User Scenarios & Testing

### User Story 1 - AI Assistant Integration (Priority: P1)

As an AI assistant (e.g., Claude, Copilot), I want to call DeadlockSim tools via the Model Context Protocol so that I can answer player questions about hero stats, builds, and damage calculations.

**Why this priority**: MCP enables AI assistants to use DeadlockSim as a knowledge tool without a GUI.

**Independent Test**: Start MCP server, call `list_heroes` tool — returns list of all hero names.

**Acceptance Scenarios**:

1. **Given** the MCP server is running, **When** `list_heroes` is called, **Then** all hero names are returned.
2. **Given** the MCP server is running, **When** `get_hero("Infernus")` is called, **Then** full hero stats are returned.
3. **Given** a fuzzy name like "infern", **When** `get_hero` is called, **Then** it matches to "Infernus".

---

### User Story 2 - Damage Calculations via MCP (Priority: P1)

As an AI assistant, I want to calculate bullet DPS, spirit damage, and TTK via MCP tools so that I can provide accurate combat math in conversations.

**Why this priority**: Core calculations are the most-requested AI assistant features.

**Independent Test**: Call `bullet_damage(hero="Haze", boons=10)` — returns DPS result.

**Acceptance Scenarios**:

1. **Given** hero and boons, **When** `bullet_damage` is called, **Then** per-bullet damage, DPS, and sustained DPS are returned.
2. **Given** base damage and spirit scaling, **When** `spirit_damage` is called, **Then** scaled damage and DPS are returned.
3. **Given** attacker and defender, **When** `ttk` is called, **Then** time-to-kill with magazine count is returned.

---

### User Story 3 - Build Analysis via MCP (Priority: P2)

As an AI assistant, I want to evaluate and optimize builds via MCP tools so that I can recommend items to players.

**Why this priority**: Build advice is a high-value AI assistant use case.

**Independent Test**: Call `evaluate_build(hero="Haze", items=["Toxic Bullets", "Mystic Shot"])` — returns DPS, EHP, TTK.

**Acceptance Scenarios**:

1. **Given** hero and item list, **When** `evaluate_build` is called, **Then** DPS, EHP, and TTK are returned.
2. **Given** hero and budget, **When** `optimize_dps` is called, **Then** best items for DPS are returned.

---

### User Story 4 - Comparison & Ranking via MCP (Priority: P2)

As an AI assistant, I want to compare heroes and generate rankings via MCP so that I can answer "who's best at X?" questions.

**Why this priority**: Comparison queries are common in gaming conversations.

**Independent Test**: Call `compare_heroes("Haze", "Infernus", 20)` — returns side-by-side comparison.

**Acceptance Scenarios**:

1. **Given** two hero names and boon level, **When** `compare_heroes` is called, **Then** comparison with advantage indicators is returned.
2. **Given** stat name and boon level, **When** `rank_heroes` is called, **Then** ordered ranking is returned.

---

### Edge Cases

- What happens when the MCP tool receives an invalid hero name?
- How does the server handle concurrent tool calls?
- What if the data cache is stale or missing?

## Requirements

### Functional Requirements

- **FR-001**: System MUST expose 15+ tools via the Model Context Protocol.
- **FR-002**: System MUST support hero data retrieval with fuzzy name matching.
- **FR-003**: System MUST support bullet damage, spirit damage, and TTK calculations.
- **FR-004**: System MUST support build evaluation and optimization.
- **FR-005**: System MUST support hero comparison and ranking.
- **FR-006**: System MUST support scaling curve and cross-TTK matrix retrieval.
- **FR-007**: System MUST delegate all calculations to the engine layer.

### Key MCP Tools

| Tool | Description |
|------|-------------|
| `list_heroes` | All hero names |
| `get_hero` | Hero stats with fuzzy match |
| `get_hero_abilities` | Ability details |
| `list_items` | All items |
| `get_item` | Item details |
| `bullet_damage` | Bullet DPS calculation |
| `spirit_damage` | Spirit damage calculation |
| `ttk` | Time-to-kill |
| `compare_heroes` | Side-by-side comparison |
| `rank_heroes` | Hero rankings by stat |
| `evaluate_build` | Build analysis |
| `optimize_dps` | DPS-optimal build |
| `optimize_ttk` | TTK-optimal build |
| `scaling_curve` | Boon scaling data |
| `cross_ttk` | Cross-hero TTK matrix |

## Success Criteria

- **SC-001**: All MCP tools return correct results matching CLI/GUI output.
- **SC-002**: Fuzzy name matching resolves common misspellings.
- **SC-003**: MCP server starts and responds within 1 second of launch.

## Assumptions

- MCP protocol compatibility with common AI assistant clients.
- Server runs as a separate process via `deadlock-sim-mcp` entry point.

## Implementation Files

- `deadlock_sim/mcp_server.py` — MCP tool definitions and handlers
