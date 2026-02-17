# Deadlock Simulator GUI Rewrite Plan

## Context
The backend work is complete (API client, models, data loader, engine). The GUI (`deadlock_sim/ui/gui.py`) needs to be updated to reflect all the new capabilities and the user's requested changes.

The current GUI file has been modified to include lazy-loading for the Build tab shop (returns `refresh_shop` from `_build_eval_tab()` and triggers it on first tab activation). These changes should be preserved.

## Reference: Current GUI State
- File: `deadlock_sim/ui/gui.py` (~1262 lines)
- Framework: NiceGUI (browser-based, `nicegui>=3.0`)
- Current tabs (in order): Hero Stats, Bullet Damage, Spirit Damage, Scaling, TTK, Comparison, Rankings, Build, Optimizer
- Uses `_ITEM_IMAGE` dict for local item icon mapping
- Uses `_CAT_COLORS` for category color theming
- Build tab has lazy shop loading via `_build_refresh_shop` / `_on_tab_change`

## Changes Required

### 1. Remove Bullet Damage and Spirit Damage Tabs
- Delete `_build_bullet_tab()` function entirely (~lines 446-530)
- Delete `_build_spirit_tab()` function entirely (~lines 536-606)
- Remove `tab_bullet` and `tab_spirit` from the tab definitions in `run_gui()` / `index()`
- Remove corresponding `ui.tab_panel` entries
- The spirit damage calculation still exists in the engine (`DamageCalculator.calculate_spirit`, `calculate_ability_spirit_dps`, `hero_total_spirit_dps`) — it just doesn't need its own standalone tab anymore since it's integrated into the hero page and build results

### 2. Move Hero Stats Tab to the End
- In the tab creation section of `index()`, move `tab_hero = ui.tab("Hero Stats")` to be the LAST tab
- Move its corresponding `ui.tab_panel(tab_hero)` block to the end as well
- Update `value=tab_hero` in `ui.tab_panels(tabs, value=...)` to use whichever tab should be the new default (probably the Heroes/abilities tab or Scaling)

### 3. Add New "Heroes" Tab (Abilities + Images + Upgrades)
This is a NEW tab (different from Hero Stats). It should be the first or second tab.

**Layout:**
- Hero selector dropdown at the top
- Hero image displayed prominently (use `hero.icon_url` or `hero.hero_card_url` from the API — these are remote URLs from `assets.deadlock-api.com`)
- Hero role and playstyle text
- Abilities section showing each ability with:
  - Ability icon (use `ability.image_url` — remote URL from the API)
  - Ability name and type (innate, signature, ultimate)
  - Description text
  - Key stats: base damage, cooldown, duration, spirit scaling coefficient
  - **Upgrade popup on hover**: When hovering over an ability, show a tooltip/popup with the T1/T2/T3 upgrade descriptions from `ability.upgrades` list (each has `.tier` and `.description`)
- Spirit DPS section: Use `DamageCalculator.hero_total_spirit_dps()` to show the hero's total spirit DPS, with inputs for spirit power and CDR

**Data access:**
- `hero.abilities` — list of `HeroAbility` objects
- `hero.icon_url`, `hero.hero_card_url` — remote image URLs
- Each `HeroAbility` has: `.name`, `.class_name`, `.ability_type`, `.description`, `.image_url`, `.cooldown`, `.duration`, `.base_damage`, `.spirit_scaling`, `.upgrades` (list of `AbilityUpgrade` with `.tier`, `.description`), `.properties` (raw dict)
- For spirit DPS calculation: `DamageCalculator.calculate_ability_spirit_dps(ability, current_spirit, cooldown_reduction, spirit_amp, enemy_spirit_resist, resist_shred)` and `DamageCalculator.hero_total_spirit_dps(hero, ...)`

**Upgrade hover popup implementation:**
- Use NiceGUI's tooltip or a custom HTML hover div similar to the existing item tooltips
- Style with purple/spirit theme colors
- Show tier number (T1/T2/T3) and description for each upgrade

### 4. Update Scaling Tab for Multi-Hero Comparison
Current state: Single hero selector, shows DPS and HP scaling curves for one hero.

**Changes needed:**
- Replace single `ui.select` with a multi-select or a mechanism to add/remove heroes (e.g., a select + "Add" button, with chips showing selected heroes that can be removed)
- Plot ALL selected heroes on the same DPS chart and same HP chart
- Each hero gets a different color line
- Keep the max boons slider
- Show a comparison table below the charts with all selected heroes' stats at the current boon level
- Use `ScalingCalculator.scaling_curve(hero, max_boons)` for each selected hero

### 5. Fix Tooltip Clipping in Build Tab
Current issue: Hover tooltips on items clip on left and upper edges.

**Current tooltip CSS (`.item-tooltip`):**
```css
position: absolute;
bottom: 72px; left: 50%;
transform: translateX(-50%);
```

**Fix:**
- Add overflow handling: ensure the tooltip container doesn't overflow the viewport
- Use JavaScript or CSS to detect edge proximity and flip the tooltip position
- Simplest fix: Change positioning so tooltips appear to the right or below when near edges
- Add to `.item-tooltip`: `left: 0; transform: none;` for items near the left edge
- Or use a smarter approach: add CSS like `min-width: 220px; max-width: 300px;` and ensure the parent scroll container has `overflow: visible` or the tooltip uses `position: fixed` with JS-computed coordinates
- Consider using NiceGUI's built-in `ui.tooltip()` component instead of custom HTML tooltips, which handles positioning automatically

### 6. Add "Refresh API Data" Button
- Add a button in the header area (near the title) labeled "Refresh Data" or with a sync icon
- On click, call `from ..api_client import refresh_all_data` and run `refresh_all_data()`
- Show a loading spinner/notification during the fetch
- After completion, reload the global `_heroes` and `_items` dicts and notify the user
- Note: The API endpoint (`assets.deadlock-api.com`) may not be accessible from all environments (blocked by proxy in some sandboxed envs). Handle errors gracefully with a notification.

### 7. Update Build Results to Include Spirit DPS
In the Build evaluator results section (`_build_eval_tab` / `update_results`):
- After showing bullet DPS results, also show spirit DPS using `DamageCalculator.hero_total_spirit_dps(hero, current_spirit=int(build_stats.spirit_power), cooldown_reduction=build_stats.cooldown_reduction, spirit_amp=build_stats.spirit_amp_pct)`
- Show combined DPS (bullet + spirit)
- The `BuildResult` model already has `spirit_dps` and `combined_dps` fields

### 8. Update Item Icons to Use API URLs
Current state: Uses `_ITEM_IMAGE` dict mapping item names to local PNG filenames.

**With API data:**
- Items from the API cache have `item.image_url` field (remote URL)
- Use `item.image_url` if available, fall back to `_ITEM_IMAGE` mapping for local icons
- Update `_item_image_url()` helper to check `item.image_url` first

## New Tab Order
1. Heroes (NEW - abilities/images page)
2. Scaling (updated for multi-hero)
3. TTK
4. Comparison
5. Rankings
6. Build (with tooltip fix + spirit DPS in results)
7. Optimizer
8. Hero Stats (moved to end)

## Files to Modify
- `deadlock_sim/ui/gui.py` — main GUI file (all changes above)
- `deadlock_sim/requirements.txt` — add `requests>=2.28` if not present
- `deadlock_sim/pyproject.toml` — add `requests>=2.28` to dependencies

## Dependencies Available
- `deadlock_sim.api_client` — `refresh_all_data()`, `is_cache_available()`
- `deadlock_sim.data` — `load_heroes()`, `load_items()` (auto-detects API cache)
- `deadlock_sim.engine.damage` — `DamageCalculator` with new ability spirit DPS methods
- `deadlock_sim.models` — `HeroAbility`, `AbilityUpgrade`, updated `HeroStats`, `Item`, `BuildResult`

## Branch
All work should be on: `claude/deadlock-simulator-4GhRp`
