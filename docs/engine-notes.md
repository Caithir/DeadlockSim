# Engine notes

How the simulator models Deadlock, what it leaves out, and the open questions. Code references are
to the Rust sources under `src/`. Game-mechanic background lives in `docs/mechanics/`.

This file replaces the earlier `TODO_ENGINE.md`, `TODO_SIMULATION.md`, `BUG_REPORT.md`,
`SPIRIT_DAMAGE_CONTEXT.md` and `issues/` notes, which described the Python implementation. Every
item in them was either fixed in Python before the port, fixed in the port, or no longer applies;
they remain in git history.

## Two calculation paths

| | Analytic (`engine/damage.rs`, `engine/heroes.rs`, `engine/analysis.rs`) | Simulation (`engine/simulation.rs`) |
|---|---|---|
| Used by | Build stat sheet, item impact sort, optimizer, matchups, TTK | Simulation tab, "⚔ Sim" item sorts |
| Time | Closed-form per-second rates | Event queue: shots, reloads, procs, DoT ticks, casts, melee, regen |
| Accuracy / headshots | Expected value | Expected value per shot |
| Item procs and debuffs | Not included in spirit DPS | Modeled (proc cooldowns, buildup, stacking amp, shred pools) |
| Target | Item-less target, base resists only | A defender hero with its own build, optionally fighting back |

`engine/montecarlo.rs` is the only place that rolls dice: it replays a gun duel shot by shot with
random hit and headshot rolls to show the spread of kill times.

## Formulas in use

- **Bullet damage per shot**: `((base + gain × boons) × (1 + weapon %) + flat) × pellets that can hit one target`.
- **Final gun DPS**: `raw × falloff × (1 + target bullet amp) × (1 − resist after shred)`; sustained DPS
  spreads a magazine's damage over magdump + reload time.
- **Falloff**: full damage up to the hero's falloff start, linear to 10% at the falloff end. API ranges
  are game units (inches) and are converted to meters when loaded (`data::UNITS_PER_METER`).
- **Headshots**: each hero's own multiplier (`crit_bonus_start`, 1.65 by default; overrides for heroes
  with reduced crit, 1.0 for Graves).
- **Resist**: stacks multiplicatively across items (`1 − Π(1 − Rᵢ)`); shred scales it down
  (`resist × (1 − shred)`), shred clamped to [0, 1].
- **Spirit damage**: `(base + scaling × spirit) × (1 + spirit amp) × (1 + damage amp) × (1 − resist)`.
  Spirit amp applies to the whole hit, the same way in both paths.
- **Spirit power**: `(item spirit + spirit per boon × boons) × (1 + spirit power %)`, truncated.
- **Melee**: weapon damage bonus applies at 50%; melee is reduced by bullet resist.
- **Shop bonuses**: per-category spend thresholds in `data::SHOP_TIER_DATA` (weapon %, vitality base-HP %,
  flat spirit).
- **Boons and ability points**: from total souls via `data::SOUL_LEVEL_TABLE`.
- **Effective HP** (build sheet, optimizer): HP pool ÷ (1 − bullet resist), then blended 50/50 with the
  spirit-resist multiplier; resists capped at 90%. The plain HP + shields pool is shown separately.

## Known limitations

- **Static spirit DPS ignores target-side effects.** The analytic path does not apply Escalating Exposure
  stacks, damage-amp items or proc damage; only the simulation does.
- **Ability DoTs tick once per second** in the simulation; per-ability tick rates are not read from the API.
- **Monte Carlo pellets hit or miss together**: one roll per shot, not per pellet.
- **The balanced optimizer favours resist stacking**, because the EHP formula above rewards resist strongly.
  The optimizer is greedy plus single-swap local search, not exhaustive.
- **Utility is not modeled**: crowd control, mobility, stealth and immunity contribute nothing unless the
  user assigns them DPS/EHP values in Settings.
- **Out of scope**: parry, projectile travel time, movement and positioning, multi-target fights,
  consumables, ability combos.
- **Shop tier bonuses are hardcoded** and need updating by hand when a patch changes them.

## Open questions about the game

- Does spirit amp apply to an ability's base damage, or only to its spirit-scaled part? Both paths
  currently amp the whole hit.
- Should Escalating Exposure's per-stack amp be read from item data in the analytic path too?
  (`AbilityConfig::ee_per_stack` defaults to 6%; the simulation reads `MagicIncreasePerStack`.)
