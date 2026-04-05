# Weapon Damage Mechanics

> Source: https://deadlock.wiki — Last verified: March 2026

## Final Damage Formula

```
Final Damage = [(Base Damage × Weapon Damage Multiplier) + Flat Bonus] × Falloff × Resistances × Crit Multiplier
```

### Components

1. **Base Damage**: Hero's base bullet damage, scales with boons
   ```
   Base Damage = Base Bullet Damage + (Damage Gain × Boons)
   ```

2. **Weapon Damage Multiplier**: Percentage bonuses from items + shop tier investment (additive with each other)
   ```
   Multiplier = 1 + Shop Bonuses + Item Bonuses + Statue Bonuses
   ```

3. **Flat Bonus**: Added AFTER the percentage multiplier (from specific hero abilities)
   - NOT multiplied by Weapon Damage %
   - IS affected by Falloff, Bullet Resist, and Crit Multiplier
   - Sources: Grey Talon Rain of Arrows (+4), Haze Fixation (+0.2/stack), Lash Grapple T2 (+6), Pocket Flying Cloak T3 (+7), Yamato Flying Slash T3 (+6), Abrams Shoulder Charge T3 (+1.5)

4. **Falloff**: Linear reduction from 100% to 10% based on distance within hero-specific falloff range
   - Visual indicator on enemy health bar (dot color: Red=10-20%, Orange=20-35%, Yellow=35-75%, Transparent=75-100%)

5. **Resistances**: Target's Bullet Resist (see damage_resistance.md)

6. **Crit Multiplier**: Headshot damage bonus
   ```
   Crit Multiplier = 1 + 0.65 × Crit Bonus Scale × Crit Resist
   ```
   - Base weakpoint multiplier: **1.65x** (for most heroes)
   - Graves **cannot** deal critical damage (lock-on weapon)

## Crit Bonus Scale Exceptions

Heroes with reduced crit effectiveness:

| Hero         | Crit Bonus Scale Modifier |
|--------------|--------------------------|
| Billy        | -20%                     |
| Celeste      | -25%                     |
| The Doorman  | -25%                     |
| Drifter      | -45%                     |
| Kelvin       | -25%                     |
| Rem          | -20%                     |
| Vyper        | -30%                     |

## Weapon Damage Shop Tier Bonuses

Investing souls in the **Weapon** item category grants cumulative Weapon Damage %:

| Souls Invested | Weapon Damage Increase |
|----------------|------------------------|
| 800            | +7%                    |
| 1,600          | +9%                    |
| 2,400          | +13%                   |
| 3,200          | +20%                   |
| 4,800          | +49%                   |
| 7,200          | +60%                   |
| 9,600          | +80%                   |
| 16,000         | +95%                   |
| 22,400         | +115%                  |
| 28,800         | +135%                  |

> **⚠ DISCREPANCY**: Codebase `_SHOP_TIER_DATA` has different values from 4800+:
> Code: 29, 40, 60, 75, 95, 115 vs Wiki: 49, 60, 80, 95, 115, 135.
> Difference is consistently +20% in wiki from 4800 onward. Needs in-game verification.

## Spreadshot Heroes

Heroes whose weapons fire multiple bullets per shot:

| Hero       | Bullets/Shot | Pattern    |
|------------|-------------|------------|
| Abrams     | 9           | Semi-Fixed |
| Calico     | ?           | Fixed      |
| Mo & Krill | 4           | Semi-Fixed |
| Shiv       | 6-12        | Random     |
| Yamato     | 5           | Semi-Fixed |
| Pocket     | 7           | Fixed      |

All calculation rules apply to every individual bullet (pellet).

## Piercing Shots

- **Paige**: Shots pierce enemies (hit multiple targets), disappear on map surfaces. **Cannot deal headshot damage.**
- **The Doorman**: Shots also pierce enemies. CAN deal headshot damage. Half damage to all enemies after the first.

## DPS Formulas

### Burst DPS (no reload)
```
Damage Per Bullet = Base Damage × Pellets × Weapon Damage Multiplier
Bullets Per Second = Fire Rate × (1 + Fire Rate Bonus)
Burst DPS = Damage Per Bullet × Bullets Per Second
```

### Sustained DPS (with reloads)
```
Magazine Size = FLOOR(Base Ammo × (1 + Ammo Increase%)) + Ammo Flat
Damage Per Magazine = Damage Per Bullet × Magazine Size
Magdump Time = Magazine Size / Bullets Per Second
Cycle Time = Magdump Time + Reload Duration
Sustained DPS = Damage Per Magazine / Cycle Time
```

### Realistic DPS (with accuracy + headshots)
```
Realistic DPS = DPS × Accuracy + DPS × Accuracy × Headshot Rate × (Headshot Multiplier - 1)
```

## Increased Bullet Damage (Target Debuffs)

Some abilities make targets take MORE bullet damage from the caster:
- Bebop Grapple Arm T1: +20% weapon damage vs hooked enemies for 6s
- Dynamo Kinetic Pulse T2: +30% weapon damage to hit enemies for 8s
- Warden Binding Word T3: +20% bullet damage to trapped heroes for 6s

## Golden Statues

Permanent Weapon Damage % bonuses based on game time:
- Before 10 minutes: +3%
- Before 30 minutes: +4%
- After 30 minutes: +7%

## Conditional Item Modifiers

- **Headshot Booster**: +45 bonus Weapon Damage on headshots
- **Monster Rounds**: +25% Weapon Damage vs NPCs
- **Berserker**: +7% Weapon Damage per stack when sustaining damage
- **Headhunter**: +75 (×Boon scaling) bonus Weapon Damage on headshots
- **Intensifying Magazine**: Up to +45% Weapon Damage while continuously firing
- **Opening Rounds**: +45% Weapon Damage vs enemies above 50% HP
