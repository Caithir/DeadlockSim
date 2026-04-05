# Health & Survivability Mechanics

> Source: https://deadlock.wiki — Last verified: March 2026

## Max HP Formula

```
Max HP = (Base HP + Boons × HP per Boon) × (1 + Vitality Bonuses%) + Bonus HP
```

- **Base HP**: Hero-specific starting health (see Hero Attributes Table)
- **HP per Boon**: Hero-specific health gained per boon level
- **Vitality Bonuses%**: Percentage bonus from vitality shop tier investment
- **Bonus HP**: Flat HP from items (e.g., Extra Health, Spirit Armor, etc.)

### Notable Modifier
- **Glass Cannon**: -15% Max Health

## Vitality Shop Tier Bonuses (Max Health %)

Investing souls in the **Vitality** item category grants cumulative bonus Max Health:

| Souls Invested | Max Health Increase |
|----------------|---------------------|
| 800            | +8%                 |
| 1,600          | +10%                |
| 2,400          | +13%                |
| 3,200          | +17%                |
| 4,800          | +22%                |
| 7,200          | +27%                |
| 9,600          | +32%                |
| 16,000         | +36%                |
| 22,400         | +40%                |
| 28,800         | +44%*               |

> *Note: Some wiki sources list 28,800 as +56%. Needs in-game verification.

## Hero Base Health (with Boon Scaling)

Values from the wiki Hero Attributes Table. Format: Base HP | +HP/Boon | HP at 35 Boons.

All hero base HP and per-boon gains are loaded from the API via `data.py:load_heroes()` fields:
- `base_hp`: Starting health
- `hp_gain`: Health gained per boon (parsed from `EMaxHealth` or `MODIFIER_VALUE_BASE_HEALTH_FROM_LEVEL`)

## Health Regen

- Heroes have base health regen (hero-specific)
- Regen ticks periodically
- Healing reduction debuffs reduce regen effectiveness:
  ```
  effective_regen = base_regen × (1 - healing_reduction%)
  ```

## Shields

Two types of shields absorb damage before HP:
- **Bullet Shield**: Absorbs bullet damage only
- **Spirit Shield**: Absorbs spirit damage only

Shields are granted by items (e.g., Bullet Armor, Spirit Armor).

## Effective HP Calculation

For combat simulation purposes:
```
Effective HP vs Bullets = (Max HP + Bullet Shield) / (1 - Bullet Resist)
Effective HP vs Spirit  = (Max HP + Spirit Shield) / (1 - Spirit Resist)
```
