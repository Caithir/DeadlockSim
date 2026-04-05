# Spirit Damage Mechanics

> Source: https://deadlock.wiki — Last verified: March 2026

## Spirit Damage Formula

```
Spirit Damage = Base Damage + (Spirit Power × Spirit Scaling Coefficient)
```

- **Base Damage**: Ability's innate damage value (unaffected by Spirit Power)
- **Spirit Power**: Total spirit power from boons + items + shop tier bonuses
- **Spirit Scaling Coefficient**: Per-ability multiplier (shown in tooltips as e.g., "×0.8")

### Full Damage Pipeline
```
1. raw_damage = base_damage + (spirit_power × coefficient)
2. amplified = raw_damage × (1 + spirit_amp%)
3. damage_amped = amplified × (1 + damage_amp%)
4. final = damage_amped × (1 - spirit_resist%)
```

Spirit amp and damage amp are **separate multiplicative layers**, both applied before resist.

## Spirit Power Sources

### Per-Boon Spirit Gain
- Most heroes: **+1.1** Spirit Power per boon
- Notable exceptions:
  - Haze: +0.5
  - Ivy: +1.2
  - Kelvin: Lower than standard
  - Grey Talon: Spirit Power also increases base bullet damage (unique mechanic)
  - Haze: Spirit Power also increases ammo (unique mechanic)

Spirit gain per boon is loaded from API via `spirit_gain` field (parsed from `EAbilityPoint` or `MODIFIER_VALUE_TECH_POWER`).

### Spirit Shop Tier Bonuses

Investing souls in the **Spirit** item category grants cumulative Spirit Power:

| Souls Invested | Spirit Power Increase |
|----------------|----------------------|
| 800            | +7                   |
| 1,600          | +11                  |
| 2,400          | +15                  |
| 3,200          | +19                  |
| 4,800          | +25                  |
| 7,200          | +32                  |
| 9,600          | +44                  |
| 16,000         | +56                  |
| 22,400         | +69                  |
| 28,800         | +81*                 |

> *Note: Some wiki sources list 28,800 as +100. Needs in-game verification.
> Codebase values shown above match `_SHOP_TIER_DATA` in `data.py`.

## Spirit Amplification (Spirit Amp)

Spirit Amp is a percentage bonus applied to ALL spirit damage dealt. Sources stack **additively**:

```
Total Spirit Amp = Base Spirit Amp + Item Spirit Amp + Ability Spirit Amp + Escalating Exposure Stacks
```

### Key Sources
- **Escalating Exposure**: +4.5% spirit amp per stack (max 5 stacks = +22.5%)
- Various spirit items provide flat spirit amp %
- Some hero abilities grant temporary spirit amp

### Escalating Exposure Mechanics
- Applies on spirit damage hit
- Stacks up to 5 times on the target
- Each stack adds +4.5% spirit amp
- Has proc cooldown between applications
- Stacks have individual durations

## Spirit DPS Calculation

### Instant Abilities
```
effective_cooldown = base_cooldown × (1 - cooldown_reduction)
spirit_dps = final_damage / effective_cooldown
```

### DoT Abilities (Damage over Time)
```
total_dot_damage = final_damage  (applied over duration)
spirit_dps = total_dot_damage / duration
```

### Cooldown Reduction
- Fraction from 0 to 1, applied **multiplicatively**
- Minimum cooldown after CDR: 0.1s (engine) or 0.5s (active items)

## Spirit Resist Shred

Shred reduces target's spirit resist, increasing spirit damage taken:

```
effective_resist = base_spirit_resist × (1 - total_shred)
```

Shred from multiple sources stacks **additively** in the simulation, clamped to [0, 1].

## Item Spirit Damage

Items with spirit damage scale similarly:
```
scaled_damage = base_item_damage + (spirit_scaling × current_spirit_power)
final = scaled_damage × (1 + spirit_amp)
```

Item damage types:
- **Proc-on-hit**: Triggers on bullet hit with proc chance and cooldown
- **Pulse passive**: Auto-fires on cooldown (e.g., Torment Pulse)
- **DoT active**: User-activated, applies damage over duration
- **Buildup**: Accumulates per shot, triggers effect at 100% (e.g., Toxic Bullets)
