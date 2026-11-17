# DeadlockSim

A damage and combat simulator for Valve's Deadlock: build planning, DPS and time-to-kill math,
an event-driven combat simulation, and a build optimizer. Hero and item data comes from the
[Deadlock Assets API](https://assets.deadlock-api.com) and is cached under `data/api_cache/`.

It is a single Rust binary with four front ends over one engine:

| Front end | Command | What it is |
|---|---|---|
| Web UI | `deadlock-sim serve` | Build planner, analysis, simulation, saved builds, hero browser, patch notes |
| Scriptable CLI | `deadlock-sim <command>` | One-shot calculations, with `--json` for scripts |
| Interactive menu | `deadlock-sim` | Text menu for quick lookups |
| MCP server | `deadlock-sim mcp` | The engine as tools for AI assistants (stdio) |

## Getting started

```bash
cargo build --release
```

```bash
./target/release/deadlock-sim serve
```

Then open <http://127.0.0.1:8080>. The server binds to localhost by default; pass `--host 0.0.0.0`
(or set `HOST`) to accept remote connections, and `--port` / `PORT` to change the port.

The repository ships with a data cache. To pull the current game data:

```bash
./target/release/deadlock-sim refresh
```

## Web UI

- **Build** — pick a hero, buy items from the shop grid, allocate ability upgrades. Boons and ability
  points follow from souls. Every stat row shows where it comes from. Items can be sorted by their
  impact on *this* build (analytic or simulated). Buying an upgrade consumes the component you own
  and shows the discounted price.
- **Analysis** — next-best-purchase ranking, a goal-driven optimizer (gun, spirit, damage, tank,
  balanced), the build's power curve per purchase, gun DPS by range, and gun-duel matchups against
  every hero.
- **Simulation** — event-driven fight against a defender (optionally fighting back) with damage by
  source and DPS over time, plus a Monte Carlo gun duel showing the spread of kill times.
- **Compare** — two builds side by side.
- **Saved Builds** — stored in the browser; export/import as JSON; share a build as a link.
- **Heroes**, **Patch Notes**, **Settings** — hero stats and rankings, patch notes diffed against the
  loaded data, and the assumptions (accuracy, headshots, range, uptime, conditional item stats) used
  everywhere.

Shortcuts: `/` search items, `Ctrl+Z` / `Ctrl+Shift+Z` undo and redo, `Alt+1…8` switch tabs.

## CLI

```bash
deadlock-sim build haze -i "toxic bullets" -i headhunter --souls 2000
deadlock-sim build --code v1-d-0-0000-1p4xolo.1v1lwnv
deadlock-sim optimize infernus --goal spirit --budget 20000
deadlock-sim recommend haze -i headhunter --goal gun --available 3200
deadlock-sim simulate haze -i "toxic bullets" --vs abrams --vs-item "battle vest" --bidirectional
deadlock-sim montecarlo haze -i headhunter --vs abrams --trials 5000
deadlock-sim matchups haze -i headhunter
deadlock-sim ttk haze abrams --boons 10
deadlock-sim rank dps --boons 20
deadlock-sim patch --date 03-25-2026
```

Names are case-insensitive and may be partial (`toxic` finds Toxic Bullets); a typo gets a
"did you mean". Add `--json` to any command for machine-readable output, and see
`deadlock-sim --help` for the full list. Shell completions: `deadlock-sim completions bash`.

## MCP server

```json
{ "mcpServers": { "deadlock-sim": { "command": "/path/to/deadlock-sim", "args": ["mcp"] } } }
```

Tools cover hero and item lookup, bullet/spirit/TTK calculations, build evaluation, optimization,
purchase recommendations, combat simulation, Monte Carlo TTK, matchups and share-code decoding.

## Project layout

```
src/
  models.rs, data.rs, api_client.rs   data models, API cache parsing, API client
  engine/                             pure calculations (no I/O)
    primitives, damage, heroes        damage math, scaling, TTK
    builds, components, scoring       stat aggregation, component upgrades, item scoring
    simulation                        event-driven combat timeline
    analysis, optimizer, montecarlo   build summaries, curves, matchups, optimizer, duel rolls
    comparison                        hero comparisons and rankings
  service.rs                          request types + operations shared by every front end
  presentation.rs                     tooltips and the stat sheet
  web/                                HTTP API and the embedded single-page UI
  cli.rs, mcp.rs, main.rs             text UI, MCP server, command line
  patchnotes.rs, share.rs             patch note tooling, build share codes
tests/
  parity.rs                           replays 2,956 reference cases from the original Python engine
  features.rs                         components, optimizer, Monte Carlo, service, MCP, patch scraping
docs/mechanics/                       notes on the game mechanics being modeled
```

## Development

```bash
cargo test
cargo clippy --all-targets
cargo fmt
```

Configuration is through environment variables: `PORT`, `HOST`, `DEADLOCKSIM_DATA_DIR` (location of
the `data/` directory; defaults to `./data`, then next to the executable) and `DEADLOCKSIM_API_URL`
(alternate API base URL, useful for testing).

## Modeling notes

- Accuracy and headshots are expected values everywhere except the Monte Carlo duel.
- Resistances stack multiplicatively; shred reduces the target's resist proportionally.
- Weapon falloff is linear from full damage at the hero's falloff start to 10% at its end; the
  default engagement distance is 20 m.
- The optimizer is a greedy search refined by single-item swaps. It finds strong builds, not
  provably optimal ones, and it only values what the engine models (no crowd control or mobility).

## Deployment

`Dockerfile` builds a small container image. `.github/workflows/deploy.yml` and `infra/` deploy a
static binary to Azure App Service; see `infra/README.md`.
