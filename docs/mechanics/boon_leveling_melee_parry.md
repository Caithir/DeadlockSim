# Boon/Leveling System & Melee/Parry Mechanics

> Source: https://deadlock.wiki — Last verified: March 2026

---

## Boon System

### Overview
- **Max boons**: 35
- Boons are earned by accumulating **Souls** (the game's currency/XP)
- Each boon grants hero-specific stat increases

### Soul Thresholds per Boon

| Boon | Souls Required | Boon | Souls Required |
|------|---------------|------|---------------|
| 1    | 600           | 19   | 17,600        |
| 2    | 900           | 20   | 19,200        |
| 3    | 1,200         | 21   | 20,800        |
| 4    | 1,500         | 22   | 22,400        |
| 5    | 1,800         | 23   | 24,000        |
| 6    | 2,100         | 24   | 25,600        |
| 7    | 2,400         | 25   | 27,200        |
| 8    | 2,700         | 26   | 28,800        |
| 9    | 3,200         | 27   | 30,400        |
| 10   | 3,600         | 28   | 32,000        |
| 11   | 4,800         | 29   | 33,600        |
| 12   | 6,000         | 30   | 35,200        |
| 13   | 7,200         | 31   | 38,400        |
| 14   | 8,400         | 32   | 41,600        |
| 15   | 10,400        | 33   | 44,800        |
| 16   | 12,400        | 34   | 48,000        |
| 17   | 14,400        | 35   | 49,600        |
| 18   | 16,000        |      |               |

### Boon Rewards (Per Boon)

Each boon grants (hero-specific values):
- **Base Bullet Damage increase** (`damage_gain` in codebase)
- **Base Health increase** (`hp_gain` in codebase)
- **Base Melee Damage increase** (light + heavy separately)
- **Spirit Power increase** (`spirit_gain` in codebase)

### Ability System

- **Ability unlocks**: Levels 0 (start), 2, 4, 6
- **Ability points**: Granted at boons that don't unlock abilities
- **Ability tiers**: 3 tiers per ability (T1, T2, T3)
  - T1 cost: 1 ability point
  - T2 cost: 2 ability points
  - T3 cost: 5 ability points
- **Ultimate**: Unlockable at 3,600 souls

---

## Melee Attack Mechanics

### Overview
- Every hero can perform **light** and **heavy** melee attacks
- Light melee: Quick attack (press melee key)
- Heavy melee: Charged attack with lunge (hold melee key)
- Melee damage scales with **Boons** and **Items**
- Weapon Damage % items scale melee at **50% rate**

### Melee Cycle Times

| Type  | Cooldown (Hit) | Cooldown (Miss) |
|-------|---------------|-----------------|
| Light | ~instant      | ~instant        |
| Heavy | 1.0s          | 1.3s            |

> **⚠ DISCREPANCY**: Codebase uses fixed cycle times: Light=0.6s, Heavy=1.1s.
> Wiki says heavy melee cooldown is 1.0s (hit) / 1.3s (miss). The 50% weapon damage
> scaling for melee is also not implemented — code applies 100% of `weapon_damage_bonus`.

### Base Melee Damage (Light)

Most heroes: **50** base light melee, **+1.58** per boon

Exceptions:
| Hero       | Base Light | Per Boon | Max (35) |
|------------|-----------|----------|----------|
| Abrams     | 50        | +1.74    | 111      |
| Bebop      | 63        | +1.58    | 118      |
| Calico     | 63        | +1.58    | 118      |
| Drifter    | 51.5      | +1.58    | 107      |
| Paige      | 42        | +1.2     | 84       |
| Pocket     | 60        | +1.58    | 115      |
| Rem        | 58        | +1.58    | 113      |
| Venator    | 50        | +1.7     | 110      |
| Viscous    | 63        | +1.58    | 118      |
| Yamato     | 55        | +1.58    | 110      |

### Base Melee Damage (Heavy)

Most heroes: **116** base heavy melee, **+3.67** per boon

Exceptions:
| Hero       | Base Heavy | Per Boon | Max (35) |
|------------|-----------|----------|----------|
| Abrams     | 116       | +4.03    | 257      |
| Apollo     | 116       | +2.91    | 218      |
| Bebop      | 116       | +2.91    | 218      |
| Billy      | 116       | +3.67    | 244      |
| Calico     | 116       | +2.91    | 218      |
| Drifter    | 120       | +3.68    | 249      |
| Paige      | 120       | +3.43    | 240      |
| Pocket     | 116       | +3.05    | 223      |
| Rem        | 116       | +3.16    | 227      |
| Venator    | 125       | +4.25    | 274      |
| Viscous    | 116       | +2.91    | 218      |
| Yamato     | 128       | +3.68    | 257      |

### Melee Damage Formula

```
Light Melee = (Base Light + Boons × Light Gain) × (1 + 0.5 × Weapon Damage%)
Heavy Melee = (Base Heavy + Boons × Heavy Gain) × (1 + 0.5 × Weapon Damage%)
```

> **Key**: Weapon Damage % only applies at **50%** effectiveness to melee.

### Melee Bonus Items

| Item            | Cost   | Category  | Bonus Melee % |
|-----------------|--------|-----------|---------------|
| Melee Lifesteal | 800    | Vitality  | +12%          |
| Melee Charge    | 1,600  | Weapon    | +10% (+25% Heavy) |
| Lifestrike      | 3,200  | Vitality  | +16%          |
| Spirit Snatch   | 3,200  | Spirit    | +7%           |
| Crushing Fists  | 6,400  | Weapon    | +20% (+25% Heavy) |
| Colossus        | 6,400  | Vitality  | +30%          |
| Runed Gauntlets | 9,999  | Weapon    | +30%          |

### Melee Interactions
- Melee attacks interrupt reloading
- Light melee freezes reload timer instantly
- Heavy melee freezes reload timer on lunge start
- Reloading resumes after melee animation completes
- Melee on climbing player: 80% slow → 20% over 2s
- Melee on Soul Urn carrier: forces urn drop
- Sinner's Sacrifice: 80 retaliation damage on melee hit

### Melee-Scaling Abilities

Some abilities scale with light melee damage: `light_melee × melee_scaling`

| Hero       | Ability                | Light Melee Scaling |
|------------|------------------------|---------------------|
| Bebop      | Exploding Uppercut     | ×1.0                |
| Billy      | Bashdown               | ×1.1                |
| Calico     | Leaping Slash          | ×1.5                |
| Drifter    | Rend                   | ×1.2                |
| Silver     | Boot Kick              | ×0.9                |
| Silver (T) | Go For The Throat      | ×1.5                |
| Silver (T) | Mauling Leap           | ×1.9                |
| Viscous    | Puddle Punch           | ×1.1                |

Note: Paige's Heavy Melee has spirit scaling (×0.3 Spirit Power coefficient).

---

## Parry Mechanics

### Overview
- Default key: `F`
- Parry animation: **1.0 second**
- Active parry window: First **0.75 seconds**
- Post-parry recovery: **0.3 seconds** (cannot act)
- Failed parry cooldown: **4.5 seconds**

### On Successful Parry
1. **Fully absorbs** the incoming melee attack (no damage taken)
2. **Stuns** the attacker for **2.75 seconds** (cannot be reduced by Debuff Resistance)
3. Attacker takes **+25% damage from ALL sources** for 2.75s
4. Can hold parry key to parry multiple heroes
5. Cooldown refunded on success

### Parry Interactions
- **Unstoppable** prevents parry stun
- **Debuff Resist** does NOT reduce parry stun duration
- Can parry Troopers (blocks damage, no stun)
- Can parry Guardians (blocks damage, prevents their attacks briefly)
- Cannot parry Walkers or most abilities (exception: Viscous Puddle Punch)

### Parry-Enhancing Items
- **Counterspell**: Additional effects on parry
- **Rebuttal**: Additional effects + reduces parry cooldown to **2.5 seconds**

### Heavy Melee Cancel
- Technique to cancel heavy melee with Active Items or Abilities
- Used to bait enemy parries
