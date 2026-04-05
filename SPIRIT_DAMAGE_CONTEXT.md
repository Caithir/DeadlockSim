# Spirit Damage Calculations — Context for Bug Investigation

This document captures the current state of spirit damage calculations across
the codebase to help investigate reported bugs. Written for context transfer
between sessions.

## Architecture Overview

Spirit damage is calculated in two separate paths:

1. **Static calculator** (`deadlock_sim/engine/damage.py`) — `DamageCalculator.calculate_spirit()` and related methods. Used by the Heroes tab, Build tab stat panels, and the static `hero_total_spirit_dps()` summary.

2. **Simulation engine** (`deadlock_sim/engine/simulation.py`) — `CombatSimulator._apply_spirit_damage()` and the event-driven timeline. Used by the Simulation tab and Build tab's sim-based item scoring.

These two paths use **different formulas** and may produce inconsistent results.

---

## Path 1: Static Calculator (`damage.py`)

### `calculate_spirit()` (line ~121)

```python
# Spirit scaling
spirit_contribution = ability.spirit_multiplier * ability.current_spirit
raw_damage = ability.base_damage + spirit_contribution

# Spirit amplification — applies ONLY to spirit_contribution, NOT base
amp_modifier = 1.0 + ability.spirit_amp
amplified_damage = ability.base_damage + (spirit_contribution * amp_modifier)

# Item modifiers (EE, crippling, soulshredder) — applied to EVERYTHING
ee_bonus = ability.escalating_exposure_stacks * 0.06  # 6% per stack
item_modifier = 1.0 + ee_bonus + ability.crippling + ability.soulshredder
modified_raw = amplified_damage * item_modifier

# Resist
effective_shred = min(1.0, ability.resist_shred + ability.mystic_vuln)
effective_resist = max(0.0, ability.enemy_spirit_resist * (1.0 - effective_shred))
modified_damage = modified_raw * (1.0 - effective_resist)
```

**Key behavior:**
- Spirit amp applies ONLY to the spirit_contribution portion, not base_damage
- EE bonus is hardcoded at 6% per stack (not read from item data)
- Crippling and soulshredder are separate fields on AbilityConfig
- Resist shred and mystic vuln are additive before application

### `calculate_ability_spirit_dps()` (line ~192)
- Wraps `calculate_spirit()` for hero abilities
- DPS for instant abilities = `modified_damage / effective_cooldown`
- DPS for DoT abilities = `modified_damage / duration` (from `calculate_spirit`)
- **Potential bug:** DoT abilities' DPS is `modified_damage / duration` where `modified_damage` is the total damage (not DPS). But for instant abilities with a cooldown, it divides by cooldown. There may be confusion between "total damage" and "damage per cast" for DoT abilities.

### `hero_total_spirit_dps()` (line ~238)
- Sums DPS from all damaging abilities
- Does NOT currently pass EE stacks, crippling, soulshredder, resist shred, or mystic vuln — only spirit_amp and base spirit resist
- **Known issue:** This means the Heroes tab and Build tab spirit DPS summaries never account for item-based damage multipliers

### `calculate_item_damage()` (line ~318)
- For spirit-scaling items (ETechPower): `scaled_damage = (base + spirit_scale * spirit) * (1 + spirit_amp)`
- Spirit amp applies to the ENTIRE scaled damage (base + spirit contribution), unlike `calculate_spirit()` which only amps the spirit_contribution portion
- **Inconsistency with calculate_spirit()** — different amp application

---

## Path 2: Simulation Engine (`simulation.py`)

### `_apply_spirit_damage()` (line ~1002)

```python
# Spirit amp: attacker base + amp stacks on target (EE etc.)
target_amp = self.target.effective_spirit_amp(t)  # EE stacks on target
total_amp = self.attacker.spirit_amp + target_amp

# Spirit resist after all shred debuffs
resist = self.target.effective_spirit_resist(t)

# Damage amp on target (crippling / soulshredder)
damage_amp = self.target.effective_damage_amp(t)

final = raw_damage * (1.0 + total_amp) * (1.0 + damage_amp) * (1.0 - resist)
```

**Key behavior:**
- Spirit amp applies to ALL of raw_damage (base + spirit contribution) — **different from static calculator** which only amps the spirit portion
- EE stacks come from `DebuffType.SPIRIT_AMP_STACK` on the target, not hardcoded
- Crippling/soulshredder come from `DebuffType.DAMAGE_AMP` on the target
- Spirit amp and damage amp are separate multipliers (multiplicative, not additive)
- Resist uses mechanic-based pooling via `TargetState.effective_spirit_resist()`

### EE Stack Value
- `classify_item()` reads `MagicIncreasePerStack` from item properties for the stack_value
- `_on_spirit_damage()` applies stacks via `apply_debuff(SPIRIT_AMP_STACK, ...)`
- The stack value is whatever the API returns, not hardcoded 6%

### Ability Scheduling
- `_seed_abilities()` auto-schedules all abilities with `base_damage > 0 and cooldown > 0`
- `_handle_ability_use()` computes: `raw = ability.base_damage + (ability.spirit_scaling * spirit_power)`
- For DoT abilities (duration > 0): splits total damage across ticks at 1s intervals
- For instant abilities: calls `_apply_spirit_damage(t, name, raw)` directly

---

## Known Inconsistencies Between the Two Paths

| Aspect | Static (`damage.py`) | Simulation (`simulation.py`) |
|--------|---------------------|------------------------------|
| Spirit amp target | Only spirit_contribution | All of raw_damage |
| EE per-stack value | Hardcoded 0.06 (6%) | Read from item data |
| Damage amp (crippling) | Additive with EE in item_modifier | Separate multiplier |
| Resist shred | Additive (shred + mystic_vuln) | Mechanic-based pool (all sources) |
| DoT DPS calculation | total_damage / duration | tick_damage per tick scheduled at tick_rate |

## Potential Bugs to Investigate

1. **Spirit amp formula mismatch**: `damage.py` only amps spirit_contribution. `simulation.py` amps all of raw_damage. Which is correct per game mechanics?

2. **EE stack value**: `damage.py` hardcodes 6% per stack. `simulation.py` reads from API. The API value should be authoritative — check what `MagicIncreasePerStack` actually returns.

3. **Spirit DPS summary ignores items**: `hero_total_spirit_dps()` never passes EE, crippling, soulshredder, or resist shred. The Build tab's spirit DPS stat in the left panel doesn't reflect these item effects.

4. **Item damage spirit amp**: `calculate_item_damage()` applies spirit_amp to the full scaled amount `(base + spirit_scale * spirit) * (1 + spirit_amp)`, which is different from `calculate_spirit()` behavior. Three different formulas for spirit amp across the codebase.

5. **DoT ability handling**: In the simulation, DoT abilities use a hardcoded 1s tick rate. The static calculator uses `duration` directly. Neither reads per-ability tick rates from the API.

6. **Ability damage in simulation**: `_handle_ability_use()` computes `raw = base_damage + spirit_scaling * spirit_power` but does NOT apply spirit_amp before passing to `_apply_spirit_damage()`. The amp is applied inside `_apply_spirit_damage()` to the full raw amount. This means base_damage gets amped too, which may not match the game.

## Key Files

- `deadlock_sim/engine/damage.py` — Static calculators
- `deadlock_sim/engine/simulation.py` — Event-driven simulation
- `deadlock_sim/models.py` — Data models (AbilityConfig, SpiritResult, etc.)
- `deadlock_sim/data.py` — API data parsing into models
- `deadlock_sim/ui/gui.py` — UI that calls both calculators

## Key Data Model Fields

### AbilityConfig (models.py)
- `base_damage`, `spirit_multiplier`, `current_spirit`
- `spirit_amp` — from items
- `escalating_exposure_stacks` — hardcoded stack count
- `crippling`, `soulshredder` — item damage multipliers
- `resist_shred`, `mystic_vuln` — separate resist shred sources

### SimSettings (simulation.py)
- `attacker_boons`, `defender_boons`
- `accuracy`, `headshot_rate`, `weapon_uptime`, `ability_uptime`

### DebuffType (simulation.py)
- `SPIRIT_RESIST_SHRED` — from Mystic Vuln, EE, Spirit Shredder
- `SPIRIT_AMP_STACK` — EE stacks that amp spirit damage
- `DAMAGE_AMP` — crippling/soulshredder (amps ALL damage)
- `BULLET_RESIST_SHRED`, `FIRE_RATE_SLOW`, `MOVE_SPEED_SLOW`, `HEAL_REDUCTION`
