# Implementation Plan: Build Sharing

**Branch**: `019-build-sharing` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/019-build-sharing/spec.md`

## Summary

Add build sharing via compact encoded strings and shareable URLs. A new `BuildCodec` engine module provides stateless, pure encode/decode functions that serialize a build (hero name, item IDs, ability upgrades, extra souls) into a compact base64 string. The GUI gets "Copy Build Code" / "Paste Build Code" buttons in the Build tab and a "Share URL" button that appends the code as a query parameter. On page load, the GUI reads query parameters and auto-loads the build. The Saved Builds tab gets a copy-code icon on each build card.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: NiceGUI (GUI), base64 + struct (encoding), dataclasses (models)
**Storage**: None (stateless encoding — no server-side persistence)
**Testing**: pytest (round-trip encode/decode), Playwright (GUI clipboard + URL integration tests)
**Target Platform**: Web browser (localhost NiceGUI server)
**Project Type**: Desktop web app (single-page NiceGUI)
**Performance Goals**: Encode/decode < 1ms; build codes < 200 chars for a full 12-item build
**Constraints**: URL length < 2000 chars (browser safe limit); no external services; base64url-safe encoding
**Scale/Scope**: 1 new engine module, modifications to GUI build tab + saved builds tab, CLI parity via import/export commands

## Constitution Check

*GATE: Must pass before implementation. Re-checked after design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | **Pure Calculation Engine** | ✅ Compliant | `BuildCodec` is a stateless class with `@staticmethod` encode/decode methods in `engine/sharing.py`. No I/O, no UI imports. Takes data models in, returns data models out. |
| II | **API-First Data** | ✅ Compliant | Encoding uses `item_id` (from API) as the canonical identifier. Decoding resolves IDs back to `Item` objects via the items dict loaded from API cache. Hero identification uses `hero_id` from API. |
| III | **Strict Layer Separation** | ✅ Compliant | `engine/sharing.py` imports only from `models`. GUI calls engine to encode/decode. CLI calls the same engine functions. No upward dependencies. |
| IV | **Dual Interface Parity** | ✅ Compliant | GUI: Copy/Paste/Share URL buttons. CLI: `export-build` (prints code) and `import-build` (accepts code, displays build). Both delegate to the same `BuildCodec` engine. |
| V | **Simplicity First** | ✅ Compliant | One new dataclass (`BuildSnapshot`), one encoder class with two methods. No framework, no plugin system, no database. Uses stdlib `struct` + `base64` — zero new dependencies. |
| VI | **Mechanic Extensibility** | ✅ Compliant | The binary format uses a version byte, allowing future extensions (new fields) without breaking existing codes. Item IDs and hero IDs come from API data, not hardcoded. |

## Project Structure

### Documentation (this feature)

```text
specs/019-build-sharing/
├── spec.md              # Feature requirements
├── plan.md              # This file
└── tasks.md             # Execution checklist (generated separately)
```

### Source Code (files to modify/create)

```text
deadlock_sim/
├── models.py                    # ADD: BuildSnapshot dataclass
├── engine/
│   ├── __init__.py              # ADD: export BuildCodec
│   └── sharing.py               # NEW: BuildCodec with encode/decode statics
└── ui/
    ├── gui.py                   # MODIFY: add sharing buttons to Build tab,
    │                            #   copy icon on saved builds, URL query param loading
    └── cli.py                   # MODIFY: add export-build / import-build menu options
tests/
└── test_engine.py               # ADD: round-trip encode/decode tests
```

**Structure Decision**: New `engine/sharing.py` module is justified because encoding/decoding is a distinct responsibility from damage calculation, build aggregation, or simulation. Keeping it separate avoids bloating `builds.py`.

---

## Design

### 1. New Data Model: `BuildSnapshot` (`models.py`)

```python
@dataclass
class BuildSnapshot:
    """A serializable snapshot of a build's identity (not full stats).

    Used as the input/output of BuildCodec encode/decode.
    """
    hero_id: int = 0
    hero_name: str = ""          # resolved on decode for display
    item_ids: list[int] = field(default_factory=list)
    item_names: list[str] = field(default_factory=list)  # resolved on decode
    ability_upgrades: dict[int, int] = field(default_factory=dict)  # {ability_idx: max_tier}
    extra_souls: int = 0
```

**Rationale**: Separates the serializable identity of a build from the full `Build` / `BuildStats` objects. The codec encodes `hero_id` + `item_ids` (compact integers) rather than string names. On decode, names are resolved from the items/heroes dicts.

### 2. Binary Encoding Format

The build code is a base64url-encoded binary payload with this structure:

```
Byte 0:       Version (uint8) — currently 1
Byte 1-2:     Hero ID (uint16, big-endian)
Byte 3-4:     Extra souls / 100 (uint16, big-endian) — resolution of 100 souls
Byte 5:       Item count N (uint8, 0-12)
Byte 6:       Ability upgrade count M (uint8, 0-4)
Bytes 7..7+2N-1:   N × item IDs (uint16 each, big-endian)
Bytes ..+M×2:      M × ability upgrades as (ability_idx: uint8, max_tier: uint8)
```

**Size analysis** for a full 12-item build with 4 ability upgrades:
- Header: 7 bytes
- Items: 12 × 2 = 24 bytes
- Abilities: 4 × 2 = 8 bytes
- Total binary: 39 bytes
- Base64url: ceil(39 × 4/3) = 52 characters

Well under the 200-character target and URL-safe. Even with a `?build=` prefix, total URL addition is ~60 characters.

**Why binary + base64url over JSON + base64?**
- Compactness: 52 chars vs. ~300+ for JSON-encoded item names
- URL-safe: base64url uses `-_` instead of `+/`, no padding `=` needed
- Deterministic: struct packing is byte-exact; same build always produces the same string

**Version byte**: Allows future format changes (e.g., adding equipped ability slots) without breaking existing codes. Decoder checks version and dispatches to the appropriate parser.

### 3. Engine: `BuildCodec` (`engine/sharing.py`)

```python
class BuildCodec:
    """Stateless encode/decode for build sharing codes."""

    VERSION = 1

    @staticmethod
    def encode(snapshot: BuildSnapshot) -> str:
        """Encode a BuildSnapshot into a compact base64url string.

        Deterministic: same snapshot always produces the same code.
        """

    @staticmethod
    def decode(
        code: str,
        heroes: dict[str, HeroStats],
        items: dict[str, Item],
    ) -> BuildSnapshot:
        """Decode a build code string back into a BuildSnapshot.

        Resolves hero_id → hero_name and item_id → item_name using the
        provided lookup dicts. Unknown IDs are skipped (items removed
        in a patch) and a warning list is populated.

        Raises ValueError on invalid/corrupted codes.
        """

    @staticmethod
    def snapshot_from_state(
        hero: HeroStats,
        items: list[Item],
        ability_upgrades: dict[int, int],
        extra_souls: int = 0,
    ) -> BuildSnapshot:
        """Build a BuildSnapshot from current UI state objects."""

    @staticmethod
    def snapshot_from_saved(
        saved_data: dict,
        heroes: dict[str, HeroStats],
        items: dict[str, Item],
    ) -> BuildSnapshot:
        """Build a BuildSnapshot from a saved-build dict (localStorage format)."""
```

**Lookup strategy for decode**: Build reverse-lookup dicts `{hero_id: HeroStats}` and `{item_id: Item}` from the provided dicts. This runs once per decode (cheap) and avoids storing global state in the engine.

**Error handling**:
- Malformed base64 → `ValueError("Invalid build code format")`
- Unknown version byte → `ValueError("Unsupported build code version")`
- Truncated payload → `ValueError("Build code is corrupted")`
- Unknown item IDs → silently skipped, names omitted from `item_names`, logged as warnings

### 4. GUI Changes (`ui/gui.py`)

#### 4a. Build Tab — Sharing Buttons

Add a button row below the existing Save button in the Build Lab:

```
[ Copy Build Code ]  [ Paste Build Code ]  [ Share URL ]
```

- **Copy Build Code**: Calls `BuildCodec.snapshot_from_state(...)` → `BuildCodec.encode(...)`, then copies to clipboard via `navigator.clipboard.writeText()` (JavaScript). Shows `ui.notify("Build code copied!")`.

- **Paste Build Code**: Opens a small dialog with a text input. User pastes the code. On submit, calls `BuildCodec.decode(...)`. On success, populates the build via `load_build_from_saved()` (reusing the existing restore path by converting `BuildSnapshot` to the saved-build dict format). On error, shows `ui.notify(error_message, type="negative")`.

- **Share URL**: Encodes the build, constructs `{current_url}?build={code}`, copies URL to clipboard. Shows `ui.notify("Share URL copied!")`.

#### 4b. URL Query Parameter Loading

In the `index()` page function, after initial setup:

1. Read query params via `app.storage.browser` or `ui.run_javascript("window.location.search")`.
2. If `?build=<code>` is present, decode and auto-load.
3. Show notification: "Build loaded from shared link" or error message.

NiceGUI provides `app.storage.browser` and JavaScript access. The simplest approach:
```python
build_param = await ui.run_javascript(
    "new URLSearchParams(window.location.search).get('build')"
)
if build_param:
    # decode and load
```

This runs after the page is rendered and the Build tab is initialized.

#### 4c. Saved Builds Tab — Copy Icon

Add a copy icon button on each saved build card (next to the existing Load/Delete buttons). On click:
1. Call `BuildCodec.snapshot_from_saved(build_data, _heroes, _items)`
2. Call `BuildCodec.encode(snapshot)`
3. Copy to clipboard
4. Show notification

### 5. CLI Changes (`ui/cli.py`)

Add two new menu options to the main menu:

- **Export Build Code**: After a build is created via `_pick_items()`, encode it and print the code string to terminal.
- **Import Build Code**: Prompt for a code string, decode it, display the build (hero, items, boons), then offer to run calculations on it.

These reuse the existing `_pick_hero()` and item display patterns. The encode/decode calls are identical to the GUI path since `BuildCodec` is pure engine code.

### 6. Test Plan

#### Engine Tests (`test_engine.py`)

```python
def test_build_codec_roundtrip():
    """Encode a snapshot, decode it, verify identical."""

def test_build_codec_empty_build():
    """Encode/decode a build with no items."""

def test_build_codec_unknown_item_skipped():
    """Decode a code with an item ID not in current data → skipped."""

def test_build_codec_invalid_code():
    """Invalid base64 → ValueError."""

def test_build_codec_deterministic():
    """Same snapshot encoded twice → identical strings."""
```

#### GUI Integration Tests (`test_gui.py`)

```python
def test_copy_paste_build_code():
    """Copy code, paste in new session, verify build matches."""

def test_share_url_loads_build():
    """Generate URL, navigate to it, verify build auto-loads."""

def test_invalid_build_code_shows_error():
    """Paste garbage → error notification, no crash."""
```

---

## Complexity Tracking

No constitution violations. No complexity exceptions needed.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| New module `engine/sharing.py` | Justified | Encoding is a distinct concern from damage/build/sim. Avoids bloating `builds.py`. |
| Binary format over JSON | Justified | 52 chars vs. 300+ chars; URL-safe; deterministic. Simplicity V is satisfied — `struct.pack` is simpler than a JSON schema with compression. |
| Version byte | Justified | Future-proofing without increasing complexity (1 byte, 1 if-check on decode). Aligns with Mechanic Extensibility (VI). |
