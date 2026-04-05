# Damage Resistance Mechanics

> Source: https://deadlock.wiki — Last verified: March 2026

## Resistance Types

Three separate resistance stats:
1. **Bullet Resist** — reduces bullet (weapon) damage
2. **Spirit Resist** — reduces spirit (ability) damage
3. **Melee Resist** — reduces melee attack damage (separate from bullet resist)

## Resistance Formula

```
Damage Taken = Damage × (1 - Effective Resist%)
```

## Resistance Stacking

Multiple resistance sources stack **multiplicatively** (not additively):

```
Total Resist = 1 - (1 - R1) × (1 - R2) × (1 - R3) × ...
```

Example: 20% + 30% resist = 1 - (0.8 × 0.7) = 1 - 0.56 = **44%** total resist (not 50%).

**Negative resist** = damage amplification (target takes MORE damage).

## Resist Reduction (Shred)

Shred reduces the target's resistance, calculated separately then subtracted:

```
Effective Resist = Base Resist - Resist Reduction
```

> **⚠ DISCREPANCY**: The codebase applies shred as:
> `effective_resist = base_resist × (1 - shred)` (multiplicative)
> Need to verify: does wiki mean additive subtraction or multiplicative reduction?

## Hero Base Resistances

Most heroes start with **0%** bullet and spirit resist. Notable exceptions:

### Bullet Resist
| Hero     | Base Resist | Per Boon |
|----------|-------------|----------|
| Lash     | 10%         | —        |

### Spirit Resist
| Hero     | Base Resist | Per Boon   |
|----------|-------------|------------|
| Bebop    | 0%          | +0.3/boon  |
| Dynamo   | 0%          | +0.625/boon|
| Kelvin   | 0%          | +0.625/boon|
| McGinnis | 0%          | +0.625/boon|

### Negative Resist (Damage Vulnerability)
| Hero    | Resist     | Notes       |
|---------|------------|-------------|
| Pocket  | -15%       | Takes more spirit damage |
| Celeste | -8%        | Spirit vulnerability |
| Rem     | -5%        | Melee vulnerability |

### Melee Resist
| Hero       | Base Melee Resist |
|------------|-------------------|
| Mo & Krill | 20%               |
| Seven      | 35%               |

## Bullet Resist Items

| Item                    | Cost   | Category | Resist   |
|-------------------------|--------|----------|----------|
| Close Quarters          | 800    | Weapon   | +20% (situational) |
| Point Blank             | 3,200  | Weapon   | +30% (situational) |
| Bullet Armor            | 800    | Vitality | Bullet Resist |
| Battle Vest             | 1,600  | Vitality | Bullet Resist |
| Spirit Armor            | 800    | Vitality | Spirit Resist |
| Improved Spirit Armor   | 1,600  | Vitality | Spirit Resist |

## Spirit Resist Items

(See item shop for full list — items with `BonusTechArmorDamageReduction` property)

## Resist Reduction Items (Shred)

### Bullet Resist Reduction
- **Armor Piercing Rounds** (6,400, Weapon): Reduces target bullet resist

### Spirit Resist Reduction
- **Decay** (Spirit): Reduces target spirit resist
- **Mystic Vulnerability**: Increases spirit damage taken (functions as shred)

## Melee Resist Items

| Item           | Cost   | Category | Melee Resist |
|----------------|--------|----------|--------------|
| Close Quarters | 800    | Weapon   | +20%         |
| Point Blank    | 3,200  | Weapon   | +30%         |
| Runed Gauntlets| 9,999  | Weapon   | +50%         |
| Rebuttal       | 800    | Vitality | +18%         |
| Juggernaut     | 6,400  | Vitality | +25%         |
| Torment Pulse  | 3,200  | Spirit   | +15%         |

## Simulation Implementation Notes

In the codebase simulation (`simulation.py`):
- Bullet resist shred and spirit resist shred are tracked as **debuff pools**
- Multiple shred sources stack **additively** within the pool
- Total shred is clamped to [0, 1] before application
- Effective resist = `base_resist × (1 - total_shred)`
- Debuffs have individual expiration timers
