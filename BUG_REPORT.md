# DeadlockSim Bug Report

Generated: 2026-04-04

---

## Summary

| # | Severity | File | Bug |
|---|----------|------|-----|
| 1 | **Critical** | `ui/state.py` | `set_hero()` clears the *new* hero's config instead of the old hero's |
| 2 | **Critical** | `ui/state.py` | `get_combat_config()` references non-existent `self._boons` → `AttributeError` |
| 3 | **Medium** | `engine/simulation.py` | `_build_combatant()` ignores `spirit_power_pct` multiplier (e.g. Boundless Spirit) |
| 4 | **Medium** | `engine/simulation.py` | `_build_combatant()` uses `hero.pellets` instead of `effective_pellets()`, ignoring per-target pellet cap (Drifter 3x overcount) |
| 5 | **Medium** | `engine/simulation.py` | `_find_kill_time()` counts shield-absorbed damage against shieldless max HP, reporting early kill times and inflating DPS |
| 6 | **Medium** | `engine/simulation.py` | Headshot multiplier always uses `SimSettings` default (1.5) instead of hero's `crit_bonus_start`; heroes like Drifter/Graves get wrong crit values |
| 7 | **Medium** | `mcp_server.py` | Spirit power calculation ignores `spirit_power_pct` in two places |
| 8 | **Medium** | `ui/gui.py` | `damage_gain` formatted as `%` instead of flat value — displays "76.00%" instead of "0.76" |
| 9 | **Medium** | `tests/conftest.py` | Hardcoded Linux paths for `cwd` and Chromium executable break tests on Windows |
| 10 | **Low** | `patchnotes.py` | Duplicate unreachable `elif "scaling"` branch (dead code) |

---

## Detailed Descriptions

### Bug 1 — `set_hero()` clears wrong hero's ability config

**File:** `deadlock_sim/ui/state.py`, lines 83–89  
**Severity:** Critical

```python
def set_hero(self, name: str) -> "BuildState":
    if name != self._hero_name:
        self._hero_name = name                              # assigns NEW name first
        self._disabled_abilities.pop(self._hero_name, None) # pops NEW name's config!
        self._ability_priority.pop(self._hero_name, None)   # pops NEW name's config!
    return self
```

`self._hero_name` is set to the new hero *before* the `.pop()` calls, so the code deletes the incoming hero's saved ability configuration instead of the outgoing hero's. If a user switches Haze → Infernus → Haze, Haze's config from the first session is silently destroyed on the second switch.

**Fix:** Save the old name before overwriting, or swap the assignment order.

---

### Bug 2 — `get_combat_config()` references `self._boons` (does not exist)

**File:** `deadlock_sim/ui/state.py`, line 182  
**Severity:** Critical

```python
def get_combat_config(self, **overrides: object) -> CombatConfig:
    stats = self.get_build_stats()
    cfg = BuildEngine.build_to_attacker_config(stats, boons=self._boons)  # ← AttributeError
```

The class has a *property* `self.boons` (line 47) but no `_boons` attribute. Any caller of `get_combat_config()` will crash with `AttributeError`. Currently unused by the GUI, so this has been silent.

**Fix:** Change `self._boons` to `self.boons`.

---

### Bug 3 — Simulation ignores `spirit_power_pct` multiplier

**File:** `deadlock_sim/engine/simulation.py`, line 751  
**Severity:** Medium

```python
spirit_from_boons = hero.spirit_gain * boons
spirit_power = spirit_from_boons + stats.spirit_power   # ← missing * (1 + spirit_power_pct)
```

The centralized `BuildEngine.build_to_attacker_config()` correctly applies the percentage:
```python
current_spirit = int((build_stats.spirit_power + spirit_gain * boons) * (1.0 + build_stats.spirit_power_pct))
```

Items like **Boundless Spirit** and **Improved Spirit** that provide `spirit_power_pct` will have their percentage bonus completely ignored in simulation results, undervaluing spirit damage for any build containing them.

---

### Bug 4 — Simulation ignores per-target pellet cap

**File:** `deadlock_sim/engine/simulation.py`, line 744  
**Severity:** Medium

```python
dmg_per_bullet = boon_dmg * hero.pellets * (1.0 + weapon_bonus)
```

`DamageCalculator` uses `effective_pellets(hero)` which respects `max_pellets_per_target` (e.g., Drifter fires 3 pellets but only 1 hits a single target). The simulation uses `hero.pellets` directly, causing Drifter's per-shot damage to be **3x overreported** in simulation results.

---

### Bug 5 — `_find_kill_time()` inflated by shield-absorbed damage

**File:** `deadlock_sim/engine/simulation.py`, lines 1479–1487  
**Severity:** Medium

```python
def _find_kill_time(self, cid: str, target_max_hp: float) -> float | None:
    running = 0.0
    for entry in self.timeline:
        if entry.combatant != cid:
            continue
        running += entry.damage          # ← includes shield-absorbed portion
        if running >= target_max_hp:     # ← compares against HP excluding shields
            return entry.time
    return None
```

`_apply_damage()` records the **full damage** in the timeline (before shield absorption), but `_find_kill_time()` sums this against `max_hp` (which excludes shields). When a target has shields, the running total reaches `max_hp` *before* the target actually dies, causing:
- Kill time reported earlier than actual
- DPS calculated over a shorter window (inflated)
- Winner determination potentially wrong in bidirectional mode

Additionally, regen healing is not tracked in the timeline, so targets with regen may report false kills.

---

### Bug 6 — Simulation uses wrong headshot multiplier for some heroes

**File:** `deadlock_sim/engine/simulation.py`, line 131 and 957  
**Severity:** Medium

`SimSettings.headshot_multiplier` defaults to `1.5` and is used for all heroes:
```python
hs_mult = 1.0 + s.headshot_rate * (s.headshot_multiplier - 1.0)
```

But each hero has a unique `crit_bonus_start` (e.g., Drifter = 1.3575, Graves = 1.0, most heroes = 1.65). The `_build_combatant` method has access to the hero but never overrides the global multiplier with `hero.crit_bonus_start`. `DamageCalculator` correctly uses the hero's value.

This means:
- **Drifter/Graves/Billy/etc.** get inflated headshot damage in simulation
- Most heroes get *reduced* headshot damage (1.5 vs their actual 1.65)

---

### Bug 7 — MCP server ignores `spirit_power_pct`

**File:** `deadlock_sim/mcp_server.py`, lines 387 and 431  
**Severity:** Medium

```python
total_spirit = int(build_stats.spirit_power + hero.spirit_gain * boons)
```

Both `evaluate_build` and `optimize_build` MCP tools compute spirit power manually without the `spirit_power_pct` multiplier, duplicating the formula from `BuildEngine.build_to_attacker_config()` but incorrectly. Builds with **Boundless Spirit** or **Improved Spirit** will have understated spirit DPS in MCP tool responses.

---

### Bug 8 — `damage_gain` displayed as percentage

**File:** `deadlock_sim/ui/gui.py`, line 1007  
**Severity:** Medium

```python
{"stat": "Dmg Gain / Boon", "value": _fv(hero.damage_gain, "+.2%") if hero.damage_gain else "-"},
```

`damage_gain` is a flat per-boon value (e.g., `0.76` for Haze). Python's `%` format multiplier converts this to `"+76.00%"` instead of the correct `"+0.76"`. The CLI correctly uses `"+.2f"` for this field.

---

### Bug 9 — Test fixtures hardcoded to Linux paths

**File:** `tests/conftest.py`, lines 37 and 48  
**Severity:** Medium

```python
proc = subprocess.Popen(
    ["python", "-m", "deadlock_sim.ui.gui"],
    cwd="/home/user/DeadlockSim",              # hardcoded Linux path
    env=env,
)
...
CHROMIUM_EXECUTABLE = "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome"
```

Both the working directory and Chromium executable path are hardcoded to a specific Linux environment. Tests will fail on any other machine (including Windows, the current dev environment). The `cwd` should use `Path(__file__).parent.parent` and Chromium discovery should be dynamic.

---

### Bug 10 — Duplicate unreachable `elif "scaling"` branch

**File:** `deadlock_sim/patchnotes.py`, lines 561 vs 581  
**Severity:** Low

```python
if "scaling" in stat_lower:           # line 561 — handles scaling
    ...
elif any(kw in stat_lower ...):
    ...
elif "cooldown" in stat_lower:
    ...
elif "duration" in stat_lower:
    ...
elif "scaling" in stat_lower:          # line 581 — UNREACHABLE
    ...
```

The second `elif "scaling" in stat_lower:` at line 581 can never execute because the first `if "scaling" in stat_lower:` at line 561 already catches all scaling cases. This is a copy-paste artifact.
