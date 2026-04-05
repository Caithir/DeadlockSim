# RFC: Make Data Parsing Pipeline Testable with Structured Error Reporting

## Problem

The data parsing layer (`data.py`) relies on heuristics and silent fallbacks that are fragile and untestable:

- **Ability damage detection** uses a priority-ordered key list (`_ABILITY_DAMAGE_KEYS`) with a final fallback that scans for any property with "damage" in the name. If no key matches, `base_damage` silently defaults to 0.0 — indistinguishable from "this ability genuinely does 0 damage."
- **Weapon lookup** is fragile: tries `hero_items` by class name match, falls back to `weapons_list`. If both fail, weapon stats silently default to 0.
- **Boon scaling** handles two key formats (`"EBulletDamage"` and `"MODIFIER_VALUE_BASE_BULLET_DAMAGE_FROM_LEVEL"`) with `or` fallback. If the API introduces a third format, it silently returns 0.
- **Shop tier bonuses** are hardcoded in `_SHOP_TIER_DATA` — not fetched from the API, will silently diverge after game patches.
- **No tests exist** for any parsing logic. The only way to verify parsing works is to run the full application against live cached data.
- **Parsing can't be tested with fixtures** because `load_heroes()` and `load_items()` internally call `api_client.load_cache()` to read from disk. There's no way to inject test JSON.

## Proposed Interface

Two changes to `data.py`:

### 1. Accept optional data parameters for testability

```python
def load_heroes(
    heroes_data: list[dict] | None = None,
    hero_items_data: dict | None = None,
    weapons_data: list[dict] | None = None,
) -> dict[str, HeroStats]:
    """Load heroes from cache or provided data.
    
    If data parameters are None, loads from cache (current behavior).
    If provided, uses the given data directly (for testing).
    """

def load_items(
    items_data: list[dict] | None = None,
) -> dict[str, Item]:
    """Load items from cache or provided data."""
```

### 2. Add structured error reporting via ParseResult

```python
@dataclass
class ParseWarning:
    """A non-fatal parse issue."""
    entity_name: str        # hero or item name
    field: str              # which field was affected
    message: str            # human-readable description
    fallback_used: str      # what fallback was applied

@dataclass
class ParseResult:
    """Result of a parse operation with diagnostics."""
    heroes: dict[str, HeroStats]
    items: dict[str, Item]
    warnings: list[ParseWarning]
    failed_entities: dict[str, str]  # name -> error message

def load_heroes_verbose(
    heroes_data: list[dict] | None = None,
    hero_items_data: dict | None = None,
    weapons_data: list[dict] | None = None,
) -> ParseResult:
    """Load heroes with detailed parse diagnostics.
    
    Returns the same heroes dict plus a list of warnings about
    which heuristics were applied and which data was missing.
    """
```

**Usage (tests):**
```python
def test_ability_with_standard_damage_key():
    hero_data = [{"name": "TestHero", "id": 1, ...}]
    hero_items = {"1": [{"name": "Fireball", "properties": {"AbilityDamage": {"value": 50}}}]}
    
    result = load_heroes_verbose(heroes_data=hero_data, hero_items_data=hero_items)
    assert result.heroes["TestHero"].abilities[0].base_damage == 50.0
    assert not any(w.field == "base_damage" for w in result.warnings)

def test_ability_with_fallback_damage_key():
    hero_items = {"1": [{"name": "Poison", "properties": {"TechDamage": {"value": 30}}}]}
    
    result = load_heroes_verbose(heroes_data=..., hero_items_data=hero_items)
    assert result.heroes["TestHero"].abilities[0].base_damage == 30.0
    assert any(w.fallback_used == "TechDamage" for w in result.warnings)
```

**Usage (production — unchanged):**
```python
heroes = load_heroes()  # same signature, same behavior
```

## Dependency Strategy

**In-process** — reads JSON from local cache. The data parameter injection eliminates the I/O dependency for testing. No new external dependencies needed.

## Testing Strategy

- **New boundary tests to write:** Test `_parse_ability()` with sample JSON for each key in `_ABILITY_DAMAGE_KEYS`. Test weapon lookup with matching and non-matching class names. Test boon scaling with both key formats. Test `_parse_upgrade_item()` with each property in `_UPGRADE_PROP_MAP`. Test `load_heroes()` with minimal fixture data.
- **Old tests to delete:** None — no existing parsing tests.
- **Test environment needs:** Sample JSON fixtures (small dicts, not full API responses). Can be inline in test functions or in a `tests/fixtures/` directory.

## Implementation Recommendations

- The parsing module should own: API JSON → domain model conversion, key matching heuristics, cross-response joins (hero + items + weapons), and property extraction.
- It should hide: the specific key priority lists, the dual-format handling, the fallback scan logic.
- It should expose: `load_heroes()` / `load_items()` (unchanged for production), plus `load_heroes_verbose()` for diagnostics and testing.
- The data injection pattern (optional parameters defaulting to cache reads) is the minimal change needed — no new classes, no `DataProvider` hierarchy, no schema registry. Just make the existing functions accept pre-loaded data.
- Warnings should track: which fallback key was used for ability damage, which weapon lookup path was taken, which boon scaling key format matched, and any fields that defaulted to 0.
