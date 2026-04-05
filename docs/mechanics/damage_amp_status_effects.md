# Damage Amplification & Status Effects

> Source: https://deadlock.wiki — Last verified: March 2026

---

## Damage Amplification

Damage amplification increases ALL damage taken by the target. Applied as a final multiplier after resist calculations.

### Hero Ability Sources

| Hero     | Ability           | Amp %  | Duration | Notes                    |
|----------|-------------------|--------|----------|--------------------------|
| Infernus | Napalm            | +16%   |          | While in napalm area     |
| Shiv     | Killing Blow      | +14%   |          | At execution threshold   |
| Parry    | Successful parry  | +25%   | 2.75s    | To ALL damage sources    |

### Item Sources

| Item                  | Amp Effect              | Notes                        |
|-----------------------|-------------------------|------------------------------|
| Escalating Exposure   | +4.5% spirit amp/stack  | Max 5 stacks = +22.5%       |
| Crippling Headshot    | Damage amp on headshot  | Applies to subsequent damage |
| Soulshredder Bullets  | Damage amp on bullet hit| Stacking                     |

### Damage Reduction Sources (Defensive)

| Source           | Reduction | Notes                    |
|------------------|-----------|--------------------------|
| Cheat Death      | -60%      | Temporary on fatal proc  |
| Inhibitor        | -30%      | Applied to target        |

## Simulation Implementation

In `simulation.py`, damage amp is tracked as a **debuff pool** on the target:

```
damage_amp = SUM(damage_amp_debuffs) / 100
final_damage = raw_damage × (1 + damage_amp)
```

Debuff types tracked:
- `DAMAGE_AMP`: From `DamageReceivedIncrease` property
- `SPIRIT_AMP_STACK`: Escalating Exposure stacks (capped at `max_stacks`)

---

## Status Effects

### Buffs (Positive)

| Effect         | Description                                        |
|----------------|----------------------------------------------------|
| Barrier        | Temporary damage absorption shield                 |
| Fire Rate      | Increased attack speed                             |
| Health Regen   | Increased health regeneration                      |
| Invincibility  | Immune to all damage                               |
| Lifesteal      | Heal on damage dealt                               |
| Move Speed     | Increased movement speed                           |
| Resistance     | Increased damage resistance                        |
| Spirit Power   | Increased spirit power                             |
| Stealth        | Invisible to enemies                               |
| Unstoppable    | Immune to crowd control (including parry stun)     |
| Weapon Damage  | Increased weapon damage                            |

### Debuffs (Negative)

| Effect              | Description                                     |
|---------------------|-------------------------------------------------|
| Bleed               | Damage over time (physical)                     |
| Burn                | Damage over time (spirit)                       |
| Curse               | Various negative effects                        |
| Damage Output Reduction | Reduced damage dealt                        |
| Disarm              | Cannot use weapon                               |
| Displace            | Forced movement (knockback, pull)               |
| Healing Reduction   | Reduced healing/regen effectiveness             |
| Immobilized         | Cannot move                                     |
| Movement Silence    | Cannot dash or use movement abilities            |
| Movement Slow       | Reduced movement speed                          |
| Silence             | Cannot use abilities                            |
| Sleep               | Incapacitated until damaged                     |
| Stun                | Cannot take any action                          |

### Hero-Specific Effects

| Effect          | Hero           | Description                          |
|-----------------|----------------|--------------------------------------|
| Affliction      | Infernus       | Burn damage stacking                 |
| Eternal Night   | Celeste        | Darkness debuff                      |
| Fixation        | Haze           | Stacking bullet damage bonus         |
| Hotel Guest     | The Doorman    | Trapped/banished state               |
| Lethal Venom    | Vyper          | Stacking poison                      |
| Malice          | Shiv           | Bleed/damage tracking                |
| Petrified       | Viscous        | Stone form CC                        |
| Rabbit Hex      | —              | Transformed into rabbit (item)       |
| Tether          | Ivy            | Linked to ally                       |
| Wrecked         | Wraith         | Debuff state                         |

### Counters to Status Effects

| Counter           | Effect                                          |
|-------------------|-------------------------------------------------|
| Purge             | Removes debuffs from target                     |
| Debuff Resistance | Stat that reduces duration of debuffs            |
| Invincibility     | Prevents all debuffs while active                |
| Unstoppable       | Prevents CC (stun, silence, immobilize, etc.)    |

## Simulation Debuff Tracking

The codebase tracks debuffs by **mechanic type** (not by item name):

| Debuff Type         | Pool Behavior  | Sources                        |
|---------------------|---------------|--------------------------------|
| SPIRIT_RESIST_SHRED | Additive pool | Decay, spirit shred items      |
| BULLET_RESIST_SHRED | Additive pool | Armor Piercing Rounds          |
| SPIRIT_AMP_STACK    | Stacking      | Escalating Exposure            |
| FIRE_RATE_SLOW      | Additive pool | Slowing items                  |
| MOVE_SPEED_SLOW     | Additive pool | Movement slow items            |
| HEAL_REDUCTION      | Additive pool | Toxic Bullets, healing cut items|
| DAMAGE_AMP          | Additive pool | Crippling Headshot, Soulshredder|

Each debuff instance has:
- Source identifier
- Value (percentage)
- Expiry time
- Optional: max_stacks, stack_count
