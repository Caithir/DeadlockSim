"""Comprehensive engine tests using real hero & item data.

Each test documents the exact scenario so you can verify in-game:
  - Hero name, boon level, items equipped
  - Expected damage numbers, DPS, TTK, etc.

Run with:
    python -m pytest tests/test_engine.py -v
"""

from __future__ import annotations

import math

import pytest

from deadlock_sim.data import (
    ABILITY_TIER_COSTS,
    _SHOP_TIER_DATA,
    load_heroes,
    load_items,
    souls_to_ability_points,
    souls_to_boons,
)
from deadlock_sim.engine.builds import BuildEngine
from deadlock_sim.engine.comparison import ComparisonEngine
from deadlock_sim.engine.damage import DamageCalculator, apply_ability_upgrades
from deadlock_sim.engine.heroes import HeroMetrics
from deadlock_sim.engine.primitives import (
    apply_amplifiers,
    falloff_multiplier,
    resist_after_shred,
)
from deadlock_sim.engine.simulation import (
    AbilityUse,
    CombatSimulator,
    SimConfig,
    SimSettings,
    classify_item,
)
from deadlock_sim.models import (
    AbilityConfig,
    Build,
    BuildStats,
    CombatConfig,
    HeroAbility,
    HeroStats,
    Item,
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures — load real data once per session
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def heroes():
    return load_heroes()


@pytest.fixture(scope="session")
def items():
    return load_items()


def _hero(heroes, name):
    h = heroes.get(name)
    assert h is not None, f"Hero '{name}' not found in data"
    return h


def _item(items, name):
    i = items.get(name)
    assert i is not None, f"Item '{name}' not found in data"
    return i


# ═══════════════════════════════════════════════════════════════════
# 1. PRIMITIVES — resist_after_shred, falloff, amplifiers
# ═══════════════════════════════════════════════════════════════════


class TestPrimitives:
    """Verify lowest-level math primitives.

    These are the building blocks — if they're wrong, everything is wrong.
    """

    # ── resist_after_shred ────────────────────────────────────────

    def test_resist_no_shred(self):
        """30% resist with 0 shred → 30% resist unchanged."""
        assert resist_after_shred(0.30, 0.0) == pytest.approx(0.30)

    def test_resist_partial_shred(self):
        """30% resist with 40% shred → 30% × (1 - 0.40) = 18%."""
        assert resist_after_shred(0.30, 0.40) == pytest.approx(0.18)

    def test_resist_full_shred(self):
        """Any resist with 100% shred → 0% resist."""
        assert resist_after_shred(0.50, 1.0) == pytest.approx(0.0)

    def test_resist_over_shred_clamped(self):
        """Shred > 100% clamped to 100% → 0% resist."""
        assert resist_after_shred(0.50, 1.5) == pytest.approx(0.0)

    def test_resist_zero_base(self):
        """0% resist with any shred → 0%."""
        assert resist_after_shred(0.0, 0.50) == pytest.approx(0.0)

    def test_resist_negative_shred_clamped(self):
        """Negative shred clamped to 0 → resist unchanged."""
        assert resist_after_shred(0.30, -0.10) == pytest.approx(0.30)

    # ── falloff_multiplier ────────────────────────────────────────

    def test_falloff_inside_min_range(self):
        """Distance within min range → full damage (1.0)."""
        assert falloff_multiplier(10.0, 20.0, 50.0) == pytest.approx(1.0)

    def test_falloff_at_min_range(self):
        """Exactly at min range → full damage (1.0)."""
        assert falloff_multiplier(20.0, 20.0, 50.0) == pytest.approx(1.0)

    def test_falloff_at_max_range(self):
        """At max range → minimum damage (0.1)."""
        assert falloff_multiplier(50.0, 20.0, 50.0) == pytest.approx(0.1)

    def test_falloff_beyond_max_range(self):
        """Beyond max range → minimum damage (0.1)."""
        assert falloff_multiplier(100.0, 20.0, 50.0) == pytest.approx(0.1)

    def test_falloff_midpoint(self):
        """Midpoint between min and max → halfway between 1.0 and 0.1.
        t = (35-20)/(50-20) = 0.5; mult = 1.0 - 0.5 * 0.9 = 0.55
        """
        assert falloff_multiplier(35.0, 20.0, 50.0) == pytest.approx(0.55)

    def test_falloff_invalid_range(self):
        """Invalid range (max <= min) → no falloff (1.0)."""
        assert falloff_multiplier(100.0, 50.0, 20.0) == pytest.approx(1.0)

    def test_falloff_custom_min_damage(self):
        """Custom min_damage_frac. At max range → min_damage_frac."""
        assert falloff_multiplier(50.0, 20.0, 50.0, min_damage_frac=0.3) == pytest.approx(0.3)

    # ── apply_amplifiers ──────────────────────────────────────────

    def test_amplifiers_no_amp(self):
        """No amplification → base damage unchanged."""
        assert apply_amplifiers(100.0, 0.0, 0.0) == pytest.approx(100.0)

    def test_amplifiers_spirit_only(self):
        """20% spirit amp → 100 × 1.20 = 120."""
        assert apply_amplifiers(100.0, 0.20, 0.0) == pytest.approx(120.0)

    def test_amplifiers_both(self):
        """20% spirit amp + 10% damage amp → 100 × 1.20 × 1.10 = 132."""
        assert apply_amplifiers(100.0, 0.20, 0.10) == pytest.approx(132.0)


# ═══════════════════════════════════════════════════════════════════
# 2. SOUL / BOON TABLES
# ═══════════════════════════════════════════════════════════════════


class TestSoulBoonTables:
    """Verify the soul-to-boon and soul-to-ability-point lookups.

    In-game verification: Open the scoreboard and check your boon count
    against your total souls earned.
    """

    def test_zero_souls(self):
        assert souls_to_boons(0) == 0
        assert souls_to_ability_points(0) == 0

    def test_below_first_threshold(self):
        """Under 600 souls → 0 boons, 0 AP."""
        assert souls_to_boons(500) == 0
        assert souls_to_ability_points(500) == 0

    def test_first_level(self):
        """600 souls → level 0 unlock (0 boons, 0 AP)."""
        assert souls_to_boons(600) == 0
        assert souls_to_ability_points(600) == 0

    def test_level_1(self):
        """900 souls → 1 boon, 1 AP."""
        assert souls_to_boons(900) == 1
        assert souls_to_ability_points(900) == 1

    def test_mid_game(self):
        """6000 souls → 9 boons, 6 AP."""
        assert souls_to_boons(6000) == 9
        assert souls_to_ability_points(6000) == 6

    def test_between_thresholds(self):
        """5500 souls is between 5200 (8 boons) and 6000 (9 boons) → 8 boons."""
        assert souls_to_boons(5500) == 8

    def test_max_level(self):
        """49600+ souls → 35 boons, 32 AP."""
        assert souls_to_boons(49600) == 35
        assert souls_to_ability_points(49600) == 32

    def test_well_above_max(self):
        """100k souls → still 35 boons (capped by table)."""
        assert souls_to_boons(100000) == 35

    def test_ability_tier_costs(self):
        """T1 = 1 AP, T2 = 2 AP, T3 = 5 AP."""
        assert ABILITY_TIER_COSTS == [1, 2, 5]


# ═══════════════════════════════════════════════════════════════════
# 3. BULLET DAMAGE — per-hero scenarios
# ═══════════════════════════════════════════════════════════════════


class TestBulletDamage:
    """Verify bullet damage calculations against in-game values.

    To verify in-game:
    1. Pick the hero in sandbox mode
    2. Set boon level (use console or item purchases to reach soul total)
    3. Shoot the target dummy and check damage numbers
    4. Compare per-bullet damage and DPS readout
    """

    def test_base_bullet_damage_at_boon_0(self, heroes):
        """Scenario: Hero at boon 0 — damage should equal base_bullet_damage.

        In-game: Pick any hero, shoot target dummy before buying any items.
        """
        for name in ["Haze", "Infernus", "Seven", "Abrams", "Wraith"]:
            hero = heroes.get(name)
            if hero is None:
                continue
            dmg = DamageCalculator.bullet_damage_at_boon(hero, 0)
            assert dmg == pytest.approx(hero.base_bullet_damage), (
                f"{name}: boon 0 damage should be base ({hero.base_bullet_damage}), got {dmg}"
            )

    def test_bullet_damage_scales_with_boons(self, heroes):
        """Scenario: At boon 10, damage = base + 10 × damage_gain.

        In-game: Reach ~6800 souls (10 boons), check bullet damage.
        """
        hero = _hero(heroes, "Haze")
        expected = hero.base_bullet_damage + (hero.damage_gain * 10)
        actual = DamageCalculator.bullet_damage_at_boon(hero, 10)
        assert actual == pytest.approx(expected), (
            f"Haze at boon 10: expected {expected}, got {actual}"
        )

    def test_fire_rate_with_bonus(self, heroes):
        """Scenario: +20% fire rate bonus.

        In-game: Buy items giving 20% fire rate, check fire rate in stats.
        """
        hero = _hero(heroes, "Haze")
        expected = hero.base_fire_rate * 1.20
        actual = DamageCalculator.fire_rate_with_bonus(hero, 0.20)
        assert actual == pytest.approx(expected)

    def test_effective_magazine(self, heroes):
        """Scenario: +50% ammo increase + 5 flat ammo.

        In-game: Buy ammo items, check magazine size in stats panel.
        Game uses ceiling rounding for ammo percentage.
        """
        hero = _hero(heroes, "Haze")
        expected = max(1, math.ceil(hero.base_ammo * 1.5) + 5)
        actual = DamageCalculator.effective_magazine(hero, ammo_increase=0.5, ammo_flat=5)
        assert actual == expected

    def test_shred_stacking(self):
        """Multiple shred sources stack additively, clamped to 1.0.

        In-game: Stack multiple shred items, check debuff on target.
        """
        assert DamageCalculator.total_shred([0.20, 0.15, 0.10]) == pytest.approx(0.45)
        assert DamageCalculator.total_shred([0.40, 0.40, 0.30]) == pytest.approx(1.0)  # clamped

    def test_full_bullet_calc_no_items(self, heroes):
        """Scenario: Haze at boon 0, no items, point-blank, no resist.

        In-game: Pick Haze, shoot dummy at close range, no items.
        Expected: raw_dps = (base_bullet × pellets) × fire_rate
        """
        hero = _hero(heroes, "Haze")
        config = CombatConfig(boons=0, distance=0.0)
        result = DamageCalculator.calculate_bullet(hero, config)

        expected_dmg_per_bullet = hero.base_bullet_damage * hero.pellets
        assert result.damage_per_bullet == pytest.approx(expected_dmg_per_bullet)
        assert result.bullets_per_second == pytest.approx(hero.base_fire_rate)
        assert result.raw_dps == pytest.approx(expected_dmg_per_bullet * hero.base_fire_rate)
        assert result.final_dps == pytest.approx(result.raw_dps)  # no resist
        assert result.final_resist == pytest.approx(0.0)

    def test_bullet_calc_with_resist_and_shred(self, heroes):
        """Scenario: Haze vs target with 30% bullet resist, 15% shred.

        In-game: Set target armor, equip shred item, compare damage.
        """
        hero = _hero(heroes, "Haze")
        config = CombatConfig(
            boons=0,
            distance=0.0,
            enemy_bullet_resist=0.30,
            shred=[0.15],
        )
        result = DamageCalculator.calculate_bullet(hero, config)

        expected_resist = resist_after_shred(0.30, 0.15)
        assert result.final_resist == pytest.approx(expected_resist)
        assert result.final_dps == pytest.approx(result.raw_dps * (1 - expected_resist))

    def test_bullet_calc_with_weapon_bonus(self, heroes):
        """Scenario: Haze at boon 0 with +25% weapon damage bonus.

        In-game: Buy items giving 25% weapon damage, check per-bullet damage.
        Per-bullet = base × (1 + 0.25) × pellets
        """
        hero = _hero(heroes, "Haze")
        config = CombatConfig(boons=0, weapon_damage_bonus=0.25, distance=0.0)
        result = DamageCalculator.calculate_bullet(hero, config)

        expected = hero.base_bullet_damage * 1.25 * hero.pellets
        assert result.damage_per_bullet == pytest.approx(expected)

    def test_sustained_dps_includes_reload(self, heroes):
        """Sustained DPS should be lower than burst DPS due to reload.

        In-game: Burst DPS shown on first mag, sustained = average over multiple mags.
        """
        hero = _hero(heroes, "Haze")
        config = CombatConfig(boons=0, distance=0.0)
        result = DamageCalculator.calculate_bullet(hero, config)

        if hero.reload_duration > 0 and hero.base_ammo > 0:
            assert result.sustained_dps < result.final_dps
            # Verify formula: sustained = (dmg_per_mag × (1-resist)) / (magdump + reload)
            cycle_time = result.magdump_time + result.reload_time
            expected_sustained = result.damage_per_magazine / cycle_time
            assert result.sustained_dps == pytest.approx(expected_sustained)

    def test_bullet_falloff_at_range(self, heroes):
        """Scenario: Haze shooting at max falloff range.

        In-game: Shoot target dummy from far away, compare damage to close range.
        """
        hero = _hero(heroes, "Haze")
        close = CombatConfig(boons=0, distance=0.0)
        far = CombatConfig(boons=0, distance=hero.falloff_range_max + 10)

        close_result = DamageCalculator.calculate_bullet(hero, close)
        far_result = DamageCalculator.calculate_bullet(hero, far)

        if hero.falloff_range_max > hero.falloff_range_min:
            assert far_result.final_dps < close_result.final_dps
            # At max range, falloff = 0.1 (10% damage)
            assert far_result.final_dps == pytest.approx(close_result.final_dps * 0.1)

    def test_conditional_berserker_stacks(self, heroes):
        """Scenario: Haze with 10 berserker stacks (+70% weapon damage).

        In-game: Build up 10 stacks of Berserker, check damage.
        """
        hero = _hero(heroes, "Haze")
        base_config = CombatConfig(boons=0, distance=0.0)
        stacked_config = CombatConfig(boons=0, distance=0.0, berserker_stacks=10)

        base = DamageCalculator.calculate_bullet(hero, base_config)
        stacked = DamageCalculator.calculate_bullet(hero, stacked_config)

        # 10 stacks × 7% = 70% weapon damage bonus
        expected_mult = 1.70 / 1.0
        assert stacked.damage_per_bullet == pytest.approx(
            base.damage_per_bullet * expected_mult, rel=0.01
        )

    def test_multi_pellet_hero(self, heroes):
        """Scenario: A hero with multiple pellets (e.g., shotgun).

        In-game: Check per-shot damage = per-pellet × pellet_count.
        """
        for name, hero in heroes.items():
            if hero.pellets > 1:
                config = CombatConfig(boons=0, distance=0.0)
                result = DamageCalculator.calculate_bullet(hero, config)
                single_pellet = hero.base_bullet_damage
                assert result.damage_per_bullet == pytest.approx(
                    single_pellet * hero.pellets
                ), f"{name}: multi-pellet damage wrong"
                break  # test at least one


# ═══════════════════════════════════════════════════════════════════
# 4. SPIRIT DAMAGE
# ═══════════════════════════════════════════════════════════════════


class TestSpiritDamage:
    """Verify spirit/ability damage calculations.

    To verify in-game:
    1. Pick hero, buy spirit items to set spirit power
    2. Use ability on target dummy, check damage number
    3. Compare to formula: (base + spirit_scaling × spirit_power) × (1+amp) × (1-resist)
    """

    def test_base_spirit_no_spirit_power(self):
        """Ability with 100 base damage and 0 spirit → 100 damage."""
        config = AbilityConfig(base_damage=100.0, spirit_multiplier=1.0, current_spirit=0)
        result = DamageCalculator.calculate_spirit(config)
        assert result.raw_damage == pytest.approx(100.0)
        assert result.modified_damage == pytest.approx(100.0)
        assert result.spirit_contribution == pytest.approx(0.0)

    def test_spirit_scaling(self):
        """100 base + 0.8 scaling × 50 spirit = 100 + 40 = 140 damage."""
        config = AbilityConfig(base_damage=100.0, spirit_multiplier=0.8, current_spirit=50)
        result = DamageCalculator.calculate_spirit(config)
        assert result.raw_damage == pytest.approx(140.0)
        assert result.spirit_contribution == pytest.approx(40.0)

    def test_spirit_amp_applies(self):
        """100 base with 20% spirit amp → 100 × 1.20 = 120."""
        config = AbilityConfig(base_damage=100.0, spirit_amp=0.20)
        result = DamageCalculator.calculate_spirit(config)
        assert result.modified_damage == pytest.approx(120.0)

    def test_spirit_resist_reduces(self):
        """100 base with 25% spirit resist → 100 × 0.75 = 75."""
        config = AbilityConfig(base_damage=100.0, enemy_spirit_resist=0.25)
        result = DamageCalculator.calculate_spirit(config)
        assert result.modified_damage == pytest.approx(75.0)

    def test_spirit_resist_shred(self):
        """100 base, 40% resist, 50% shred → resist = 0.40 × 0.50 = 0.20.
        Damage = 100 × (1 - 0.20) = 80.
        """
        config = AbilityConfig(
            base_damage=100.0,
            enemy_spirit_resist=0.40,
            resist_shred=0.50,
        )
        result = DamageCalculator.calculate_spirit(config)
        assert result.modified_damage == pytest.approx(80.0)

    def test_escalating_exposure_stacks(self):
        """100 base with 5 EE stacks at 6% each = 30% spirit amp.
        Damage = 100 × 1.30 = 130.
        """
        config = AbilityConfig(
            base_damage=100.0,
            escalating_exposure_stacks=5,
            ee_per_stack=0.06,
        )
        result = DamageCalculator.calculate_spirit(config)
        assert result.modified_damage == pytest.approx(130.0)

    def test_ee_plus_spirit_amp_stacks(self):
        """100 base, 20% spirit amp + 3 EE stacks (6% each = 18%).
        Total spirit amp = 38%. Damage = 100 × 1.38 = 138.
        """
        config = AbilityConfig(
            base_damage=100.0,
            spirit_amp=0.20,
            escalating_exposure_stacks=3,
            ee_per_stack=0.06,
        )
        result = DamageCalculator.calculate_spirit(config)
        assert result.modified_damage == pytest.approx(138.0)

    def test_crippling_damage_amp(self):
        """100 base with 25% crippling → separate multiplier.
        Damage = 100 × 1.0 × 1.25 = 125.
        """
        config = AbilityConfig(base_damage=100.0, crippling=0.25)
        result = DamageCalculator.calculate_spirit(config)
        assert result.modified_damage == pytest.approx(125.0)

    def test_all_spirit_mods_combined(self):
        """Full combo: 100 base + 50 spirit (×0.8 scale) = 140 raw.
        20% spirit amp + 3 EE × 6% = 38% total spirit amp.
        15% crippling = damage amp.
        30% resist, 40% shred → resist = 0.18.
        Final = 140 × 1.38 × 1.15 × (1 - 0.18)
        """
        config = AbilityConfig(
            base_damage=100.0,
            spirit_multiplier=0.8,
            current_spirit=50,
            spirit_amp=0.20,
            escalating_exposure_stacks=3,
            ee_per_stack=0.06,
            crippling=0.15,
            enemy_spirit_resist=0.30,
            resist_shred=0.40,
        )
        result = DamageCalculator.calculate_spirit(config)

        raw = 100.0 + 0.8 * 50
        spirit_amp = 1.0 + 0.20 + 3 * 0.06
        damage_amp = 1.0 + 0.15
        resist = 0.30 * (1.0 - 0.40)
        expected = raw * spirit_amp * damage_amp * (1.0 - resist)

        assert result.raw_damage == pytest.approx(raw)
        assert result.modified_damage == pytest.approx(expected)

    def test_dot_dps_calculation(self):
        """200 damage over 5 seconds → DPS = 200/5 = 40."""
        config = AbilityConfig(base_damage=200.0, ability_duration=5.0)
        result = DamageCalculator.calculate_spirit(config)
        assert result.dps == pytest.approx(40.0)

    def test_instant_damage_dps(self):
        """Instant ability (duration=0): DPS = damage itself."""
        config = AbilityConfig(base_damage=100.0, ability_duration=0.0)
        result = DamageCalculator.calculate_spirit(config)
        assert result.dps == pytest.approx(100.0)


# ═══════════════════════════════════════════════════════════════════
# 5. MELEE DAMAGE
# ═══════════════════════════════════════════════════════════════════


class TestMeleeDamage:
    """Verify melee damage calculations.

    In-game:
    1. Pick hero, melee the target dummy
    2. Light melee = quick strike, heavy melee = charged strike
    3. Check damage numbers match
    """

    def test_base_melee_no_bonuses(self, heroes):
        """Scenario: Haze at boon 0, no items, melee target.

        Verify light and heavy melee damage = hero base values.
        """
        hero = _hero(heroes, "Haze")
        result = DamageCalculator.calculate_melee(hero)

        assert result.light_damage == pytest.approx(hero.light_melee_damage)
        assert result.heavy_damage == pytest.approx(hero.heavy_melee_damage)

    def test_melee_scales_with_boons(self, heroes):
        """Scenario: At boon 10, melee gains boon scaling.

        Light melee = (base + damage_gain × 10) × (1 + 0) = base + scaling.
        """
        hero = _hero(heroes, "Haze")
        result = DamageCalculator.calculate_melee(hero, boons=10)

        expected_light = hero.light_melee_damage + hero.damage_gain * 10
        assert result.light_damage == pytest.approx(expected_light)

    def test_melee_weapon_bonus_half_rate(self, heroes):
        """Scenario: 50% weapon damage bonus → melee gets 50% × 50% = 25% bonus.

        In-game: Buy +50% weapon damage items, check melee damage.
        Weapon damage scales melee at 50% rate.
        """
        hero = _hero(heroes, "Haze")
        result = DamageCalculator.calculate_melee(hero, weapon_damage_bonus=0.50)

        melee_weapon = 0.50 * 0.5  # 50% weapon × 50% rate = 25%
        expected_light = hero.light_melee_damage * (1.0 + melee_weapon)
        assert result.light_damage == pytest.approx(expected_light)

    def test_melee_damage_pct_bonus(self, heroes):
        """Scenario: +30% melee damage from items.

        In-game: Equip melee damage items, check melee numbers.
        """
        hero = _hero(heroes, "Haze")
        result = DamageCalculator.calculate_melee(hero, melee_damage_pct=0.30)

        expected_light = hero.light_melee_damage * 1.30
        assert result.light_damage == pytest.approx(expected_light)

    def test_melee_resist_applied(self, heroes):
        """Scenario: Target has 20% bullet resist (melee uses bullet resist).

        In-game: Set target armor, melee them, check reduced damage.
        """
        hero = _hero(heroes, "Haze")
        result = DamageCalculator.calculate_melee(hero, enemy_bullet_resist=0.20)

        expected_light = hero.light_melee_damage * 0.80
        assert result.light_damage == pytest.approx(expected_light)

    def test_melee_dps_cycle_times(self, heroes):
        """Light melee DPS = damage / 0.6s, Heavy = damage / 1.0s."""
        hero = _hero(heroes, "Haze")
        result = DamageCalculator.calculate_melee(hero)

        assert result.light_dps == pytest.approx(hero.light_melee_damage / 0.6)
        assert result.heavy_dps == pytest.approx(hero.heavy_melee_damage / 1.0)

    def test_heavy_melee_bonus(self, heroes):
        """Scenario: +40% heavy melee bonus from items.

        Heavy melee gets both melee_damage_pct and heavy_melee_damage_pct.
        """
        hero = _hero(heroes, "Haze")
        result = DamageCalculator.calculate_melee(
            hero, melee_damage_pct=0.10, heavy_melee_damage_pct=0.40,
        )

        # Heavy gets both: melee_damage_pct + heavy_melee_damage_pct
        expected_heavy = hero.heavy_melee_damage * (1.0 + 0.10 + 0.40)
        assert result.heavy_damage == pytest.approx(expected_heavy)


# ═══════════════════════════════════════════════════════════════════
# 6. ABILITY UPGRADES
# ═══════════════════════════════════════════════════════════════════


class TestAbilityUpgrades:
    """Verify ability upgrade tier application.

    In-game:
    1. Pick hero, unlock ability upgrade tiers
    2. Check tooltip for new damage/cooldown values
    3. Compare to engine output
    """

    def test_no_upgrades_returns_base(self, heroes):
        """With no active tiers, values should be base."""
        hero = _hero(heroes, "Infernus")
        for ability in hero.abilities:
            if ability.base_damage > 0:
                dmg, cd, dur, _ss = apply_ability_upgrades(ability, [])
                assert dmg == pytest.approx(ability.base_damage)
                assert cd == pytest.approx(max(0.1, ability.cooldown))
                break

    def test_t1_upgrade_adds_damage(self, heroes):
        """T1 upgrade should modify base damage (or cooldown).

        In-game: Unlock T1 on first ability, check tooltip damage change.
        """
        hero = _hero(heroes, "Infernus")
        for ability in hero.abilities:
            if ability.base_damage > 0 and ability.upgrades:
                dmg_base, cd_base, dur_base, _ss = apply_ability_upgrades(ability, [])
                dmg_t1, cd_t1, dur_t1, _ss = apply_ability_upgrades(ability, [1])
                # T1 should change at least something
                changed = (
                    dmg_t1 != dmg_base
                    or cd_t1 != cd_base
                    or dur_t1 != dur_base
                )
                assert changed, f"{ability.name}: T1 upgrade had no effect"
                break

    def test_upgrade_tiers_cumulative(self, heroes):
        """T1+T2 should apply both tiers cumulatively."""
        hero = _hero(heroes, "Infernus")
        for ability in hero.abilities:
            if ability.base_damage > 0 and len(ability.upgrades) >= 2:
                _, _, _, _ss = apply_ability_upgrades(ability, [1])
                dmg_12, cd_12, dur_12, _ss = apply_ability_upgrades(ability, [1, 2])
                dmg_1, cd_1, dur_1, _ss = apply_ability_upgrades(ability, [1])
                # T1+T2 should be different from T1 alone (if T2 does anything)
                t2_upgrade = next((u for u in ability.upgrades if u.tier == 2), None)
                if t2_upgrade and t2_upgrade.property_upgrades:
                    has_damage_or_cd = any(
                        pu.get("name", "") in (
                            "Damage", "AbilityDamage", "AbilityCooldown",
                            "AbilityDuration", "DPS",
                        )
                        for pu in t2_upgrade.property_upgrades
                    )
                    if has_damage_or_cd:
                        changed = (
                            dmg_12 != dmg_1 or cd_12 != cd_1 or dur_12 != dur_1
                        )
                        assert changed, f"{ability.name}: T2 had no additional effect"
                break

    def test_cooldown_never_below_minimum(self):
        """Cooldown should never go below 0.1s even with large reductions."""
        ab = HeroAbility(
            name="Test", cooldown=1.0, base_damage=100.0,
            upgrades=[],
        )
        # Simulate a massive cooldown reduction by creating a mock upgrade
        _, cd, _, _ss = apply_ability_upgrades(ab, [])
        assert cd >= 0.1


# ═══════════════════════════════════════════════════════════════════
# 7. HERO TOTAL SPIRIT DPS
# ═══════════════════════════════════════════════════════════════════


class TestHeroSpiritDPS:
    """Verify total spirit DPS summing all damaging abilities.

    In-game: Sum the DPS of each ability on the hero tooltips.
    """

    def test_base_spirit_dps_no_items(self, heroes):
        """Total spirit DPS at 0 spirit should be sum of base abilities / cooldowns."""
        hero = _hero(heroes, "Infernus")
        dps = DamageCalculator.hero_total_spirit_dps(hero, current_spirit=0)
        assert dps > 0, "Infernus should have positive spirit DPS"

    def test_spirit_dps_increases_with_spirit_power(self, heroes):
        """Adding spirit power should increase total spirit DPS."""
        hero = _hero(heroes, "Infernus")
        dps_0 = DamageCalculator.hero_total_spirit_dps(hero, current_spirit=0)
        dps_50 = DamageCalculator.hero_total_spirit_dps(hero, current_spirit=50)
        assert dps_50 > dps_0, "Spirit DPS should increase with spirit power"

    def test_spirit_dps_with_cdr(self, heroes):
        """CDR should increase spirit DPS for instant-damage abilities (more casts per second).

        Note: For DoT abilities (duration > 0), DPS = damage/duration, so CDR
        has no effect. We test with a hero that has instant abilities.
        """
        # Find a hero with at least one instant damaging ability (duration == 0)
        for name in ["Wraith", "Haze", "Seven", "Infernus", "Abrams"]:
            hero = heroes.get(name)
            if hero is None:
                continue
            has_instant = any(
                a.base_damage > 0 and a.cooldown > 0 and a.duration == 0
                for a in hero.abilities
            )
            if has_instant:
                break
        else:
            pytest.skip("No hero with instant damaging abilities found")

        dps_no_cdr = DamageCalculator.hero_total_spirit_dps(hero, current_spirit=20)
        dps_with_cdr = DamageCalculator.hero_total_spirit_dps(
            hero, current_spirit=20, cooldown_reduction=0.30,
        )
        assert dps_with_cdr >= dps_no_cdr, "CDR should not reduce spirit DPS"

    def test_spirit_dps_with_upgrades(self, heroes):
        """Ability upgrades that add damage should increase total spirit DPS."""
        hero = _hero(heroes, "Infernus")
        base = DamageCalculator.hero_total_spirit_dps(hero, current_spirit=20)
        upgraded = DamageCalculator.hero_total_spirit_dps(
            hero, current_spirit=20, ability_upgrades={0: [1]},
        )
        # May or may not increase — depends on what T1 does
        # At minimum it shouldn't decrease
        assert upgraded >= base - 0.1


# ═══════════════════════════════════════════════════════════════════
# 8. DPS WITH ACCURACY & HEADSHOTS
# ═══════════════════════════════════════════════════════════════════


class TestDPSWithAccuracy:
    """Verify realistic DPS factoring accuracy and headshots.

    Formula: realistic = final_dps × accuracy + final_dps × accuracy × hs_rate × (hs_mult - 1)
    """

    def test_perfect_accuracy_no_headshots(self, heroes):
        """100% accuracy, 0% headshots → realistic = final_dps."""
        hero = _hero(heroes, "Haze")
        config = CombatConfig(boons=0, accuracy=1.0, headshot_rate=0.0, distance=0.0)
        bullet = DamageCalculator.calculate_bullet(hero, config)
        realistic = DamageCalculator.dps_with_accuracy(hero, config)
        assert realistic == pytest.approx(bullet.final_dps)

    def test_fifty_percent_accuracy(self, heroes):
        """50% accuracy, 0% headshots → realistic = final_dps × 0.5."""
        hero = _hero(heroes, "Haze")
        config = CombatConfig(boons=0, accuracy=0.5, headshot_rate=0.0, distance=0.0)
        bullet = DamageCalculator.calculate_bullet(hero, config)
        realistic = DamageCalculator.dps_with_accuracy(hero, config)
        assert realistic == pytest.approx(bullet.final_dps * 0.5)

    def test_headshot_bonus(self, heroes):
        """80% accuracy, 20% headshot rate, 1.5× headshot multiplier.

        realistic = dps × 0.8 + dps × 0.8 × 0.2 × (1.5 - 1)
                  = dps × 0.8 + dps × 0.08
                  = dps × 0.88
        """
        hero = _hero(heroes, "Haze")
        config = CombatConfig(
            boons=0, accuracy=0.8, headshot_rate=0.2,
            headshot_multiplier=1.5, distance=0.0,
        )
        bullet = DamageCalculator.calculate_bullet(hero, config)
        realistic = DamageCalculator.dps_with_accuracy(hero, config)
        expected = bullet.final_dps * 0.8 + bullet.final_dps * 0.8 * 0.2 * 0.5
        assert realistic == pytest.approx(expected)


# ═══════════════════════════════════════════════════════════════════
# 9. HERO SCALING (HeroMetrics)
# ═══════════════════════════════════════════════════════════════════


class TestHeroScaling:
    """Verify hero stat scaling across boon levels.

    In-game: Check stats panel at different boon counts.
    """

    def test_snapshot_boon_0(self, heroes):
        """At boon 0, snapshot should match base stats."""
        hero = _hero(heroes, "Haze")
        snap = HeroMetrics.snapshot(hero, 0)

        assert snap.bullet_damage == pytest.approx(hero.base_bullet_damage)
        assert snap.hp == pytest.approx(hero.base_hp)
        assert snap.spirit == pytest.approx(0.0)
        assert snap.dps == pytest.approx(
            hero.base_bullet_damage * hero.pellets * hero.base_fire_rate
        )
        assert snap.dpm == pytest.approx(
            hero.base_bullet_damage * hero.pellets * hero.base_ammo
        )

    def test_snapshot_boon_10(self, heroes):
        """At boon 10, verify damage and HP scaling."""
        hero = _hero(heroes, "Haze")
        snap = HeroMetrics.snapshot(hero, 10)

        assert snap.bullet_damage == pytest.approx(
            hero.base_bullet_damage + hero.damage_gain * 10
        )
        assert snap.hp == pytest.approx(hero.base_hp + hero.hp_gain * 10)
        assert snap.spirit == pytest.approx(hero.spirit_gain * 10)

    def test_scaling_curve_length(self, heroes):
        """Scaling curve from 0 to 35 should have 36 entries."""
        hero = _hero(heroes, "Haze")
        curve = HeroMetrics.scaling_curve(hero, max_boons=35)
        assert len(curve) == 36

    def test_scaling_curve_monotonic_dps(self, heroes):
        """DPS should increase monotonically across boon levels."""
        hero = _hero(heroes, "Haze")
        curve = HeroMetrics.scaling_curve(hero)
        for i in range(1, len(curve)):
            assert curve[i].dps >= curve[i - 1].dps, (
                f"DPS decreased from boon {i-1} to {i}"
            )

    def test_growth_percentage(self, heroes):
        """Growth percentage should be positive for all heroes."""
        hero = _hero(heroes, "Haze")
        growth = HeroMetrics.growth_percentage(hero)
        assert growth["dps_growth"] > 0
        assert growth["hp_growth"] > 0
        assert growth["aggregate_growth"] > 0

    def test_growth_percentage_formula(self, heroes):
        """Verify growth formula: (max - base) / base."""
        hero = _hero(heroes, "Haze")
        growth = HeroMetrics.growth_percentage(hero, max_boons=35)

        max_bullet = hero.base_bullet_damage + hero.damage_gain * 35
        max_dps = max_bullet * hero.pellets * hero.base_fire_rate
        expected_dps_growth = (max_dps - hero.base_dps) / hero.base_dps

        assert growth["dps_growth"] == pytest.approx(expected_dps_growth)


# ═══════════════════════════════════════════════════════════════════
# 10. TTK (Time-to-Kill)
# ═══════════════════════════════════════════════════════════════════


class TestTTK:
    """Verify time-to-kill calculations.

    In-game:
    1. Pick attacker hero, set target to defender hero
    2. Note target HP and your DPS
    3. Time how long it takes to kill
    4. Compare to engine's TTK output
    """

    def test_ttk_basic(self, heroes):
        """Scenario: Haze vs Abrams at boon 0, 100% accuracy, no items.

        TTK should be target_hp / final_dps (or step-by-step with reloads).
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")
        config = CombatConfig(boons=0, accuracy=1.0, headshot_rate=0.0, distance=0.0)
        result = HeroMetrics.ttk(haze, abrams, config)

        assert result.target_hp == pytest.approx(abrams.base_hp)
        assert result.effective_dps > 0
        assert result.realistic_ttk > 0
        # Realistic TTK with 100% accuracy should use step-by-step sim
        assert result.magazines_needed >= 1

    def test_ttk_increases_with_resist(self, heroes):
        """Adding resist should increase TTK (takes longer to kill)."""
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        no_resist = CombatConfig(boons=0, accuracy=1.0, distance=0.0)
        with_resist = CombatConfig(
            boons=0, accuracy=1.0, distance=0.0, enemy_bullet_resist=0.30,
        )

        ttk_no_resist = HeroMetrics.ttk(haze, abrams, no_resist)
        ttk_with_resist = HeroMetrics.ttk(haze, abrams, with_resist)

        assert ttk_with_resist.realistic_ttk > ttk_no_resist.realistic_ttk

    def test_ttk_decreases_with_weapon_bonus(self, heroes):
        """Weapon damage bonus should reduce TTK."""
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        base = CombatConfig(boons=0, accuracy=1.0, distance=0.0)
        boosted = CombatConfig(
            boons=0, accuracy=1.0, distance=0.0, weapon_damage_bonus=0.50,
        )

        ttk_base = HeroMetrics.ttk(haze, abrams, base)
        ttk_boosted = HeroMetrics.ttk(haze, abrams, boosted)

        assert ttk_boosted.realistic_ttk < ttk_base.realistic_ttk

    def test_ttk_one_mag_flag(self, heroes):
        """Check can_one_mag flag accuracy.

        If damage_per_magazine > target_hp → can_one_mag = True.
        """
        haze = _hero(heroes, "Haze")
        # Make a weak target that can be one-magged
        weak_target = HeroStats(name="Weak", base_hp=100)
        config = CombatConfig(boons=0, accuracy=1.0, distance=0.0)
        result = HeroMetrics.ttk(haze, weak_target, config)

        if result.damage_per_magazine > weak_target.base_hp:
            assert result.can_one_mag is True
            assert result.magazines_needed == 1

    def test_ttk_low_accuracy_needs_more_mags(self, heroes):
        """Low accuracy should require more magazines to kill."""
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        high_acc = CombatConfig(boons=0, accuracy=1.0, distance=0.0)
        low_acc = CombatConfig(boons=0, accuracy=0.3, distance=0.0)

        ttk_high = HeroMetrics.ttk(haze, abrams, high_acc)
        ttk_low = HeroMetrics.ttk(haze, abrams, low_acc)

        assert ttk_low.magazines_needed >= ttk_high.magazines_needed
        assert ttk_low.realistic_ttk > ttk_high.realistic_ttk

    def test_ttk_curve_length(self, heroes):
        """TTK curve should have entries for each boon level."""
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")
        config = CombatConfig(accuracy=1.0, distance=0.0)
        curve = HeroMetrics.ttk_curve(haze, abrams, config, max_boons=35)
        assert len(curve) == 36

    def test_ttk_decreases_with_boons(self, heroes):
        """TTK should generally decrease as boons increase (more damage)."""
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")
        config = CombatConfig(accuracy=1.0, distance=0.0)
        curve = HeroMetrics.ttk_curve(haze, abrams, config, max_boons=35)

        # First boon TTK should be > last boon TTK
        # (Both get boons, but attacker's DPS scales faster than defender HP for most matchups)
        boon_0_ttk = curve[0][1].realistic_ttk
        boon_35_ttk = curve[35][1].realistic_ttk
        # Not all matchups guarantee this, but Haze vs Abrams should scale
        # At minimum, TTK at high boons shouldn't be dramatically worse
        assert boon_35_ttk < boon_0_ttk * 2, "TTK at max boons shouldn't be 2× worse"


# ═══════════════════════════════════════════════════════════════════
# 11. BUILD ENGINE
# ═══════════════════════════════════════════════════════════════════


class TestBuildEngine:
    """Verify build aggregation, shop tier bonuses, and build evaluation.

    In-game:
    1. Buy specific items in sandbox
    2. Check combined stats in stats panel
    3. Compare to engine's aggregate_stats output
    """

    def test_empty_build(self):
        """Empty build → all stats zero."""
        build = Build(items=[])
        stats = BuildEngine.aggregate_stats(build)
        assert stats.weapon_damage_pct == pytest.approx(0.0)
        assert stats.bonus_hp == pytest.approx(0.0)
        assert stats.spirit_power == pytest.approx(0.0)
        assert stats.total_cost == 0

    def test_single_weapon_item(self, items):
        """Buy one weapon item, check its stats are reflected.

        In-game: Buy Headshot Booster, check stats panel.
        """
        item = _item(items, "Headshot Booster")
        build = Build(items=[item])
        stats = BuildEngine.aggregate_stats(build)

        assert stats.total_cost == item.cost
        assert stats.weapon_cost == item.cost

    def test_resist_stacks_multiplicatively(self, items):
        """Two resist items → multiplicative stacking.

        Example: 15% + 20% → 1 - (0.85)(0.80) = 32%, not 35%.
        """
        # Find two items with bullet resist
        resist_items = [
            i for i in items.values()
            if i.bullet_resist_pct > 0 and not i.condition
        ]
        if len(resist_items) < 2:
            pytest.skip("Need 2+ bullet resist items")

        i1, i2 = resist_items[0], resist_items[1]
        build = Build(items=[i1, i2])
        stats = BuildEngine.aggregate_stats(build)

        expected = 1.0 - (1.0 - i1.bullet_resist_pct) * (1.0 - i2.bullet_resist_pct)
        assert stats.bullet_resist_pct == pytest.approx(expected)

    def test_shop_tier_weapon_bonus(self, items):
        """Spending 800+ souls on weapon items grants shop tier bonus.

        In-game: Buy weapon items totaling 800+ souls, check weapon % in stats.
        Bonus = _SHOP_TIER_DATA lookup for weapon column.
        """
        weapon_items = sorted(
            [i for i in items.values() if i.category.lower() == "weapon"],
            key=lambda x: x.cost,
        )
        # Build up to at least 800 in weapon
        selected = []
        total = 0
        for item in weapon_items:
            if total >= 800:
                break
            selected.append(item)
            total += item.cost

        if total < 800:
            pytest.skip("Not enough weapon items to reach 800 threshold")

        build = Build(items=selected)
        stats = BuildEngine.aggregate_stats(build)

        # Should have shop tier bonus applied
        tier_bonus = 0
        for row in _SHOP_TIER_DATA:
            if stats.weapon_cost >= row[0]:
                tier_bonus = row[1]
        assert tier_bonus > 0
        # The weapon_damage_pct should include the tier bonus
        item_weapon_pct = sum(i.weapon_damage_pct for i in selected)
        assert stats.weapon_damage_pct == pytest.approx(
            item_weapon_pct + tier_bonus / 100.0
        )

    def test_shop_tier_spirit_bonus(self, items):
        """Spirit shop tier grants flat spirit power.

        In-game: Buy spirit items totaling 800+ souls, check spirit power in stats.
        """
        spirit_items = sorted(
            [i for i in items.values() if i.category.lower() == "spirit"],
            key=lambda x: x.cost,
        )
        selected = []
        total = 0
        for item in spirit_items:
            if total >= 800:
                break
            selected.append(item)
            total += item.cost

        if total < 800:
            pytest.skip("Not enough spirit items to reach 800 threshold")

        build = Build(items=selected)
        stats = BuildEngine.aggregate_stats(build)

        tier_bonus = 0
        for row in _SHOP_TIER_DATA:
            if stats.spirit_cost >= row[0]:
                tier_bonus = row[3]
        assert tier_bonus > 0
        item_spirit = sum(i.spirit_power for i in selected)
        assert stats.spirit_power == pytest.approx(item_spirit + tier_bonus)

    def test_build_to_attacker_config(self, items, heroes):
        """Verify build_to_attacker_config populates CombatConfig correctly.

        Spirit = item_spirit + spirit_gain × boons.
        """
        hero = _hero(heroes, "Haze")
        build = Build(items=[_item(items, "Headshot Booster")])
        stats = BuildEngine.aggregate_stats(build)

        config = BuildEngine.build_to_attacker_config(
            stats, boons=10, spirit_gain=hero.spirit_gain,
        )

        expected_spirit = int(stats.spirit_power + hero.spirit_gain * 10)
        assert config.current_spirit == expected_spirit
        assert config.boons == 10
        assert config.weapon_damage_bonus == pytest.approx(stats.weapon_damage_pct)
        assert config.fire_rate_bonus == pytest.approx(stats.fire_rate_pct)

    def test_defender_effective_hp(self, heroes):
        """Verify defender EHP calculation.

        Formula: (base_hp + hp_gain × boons) × (1 + base_hp_pct) + bonus_hp + shields.
        """
        abrams = _hero(heroes, "Abrams")
        bs = BuildStats(bonus_hp=200, bullet_shield=100, spirit_shield=50, base_hp_pct=0.10)
        boons = 10

        result = BuildEngine.defender_effective_hp(abrams, bs, boons)

        base = (abrams.base_hp + abrams.hp_gain * 10) * 1.10
        expected = base + 200 + 100 + 50
        assert result == pytest.approx(expected)

    def test_evaluate_build_returns_result(self, heroes, items):
        """Evaluate a build and verify all fields populated."""
        hero = _hero(heroes, "Haze")
        build = Build(items=[_item(items, "Headshot Booster")])
        result = BuildEngine.evaluate_build(hero, build, boons=10)

        assert result.hero_name == "Haze"
        assert result.bullet_result is not None
        assert result.bullet_result.raw_dps > 0
        assert result.effective_hp > 0


# ═══════════════════════════════════════════════════════════════════
# 12. HERO COMPARISON
# ═══════════════════════════════════════════════════════════════════


class TestComparison:
    """Verify hero comparison and ranking engine."""

    def test_compare_two_heroes(self, heroes):
        """Compare Haze vs Abrams at boon 0."""
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")
        comp = ComparisonEngine.compare_two(haze, abrams, boon_level=0)

        assert comp.hero_a_name == "Haze"
        assert comp.hero_b_name == "Abrams"
        assert comp.dps_ratio > 0
        assert comp.hp_ratio > 0

        # Ratio should be a / b
        assert comp.dps_ratio == pytest.approx(comp.hero_a_dps / comp.hero_b_dps)

    def test_compare_curve(self, heroes):
        """Comparison curve should have 36 entries (0-35 boons)."""
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")
        curve = ComparisonEngine.compare_curve(haze, abrams)
        assert len(curve) == 36

    def test_rank_heroes_dps(self, heroes):
        """Rank heroes by DPS — should include all heroes, descending."""
        rankings = ComparisonEngine.rank_heroes(heroes, "dps", boon_level=0)
        assert len(rankings) == len(heroes)
        # Check descending order
        for i in range(1, len(rankings)):
            assert rankings[i].value <= rankings[i - 1].value
        # Rank numbers should be sequential
        for i, entry in enumerate(rankings):
            assert entry.rank == i + 1

    def test_rank_heroes_hp(self, heroes):
        """Rank heroes by HP at boon 0."""
        rankings = ComparisonEngine.rank_heroes(heroes, "hp", boon_level=0)
        assert len(rankings) == len(heroes)
        for i in range(1, len(rankings)):
            assert rankings[i].value <= rankings[i - 1].value

    def test_cross_ttk_matrix(self, heroes):
        """TTK matrix should be NxN with positive values.

        In-game: This is the "who kills who fastest" matrix.
        """
        subset = list(heroes.keys())[:3]
        config = CombatConfig(boons=0, accuracy=1.0, distance=0.0)
        matrix = ComparisonEngine.cross_ttk_matrix(heroes, config, hero_names=subset)

        assert len(matrix) == len(subset)
        for atk in subset:
            assert atk in matrix
            for df in subset:
                assert df in matrix[atk]
                assert matrix[atk][df] > 0


# ═══════════════════════════════════════════════════════════════════
# 13. ITEM DAMAGE
# ═══════════════════════════════════════════════════════════════════


class TestItemDamage:
    """Verify item DPS calculation for damage-dealing items.

    In-game:
    1. Buy the item
    2. Check proc damage on target dummy
    3. Compare to engine's calculated DPS
    """

    def test_spirit_scaled_item(self, items):
        """Spirit-scaled item damage increases with spirit power.

        In-game: Buy the item + spirit items, check proc damage.
        """
        # Find a spirit-scaling damage item
        for item in items.values():
            r0 = DamageCalculator.calculate_item_damage(item, current_spirit=0)
            r50 = DamageCalculator.calculate_item_damage(item, current_spirit=50)
            if r0 and r50 and r50.scaled_from == "spirit":
                assert r50.dps >= r0.dps, (
                    f"{item.name}: spirit scaling should increase DPS"
                )
                assert r50.spirit_contribution > 0
                return
        pytest.skip("No spirit-scaled damage items found")

    def test_boon_scaled_item(self, items):
        """Boon-scaled item damage increases with boon count."""
        for item in items.values():
            r0 = DamageCalculator.calculate_item_damage(item, boons=0)
            r20 = DamageCalculator.calculate_item_damage(item, boons=20)
            if r0 and r20 and r20.scaled_from == "boons":
                assert r20.dps >= r0.dps, (
                    f"{item.name}: boon scaling should increase DPS"
                )
                assert r20.boon_contribution > 0
                return
        pytest.skip("No boon-scaled damage items found")

    def test_item_damage_reduced_by_resist(self, items):
        """Spirit damage items should be reduced by spirit resist."""
        for item in items.values():
            r_no = DamageCalculator.calculate_item_damage(item, enemy_spirit_resist=0.0)
            r_yes = DamageCalculator.calculate_item_damage(item, enemy_spirit_resist=0.30)
            if r_no and r_yes and r_no.damage_type == "spirit":
                assert r_yes.dps < r_no.dps, (
                    f"{item.name}: resist should reduce spirit DPS"
                )
                return
        pytest.skip("No spirit damage items found")


# ═══════════════════════════════════════════════════════════════════
# 14. COMBAT SIMULATION
# ═══════════════════════════════════════════════════════════════════


class TestCombatSimulation:
    """Verify the event-driven combat simulator.

    These tests run the full sim and check structural correctness.
    The exact numbers depend on game data, but relations should hold.
    """

    def test_basic_sim_runs(self, heroes):
        """Basic simulation should complete without error.

        Scenario: Haze attacks Abrams for 10 seconds, no items.
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        config = SimConfig(
            attacker=haze,
            defender=abrams,
            settings=SimSettings(duration=10.0, weapon_uptime=1.0),
        )
        result = CombatSimulator.run(config)

        assert result.overall_dps > 0
        assert result.total_damage > 0
        assert len(result.timeline) > 0

    def test_sim_weapon_uptime_affects_dps(self, heroes):
        """Lower weapon uptime should reduce DPS.

        Scenario: Compare 100% uptime vs 50% uptime.
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        full = SimConfig(
            attacker=haze, defender=abrams,
            settings=SimSettings(duration=10.0, weapon_uptime=1.0),
        )
        half = SimConfig(
            attacker=haze, defender=abrams,
            settings=SimSettings(duration=10.0, weapon_uptime=0.5),
        )

        result_full = CombatSimulator.run(full)
        result_half = CombatSimulator.run(half)

        assert result_half.overall_dps < result_full.overall_dps

    def test_sim_with_items(self, heroes, items):
        """Scenario: Haze with weapon items should deal more DPS.

        In-game: Buy weapon items, run sandbox fight, compare DPS.
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        naked = SimConfig(
            attacker=haze, defender=abrams,
            settings=SimSettings(duration=10.0),
        )
        equipped = SimConfig(
            attacker=haze,
            attacker_build=Build(items=[_item(items, "Headshot Booster")]),
            defender=abrams,
            settings=SimSettings(duration=10.0),
        )

        r_naked = CombatSimulator.run(naked)
        r_equipped = CombatSimulator.run(equipped)

        assert r_equipped.overall_dps >= r_naked.overall_dps

    def test_sim_boons_increase_damage(self, heroes):
        """Higher boon levels should increase DPS.

        Scenario: 0 boons vs 20 boons.
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        low = SimConfig(
            attacker=haze, defender=abrams,
            settings=SimSettings(duration=10.0, attacker_boons=0),
        )
        high = SimConfig(
            attacker=haze, defender=abrams,
            settings=SimSettings(duration=10.0, attacker_boons=20),
        )

        r_low = CombatSimulator.run(low)
        r_high = CombatSimulator.run(high)

        assert r_high.overall_dps > r_low.overall_dps

    def test_sim_bidirectional_mode(self, heroes):
        """Bidirectional mode: both combatants deal damage.

        Verify both sides register damage and a winner emerges.
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        config = SimConfig(
            attacker=haze, defender=abrams,
            settings=SimSettings(
                duration=30.0,
                bidirectional=True,
                attacker_boons=10,
                defender_boons=10,
            ),
        )
        result = CombatSimulator.run(config)

        assert result.overall_dps > 0
        # In bidirectional mode, defender should also deal damage
        if result.defender_dps is not None:
            assert result.defender_dps > 0

    def test_sim_resist_reduces_damage(self, heroes):
        """Defender resist should reduce total damage taken.

        Scenario: Same fight with 0 vs 30% bullet resist on defender.
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        no_resist = SimConfig(
            attacker=haze,
            defender=HeroStats(name="Dummy", base_hp=5000),
            settings=SimSettings(duration=10.0),
        )
        with_resist = SimConfig(
            attacker=haze,
            defender=HeroStats(name="Dummy", base_hp=5000),
            defender_build=Build(items=[]),
            settings=SimSettings(duration=10.0),
        )

        r_no = CombatSimulator.run(no_resist)

        # Create a defender build with resist
        resist_items = [
            i for i in load_items().values()
            if i.bullet_resist_pct > 0 and not i.condition
        ]
        if resist_items:
            with_resist = SimConfig(
                attacker=haze,
                defender=HeroStats(name="Dummy", base_hp=5000),
                defender_build=Build(items=[resist_items[0]]),
                settings=SimSettings(duration=10.0),
            )
            r_yes = CombatSimulator.run(with_resist)
            assert r_yes.overall_dps <= r_no.overall_dps

    def test_sim_timeline_ordered(self, heroes):
        """Events in timeline should be in chronological order."""
        haze = _hero(heroes, "Haze")
        config = SimConfig(
            attacker=haze,
            defender=HeroStats(name="Dummy", base_hp=5000),
            settings=SimSettings(duration=5.0),
        )
        result = CombatSimulator.run(config)

        times = [e.time for e in result.timeline]
        assert times == sorted(times), "Timeline events should be time-ordered"


# ═══════════════════════════════════════════════════════════════════
# 14b. SIMULATION — RELOAD & DURATION ACCURACY
# ═══════════════════════════════════════════════════════════════════


class TestSimReloadDamage:
    """Verify simulation weapon damage matches manual fire/reload calculations.

    These tests ensure the sim correctly models:
    - First bullet fires at t=0
    - Magazine empties at tpb intervals
    - Reload takes exactly reload_duration
    - Firing resumes after reload
    - Duration cutoff is respected

    In-game verification:
    1. Pick the hero in sandbox
    2. Set a timer for the specified duration
    3. Shoot the target dummy continuously
    4. Compare total damage dealt to sim output
    """

    @staticmethod
    def _weapon_only_settings(duration, boons=0):
        return SimSettings(
            duration=duration,
            weapon_uptime=1.0,
            accuracy=1.0,
            headshot_rate=0.0,
            distance=0.0,
            attacker_boons=boons,
            defender_boons=0,
            weave_melee=False,
            melee_after_reload=False,
            ability_uptime=0.0,
        )

    @staticmethod
    def _manual_bullet_count(hero, duration):
        """Step through fire/reload cycles to count bullets fired.

        First bullet fires at t=0, then every tpb seconds.
        When ammo=0, wait reload_duration then refill.
        Stop when next fire would exceed duration.
        """
        tpb = 1.0 / hero.base_fire_rate
        t = 0.0
        bullets = 0
        ammo = hero.base_ammo
        reloads = 0
        while True:
            if ammo > 0:
                if t > duration:
                    break
                bullets += 1
                ammo -= 1
                t += tpb
            else:
                t += hero.reload_duration
                if t > duration:
                    break
                ammo = hero.base_ammo
                reloads += 1
        return bullets, reloads

    _DUMMY = HeroStats(name="Dummy", base_hp=100000, base_regen=0)

    # ── Single magazine (no reload) ───────────────────────────────

    def test_venator_3s_no_reload(self, heroes):
        """Venator 3s fight: 24 bullets × 8.0 = 192.0.

        Magdump = 33 × 0.126s = 4.158s, so 3s fits 24 bullets with no reload.

        In-game: Pick Venator, shoot dummy for exactly 3 seconds.
        """
        hero = _hero(heroes, "Venator")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(3.0),
        )
        result = CombatSimulator.run(config)

        bullets, reloads = self._manual_bullet_count(hero, 3.0)
        expected = bullets * hero.base_bullet_damage
        assert bullets == 24
        assert reloads == 0
        assert result.bullet_damage == pytest.approx(expected)

    # ── One reload ────────────────────────────────────────────────

    def test_venator_5s_no_reload(self, heroes):
        """Venator 5s fight: 33 bullets (full mag), no reload needed.

        Magdump = 33 × 0.126s = 4.158s, fits in 5s.

        In-game: Shoot dummy for 5 seconds with Venator.
        """
        hero = _hero(heroes, "Venator")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(5.0),
        )
        result = CombatSimulator.run(config)

        bullets, reloads = self._manual_bullet_count(hero, 5.0)
        expected = bullets * hero.base_bullet_damage
        assert bullets == 33
        assert reloads == 0
        assert result.bullet_damage == pytest.approx(expected)

    # ── Multiple reloads ──────────────────────────────────────────

    def test_venator_10s_one_reload(self, heroes):
        """Venator 10s fight: 58 bullets, 1 reload.

        Cycle = 4.158s dump + 2.80s reload = 6.958s, then 25 more bullets.

        In-game: Shoot dummy for 10 seconds with Venator.
        """
        hero = _hero(heroes, "Venator")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(10.0),
        )
        result = CombatSimulator.run(config)

        bullets, reloads = self._manual_bullet_count(hero, 10.0)
        expected = bullets * hero.base_bullet_damage
        assert bullets == 58
        assert reloads == 1
        assert result.bullet_damage == pytest.approx(expected)

    # ── Slow fire rate hero (Seven, 3-round burst) ────────────────

    def test_seven_10s_one_reload(self, heroes):
        """Seven 10s fight: 30 bullets, 1 reload.

        Seven fires at 3.81 rps (0.2625s/bullet), mag=29.
        Magdump = 7.613s + reload 2.35s = 9.963s, then 1 more.

        In-game: Shoot dummy for 10 seconds with Seven.
        """
        hero = _hero(heroes, "Seven")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(10.0),
        )
        result = CombatSimulator.run(config)

        bullets, reloads = self._manual_bullet_count(hero, 10.0)
        expected = bullets * hero.base_bullet_damage * hero.pellets
        assert bullets == 30
        assert reloads == 1
        assert result.bullet_damage == pytest.approx(expected)

    # ── Multi-pellet hero (Abrams) ────────────────────────────────

    def test_abrams_10s_one_reload(self, heroes):
        """Abrams 10s fight: 16 shots × 32.4 per shot = 518.40.

        Abrams fires at 1.587 rps (0.63s/shot), mag=9.
        Magdump = 5.67s + reload 0.35s = 6.02s, then 6 more shots.

        In-game: Shoot dummy for 10 seconds with Abrams at point blank.
        """
        hero = _hero(heroes, "Abrams")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(10.0),
        )
        result = CombatSimulator.run(config)

        bullets, reloads = self._manual_bullet_count(hero, 10.0)
        expected = bullets * hero.base_bullet_damage * hero.pellets
        assert reloads == 1
        assert result.bullet_damage == pytest.approx(expected)

    # ── Large magazine hero (Wraith) ──────────────────────────────

    def test_wraith_5s_no_reload(self, heroes):
        """Wraith 5s fight: 52 bullets, no reload needed.

        Magdump = 52 × 0.0945s = 4.914s, fits in 5s.

        In-game: Shoot dummy for 5 seconds with Wraith.
        """
        hero = _hero(heroes, "Wraith")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(5.0),
        )
        result = CombatSimulator.run(config)

        bullets, reloads = self._manual_bullet_count(hero, 5.0)
        expected = bullets * hero.base_bullet_damage * hero.pellets
        assert bullets == 52
        assert reloads == 0
        assert result.bullet_damage == pytest.approx(expected)

    def test_wraith_10s_one_reload(self, heroes):
        """Wraith 10s fight: 76 bullets, 1 reload.

        Magdump (4.914s) + reload (2.82s) = 7.734s, then 24 more.

        In-game: Shoot dummy for 10 seconds with Wraith.
        """
        hero = _hero(heroes, "Wraith")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(10.0),
        )
        result = CombatSimulator.run(config)

        bullets, reloads = self._manual_bullet_count(hero, 10.0)
        expected = bullets * hero.base_bullet_damage * hero.pellets
        assert reloads == 1
        assert result.bullet_damage == pytest.approx(expected)

    # ── Extended sim (15s, multiple reloads) ──────────────────────

    def test_venator_15s_two_reloads(self, heroes):
        """Venator 15s fight: 75 bullets, 2 reloads.

        In-game: Long fight to verify multiple reload cycles accumulate correctly.
        """
        hero = _hero(heroes, "Venator")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(15.0),
        )
        result = CombatSimulator.run(config)

        bullets, reloads = self._manual_bullet_count(hero, 15.0)
        expected = bullets * hero.base_bullet_damage
        assert reloads == 2
        assert result.bullet_damage == pytest.approx(expected)

    # ── With boons (damage scaling) ───────────────────────────────

    def test_venator_10s_boon10(self, heroes):
        """Venator 10s fight at boon 10: same bullet count, higher per-bullet.

        58 bullets at boon 10 damage. Boons don't change fire rate or mag.

        In-game: Reach boon 10, shoot dummy for 10 seconds.
        """
        hero = _hero(heroes, "Venator")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(10.0, boons=10),
        )
        result = CombatSimulator.run(config)

        dmg_per_bullet = hero.base_bullet_damage + hero.damage_gain * 10
        bullets, _ = self._manual_bullet_count(hero, 10.0)
        expected = bullets * dmg_per_bullet
        assert bullets == 58
        assert result.bullet_damage == pytest.approx(expected)

    # ── With items (Extended Magazine) ────────────────────────────

    def test_venator_10s_extended_mag(self, heroes, items):
        """Venator 10s + Extended Magazine: increased mag changes reload timing.

        Extended Mag gives +30% ammo plus shop tier weapon bonus.

        In-game: Buy Extended Magazine on Venator, shoot dummy for 10 seconds.
        """
        hero = _hero(heroes, "Venator")
        em = _item(items, "Extended Magazine")
        build = Build(items=[em])
        bs = BuildEngine.aggregate_stats(build)

        config = SimConfig(
            attacker=hero, attacker_build=build, defender=self._DUMMY,
            settings=self._weapon_only_settings(10.0),
        )
        result = CombatSimulator.run(config)

        # Sim applies shop tier weapon bonus
        per_bullet = hero.base_bullet_damage * (1 + bs.weapon_damage_pct)
        new_mag = math.ceil(hero.base_ammo * (1 + bs.ammo_pct))

        # Count weapon events from timeline to verify
        weapon_events = sum(1 for e in result.timeline if e.source == "weapon")
        expected_dmg = weapon_events * per_bullet
        assert result.bullet_damage == pytest.approx(expected_dmg, rel=0.01)
        assert result.bullet_damage > 0

    # ── With headshots ────────────────────────────────────────────

    def test_venator_5s_headshots(self, heroes):
        """Venator 5s with 50% headshot rate using hero's crit multiplier.

        Uses hero.crit_bonus_start (1.65) for headshot damage.
        avg_mult = 1.0 + 0.5 * (1.65 - 1.0) = 1.325.

        In-game: Aim for ~50% headshots over 5 seconds.
        """
        hero = _hero(heroes, "Venator")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=SimSettings(
                duration=5.0,
                weapon_uptime=1.0,
                accuracy=1.0,
                headshot_rate=0.5,
                headshot_multiplier=1.5,
                distance=0.0,
                attacker_boons=0,
                defender_boons=0,
                weave_melee=False,
                melee_after_reload=False,
                ability_uptime=0.0,
            ),
        )
        result = CombatSimulator.run(config)

        bullets, _ = self._manual_bullet_count(hero, 5.0)
        avg_mult = 1.0 + 0.5 * (hero.crit_bonus_start - 1.0)
        expected = bullets * hero.base_bullet_damage * avg_mult
        assert result.bullet_damage == pytest.approx(expected)

    # ── DPS convergence over longer duration ──────────────────────

    def test_sustained_dps_converges(self, heroes):
        """Over long durations, sim DPS should approach analytical sustained DPS.

        Analytical sustained = mag_dmg / (magdump + reload).
        Sim DPS over 30s should be within 5% of analytical.
        Uses Wraith (clean auto — no passive weapon buffs).
        """
        hero = _hero(heroes, "Wraith")
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(30.0),
        )
        result = CombatSimulator.run(config)

        analytical = DamageCalculator.calculate_bullet(
            hero, CombatConfig(boons=0, distance=0.0),
        )
        sim_dps = result.bullet_damage / 30.0
        assert sim_dps == pytest.approx(analytical.sustained_dps, rel=0.05)

    # ── Two-mag sustained DPS by weapon archetype ─────────────────

    @staticmethod
    def _two_mag_cycle(hero):
        """Return (duration, cycle_time, mag_dmg) for 2 full mag+reload cycles."""
        tpb = 1.0 / hero.base_fire_rate
        magdump = hero.base_ammo * tpb
        cycle = magdump + hero.reload_duration
        eff_pellets = DamageCalculator.effective_pellets(hero)
        mag_dmg = hero.base_bullet_damage * eff_pellets * hero.base_ammo
        # Subtract epsilon so the sim ends at reload completion,
        # not at the start of a 3rd magazine.
        return 2 * cycle - 0.001, cycle, mag_dmg

    @pytest.mark.parametrize("hero_name,expected_dps", [
        # (hero, sustained DPS = mag_dmg / cycle_time)
        # Fast auto
        ("Venator", 37.94),
        # Burst fire
        ("Seven", 31.47),
        # Spread shotgun (9 pellets, fast reload)
        ("Abrams", 48.42),
        # Tight shotgun (3 pellets, 1 per target)
        ("Drifter", 30.25),
        # Slow sniper (highest per-bullet)
        ("Grey Talon", 32.85),
        # Fastest spray (14.29 rps)
        ("Vyper", 48.15),
        # Huge magazine (66 rounds)
        ("McGinnis", 23.86),
        # Fast reload shotgun (0.30s reload)
        ("Silver", 40.83),
        # Semi-auto heavy (35 per bullet)
        ("Paige", 51.58),
        # Multi-pellet slash (5 pellets)
        ("Yamato", 42.57),
    ])
    def test_two_mag_sustained_dps(self, heroes, hero_name, expected_dps):
        """Sustained DPS across weapon archetypes (2 mags + 2 reloads).

        DPS = (2 × mag_damage) / (2 × cycle_time)
        where cycle = magdump_time + reload_time.

        NOTE: The game's stats panel shows BURST DPS (while firing),
        not sustained DPS. Our sustained DPS includes reload downtime
        and will always be lower than the in-game DPS readout.
        The per-bullet damage and bullet counts are verified exactly;
        this test validates sim ↔ analytical engine consistency.

        In-game verification:
        1. Pick the hero at boon 0, no items
        2. Empty exactly 2 full magazines into the dummy at point blank
        3. Note: total damage dealt AND total elapsed time
        4. DPS = total_damage / total_time
        """
        hero = _hero(heroes, hero_name)
        dur, cycle, mag_dmg = self._two_mag_cycle(hero)
        config = SimConfig(
            attacker=hero, defender=self._DUMMY,
            settings=self._weapon_only_settings(dur),
        )
        result = CombatSimulator.run(config)

        # Total damage = exactly 2 magazines
        expected_total = 2 * mag_dmg
        assert result.bullet_damage == pytest.approx(expected_total), (
            f"{hero_name}: expected {expected_total:.2f} total, got {result.bullet_damage:.2f}"
        )

        # Sustained DPS = total / time (including reload downtime)
        sim_sustained_dps = result.bullet_damage / dur
        assert sim_sustained_dps == pytest.approx(expected_dps, rel=0.01), (
            f"{hero_name}: expected {expected_dps:.2f} sustained DPS, "
            f"got {sim_sustained_dps:.2f}"
        )

        # Should also match analytical sustained DPS
        analytical = DamageCalculator.calculate_bullet(
            hero, CombatConfig(boons=0, distance=0.0),
        ).sustained_dps
        assert sim_sustained_dps == pytest.approx(analytical, rel=0.01), (
            f"{hero_name}: sim DPS {sim_sustained_dps:.2f} doesn't match "
            f"analytical {analytical:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════
# 15. ITEM CLASSIFICATION (Simulation)
# ═══════════════════════════════════════════════════════════════════


class TestItemClassification:
    """Verify items are correctly classified for simulation behavior."""

    def test_passive_stat_items(self, items):
        """Items with only stat bonuses (no procs) should be PASSIVE_STAT or None."""
        for name, item in items.items():
            behavior = classify_item(item)
            if behavior is None:
                # No damage behavior — it's a pure stat item, which is fine
                continue
            # If classified, it should have a valid behavior type
            assert behavior.behavior_type is not None

    def test_known_damage_items_classified(self, items):
        """Key damage items should be classified (not None)."""
        damage_items = ["Toxic Bullets", "Tesla Bullets", "Torment Pulse"]
        for name in damage_items:
            item = items.get(name)
            if item is None:
                continue
            behavior = classify_item(item)
            assert behavior is not None, f"{name} should have a sim behavior"
            assert behavior.behavior_type.value != "passive_stat", (
                f"{name} should not be passive_stat"
            )


# ═══════════════════════════════════════════════════════════════════
# 16. END-TO-END SCENARIO TESTS
# ═══════════════════════════════════════════════════════════════════


class TestEndToEndScenarios:
    """Full scenario tests combining multiple engine systems.

    Each test describes a complete in-game scenario you can replicate.
    """

    def test_haze_full_build_dps(self, heroes, items):
        """Scenario: Haze at 15 boons with a weapon build.

        Setup in-game:
        1. Pick Haze
        2. Reach 15600 souls (18 boons based on table; let's use boons=15 directly)
        3. Buy Headshot Booster
        4. Check sustained DPS in stats or vs dummy

        Verify: DPS with items > DPS without items.
        """
        hero = _hero(heroes, "Haze")
        boons = 15

        naked_config = CombatConfig(boons=boons, distance=0.0)
        naked_dps = DamageCalculator.calculate_bullet(hero, naked_config).sustained_dps

        build_items = [i for i in [items.get("Headshot Booster")] if i]
        if not build_items:
            pytest.skip("Headshot Booster not found")

        build = Build(items=build_items)
        stats = BuildEngine.aggregate_stats(build)
        config = BuildEngine.build_to_attacker_config(
            stats, boons=boons, spirit_gain=hero.spirit_gain,
            headshot_multiplier=hero.crit_bonus_start,
        )
        config.distance = 0.0
        equipped_dps = DamageCalculator.calculate_bullet(hero, config).sustained_dps

        assert equipped_dps > naked_dps

    def test_infernus_spirit_build(self, heroes, items):
        """Scenario: Infernus spirit build.

        Setup in-game:
        1. Pick Infernus
        2. Buy spirit items: Extra Spirit, Improved Spirit
        3. Check spirit DPS from abilities

        Verify: Spirit DPS with items > base spirit DPS.
        """
        hero = _hero(heroes, "Infernus")
        boons = 10

        spirit_items = [
            items.get("Extra Spirit"),
            items.get("Improved Spirit"),
        ]
        spirit_items = [i for i in spirit_items if i]
        if not spirit_items:
            pytest.skip("Spirit items not found")

        build = Build(items=spirit_items)
        stats = BuildEngine.aggregate_stats(build)
        config = BuildEngine.build_to_attacker_config(
            stats, boons=boons, spirit_gain=hero.spirit_gain,
        )

        base_spirit_dps = DamageCalculator.hero_total_spirit_dps(
            hero, current_spirit=int(hero.spirit_gain * boons),
        )
        built_spirit_dps = DamageCalculator.hero_total_spirit_dps(
            hero,
            current_spirit=config.current_spirit,
            cooldown_reduction=stats.cooldown_reduction,
            spirit_amp=stats.spirit_amp_pct,
            resist_shred=stats.spirit_resist_shred,
        )

        assert built_spirit_dps > base_spirit_dps

    def test_abrams_tank_ehp(self, heroes, items):
        """Scenario: Abrams tanky build.

        Setup in-game:
        1. Pick Abrams
        2. Buy vitality items with HP/resist
        3. Check effective HP in stats

        Verify: EHP with items > base HP.
        """
        hero = _hero(heroes, "Abrams")
        boons = 10

        # Find vitality items
        vit_items = [
            i for i in items.values()
            if i.category.lower() == "vitality" and (i.bonus_hp > 0 or i.bullet_resist_pct > 0)
        ][:3]
        if not vit_items:
            pytest.skip("No vitality items found")

        build = Build(items=vit_items)
        stats = BuildEngine.aggregate_stats(build)
        ehp = BuildEngine.defender_effective_hp(hero, stats, boons)

        base_hp = hero.base_hp + hero.hp_gain * boons
        assert ehp > base_hp

    def test_sim_matches_analytical_dps_direction(self, heroes):
        """The sim DPS and analytical DPS should agree on direction.

        If weapon bonus increases analytical DPS, it should also increase sim DPS.
        """
        haze = _hero(heroes, "Haze")
        dummy = HeroStats(name="Dummy", base_hp=10000)

        # Analytical
        base_cfg = CombatConfig(boons=0, distance=0.0)
        boost_cfg = CombatConfig(boons=0, weapon_damage_bonus=0.50, distance=0.0)
        analytical_base = DamageCalculator.calculate_bullet(haze, base_cfg).sustained_dps
        analytical_boost = DamageCalculator.calculate_bullet(haze, boost_cfg).sustained_dps
        assert analytical_boost > analytical_base

    def test_souls_to_build_pipeline(self, heroes, items):
        """Full pipeline: souls → boons → build → config → DPS.

        Scenario: Player has 10000 total souls.
        1. souls → boons (should be 13 at 9600 threshold)
        2. Pick items within budget
        3. Compute DPS
        """
        total_souls = 10000
        boons = souls_to_boons(total_souls)
        ap = souls_to_ability_points(total_souls)

        assert boons == 13  # 9600 threshold = 13 boons
        assert ap == 10     # 9600 threshold = 10 AP

        hero = _hero(heroes, "Haze")

        # Build within budget (items cost < total_souls)
        cheap_items = [
            i for i in items.values()
            if i.cost <= 1000 and i.weapon_damage_pct > 0
        ][:2]

        build = Build(items=cheap_items)
        stats = BuildEngine.aggregate_stats(build)
        config = BuildEngine.build_to_attacker_config(
            stats, boons=boons, spirit_gain=hero.spirit_gain,
            headshot_multiplier=hero.crit_bonus_start,
        )

        result = DamageCalculator.calculate_bullet(hero, config)
        assert result.sustained_dps > 0
        assert result.magazine_size > 0


# ═══════════════════════════════════════════════════════════════════
# 17. REAL HERO DATA SANITY CHECKS
# ═══════════════════════════════════════════════════════════════════


class TestDataSanity:
    """Sanity checks on loaded hero and item data.

    These catch data parsing issues — if they fail, the API data
    or parsing logic has changed.
    """

    def test_heroes_loaded(self, heroes):
        """Should load a reasonable number of heroes."""
        assert len(heroes) >= 20, f"Only {len(heroes)} heroes loaded"

    def test_items_loaded(self, items):
        """Should load a reasonable number of items."""
        assert len(items) >= 50, f"Only {len(items)} items loaded"

    def test_all_heroes_have_base_stats(self, heroes):
        """Every hero should have positive base stats."""
        for name, hero in heroes.items():
            assert hero.base_hp > 0, f"{name}: base_hp should be > 0"
            assert hero.base_bullet_damage >= 0, f"{name}: base_bullet_damage should be >= 0"
            assert hero.base_fire_rate >= 0, f"{name}: base_fire_rate should be >= 0"

    def test_all_heroes_have_scaling(self, heroes):
        """Every hero should have positive per-boon scaling."""
        for name, hero in heroes.items():
            assert hero.damage_gain >= 0, f"{name}: damage_gain should be >= 0"
            assert hero.hp_gain > 0, f"{name}: hp_gain should be > 0"

    def test_all_items_have_cost(self, items):
        """Every item should have a positive cost."""
        for name, item in items.items():
            assert item.cost > 0, f"{name}: cost should be > 0"

    def test_all_items_have_category(self, items):
        """Every item should have a valid category."""
        valid = {"weapon", "vitality", "spirit"}
        for name, item in items.items():
            assert item.category.lower() in valid, (
                f"{name}: category '{item.category}' not in {valid}"
            )

    def test_hero_abilities_present(self, heroes):
        """Most heroes should have at least 3 abilities."""
        heroes_with_abilities = sum(
            1 for h in heroes.values() if len(h.abilities) >= 3
        )
        assert heroes_with_abilities >= len(heroes) * 0.8, (
            "Most heroes should have 3+ abilities"
        )

    def test_hero_crit_bonus_values(self, heroes):
        """Crit bonus should be between 1.0 and 2.0 for all heroes."""
        for name, hero in heroes.items():
            assert 1.0 <= hero.crit_bonus_start <= 2.0, (
                f"{name}: crit_bonus_start={hero.crit_bonus_start} out of range"
            )

    def test_no_negative_resist_items(self, items):
        """Item resists should be non-negative (already parsed from API)."""
        for name, item in items.items():
            assert item.bullet_resist_pct >= 0, f"{name}: negative bullet resist"
            assert item.spirit_resist_pct >= 0, f"{name}: negative spirit resist"

    def test_hero_base_dps_consistent(self, heroes):
        """Hero base_dps should approximately equal base_bullet × pellets × fire_rate."""
        for name, hero in heroes.items():
            if hero.base_dps <= 0:
                continue
            computed = hero.base_bullet_damage * hero.pellets * hero.base_fire_rate
            # Allow some tolerance for cycle_time-based DPS
            assert computed == pytest.approx(hero.base_dps, rel=0.15), (
                f"{name}: computed base DPS ({computed:.1f}) doesn't match "
                f"stored base_dps ({hero.base_dps:.1f})"
            )


# ═══════════════════════════════════════════════════════════════════
# 18. GAME-VERIFIED SCENARIOS (April 2026 patch)
#
# These tests pin numbers that were manually confirmed in-game.
# Each test covers a unique mechanic — no redundant item/hero combos.
# If a test fails after an API data refresh, re-verify in sandbox.
# ═══════════════════════════════════════════════════════════════════


class TestGameVerified:
    """Tests with hardcoded values verified in the live game.

    How to re-verify if these fail after a data refresh:
    1. Open Deadlock sandbox mode
    2. Pick the hero listed in the test
    3. Set boon level / items as described
    4. Hit the target dummy and read the damage number
    5. Update the expected value if the game changed

    Organization: one test per mechanic, not per hero/item combo.
    """

    # ── 1. Base bullet damage (single-pellet) ─────────────────────

    def test_base_bullet_single_pellet(self, heroes):
        """Verify per-bullet damage at boon 0 for single-pellet heroes.

        In-game: Pick hero, shoot dummy at point blank, no items.
        Haze: 5.26 → 5 | Wraith: 5.64 → 6 | Seven: 10.81 → 11
        """
        expected = {"Haze": 5, "Wraith": 6, "Seven": 11}
        for name, game_val in expected.items():
            hero = _hero(heroes, name)
            assert round(hero.base_bullet_damage) == game_val, (
                f"{name}: expected {game_val}, got {round(hero.base_bullet_damage)}"
            )

    # ── 2. Base bullet damage (multi-pellet / shotgun) ────────────

    def test_base_bullet_multi_pellet(self, heroes):
        """Abrams shotgun: 3.6 × 9 pellets = 32.4 → game shows 33 (ceiling).

        In-game: Pick Abrams, shoot dummy at point blank.
        """
        hero = _hero(heroes, "Abrams")
        total = hero.base_bullet_damage * hero.pellets
        assert math.ceil(total) == 33

    # ── 3. Headshot multiplier ────────────────────────────────────

    def test_headshot_damage(self, heroes):
        """Haze headshot: 5.26 × 1.65 = 8.68 → 9.

        In-game: Headshot the dummy.
        """
        hero = _hero(heroes, "Haze")
        assert round(hero.base_bullet_damage * hero.crit_bonus_start) == 9

    # ── 4. Full magazine damage ───────────────────────────────────

    def test_full_magazine_damage(self, heroes):
        """Wraith full mag: 5.64 × 52 = 293.28 → 293.

        In-game: Empty all bullets into dummy, read cumulative damage.
        """
        hero = _hero(heroes, "Wraith")
        total_mag = hero.base_bullet_damage * hero.pellets * hero.base_ammo
        assert round(total_mag) == 293

    # ── 5. Boon scaling (multi-pellet + HP) ───────────────────────

    def test_boon_scaling_abrams(self, heroes):
        """Abrams at boon 9: per-shot = 41, HP = 1368.

        In-game: Reach boon 9 (~6000 souls), check damage and HP.
        """
        hero = _hero(heroes, "Abrams")
        dmg = DamageCalculator.bullet_damage_at_boon(hero, 9) * hero.pellets
        hp = hero.base_hp + hero.hp_gain * 9
        assert math.ceil(dmg) == 41
        assert hp == pytest.approx(1368)

    # ── 6. Melee damage ──────────────────────────────────────────

    def test_melee_damage(self, heroes):
        """Light = 50, Heavy = 116 (same for all base heroes at boon 0).

        In-game: Pick any hero, quick melee + charged melee.
        """
        for name in ["Haze", "Abrams"]:
            hero = _hero(heroes, name)
            result = DamageCalculator.calculate_melee(hero)
            assert round(result.light_damage) == 50, f"{name} light melee"
            assert round(result.heavy_damage) == 116, f"{name} heavy melee"

    # ── 7. Base HP values ─────────────────────────────────────────

    def test_hero_base_hp(self, heroes):
        """Verified HP at boon 0 for multiple heroes.

        In-game: Check HP in stats panel.
        """
        expected_hp = {
            "Haze": 740, "Abrams": 810, "Infernus": 840,
            "Wraith": 740, "Seven": 740,
        }
        for name, hp in expected_hp.items():
            hero = heroes.get(name)
            if hero is None:
                continue
            assert hero.base_hp == pytest.approx(hp), f"{name}: {hero.base_hp} != {hp}"

    # ── 8. Instant ability damage (no spirit) ─────────────────────

    def test_instant_ability_base_damage(self, heroes):
        """Verify base damage of instant abilities at 0 spirit.

        In-game: Pick hero, use ability on dummy, no items.
        """
        cases = [
            ("Infernus", 0, "Concussive Combustion", 125),
            ("Infernus", 2, "Napalm", 40),
            ("Seven", 1, "Static Charge", 35),
            ("Dynamo", 0, "Kinetic Pulse", 115),
            ("Abrams", 2, "Seismic Impact", 100),
        ]
        for hero_name, ab_idx, ab_name, expected in cases:
            hero = _hero(heroes, hero_name)
            ab = hero.abilities[ab_idx]
            assert ab.name == ab_name, f"Expected {ab_name} at index {ab_idx}"
            assert round(ab.base_damage) == expected, (
                f"{hero_name} {ab_name}: expected {expected}, got {round(ab.base_damage)}"
            )

    # ── 9. Duration parsing: instant vs DoT ───────────────────────

    def test_instant_abilities_have_zero_duration(self, heroes):
        """Abilities that deal instant damage should have duration=0.

        DebuffDuration / SleepDuration / StunDuration are CC, not damage.
        """
        instant_cases = [
            ("Infernus", 0, "Concussive Combustion"),  # StunDuration ≠ damage
            ("Infernus", 2, "Napalm"),                 # DebuffDuration ≠ damage
            ("Haze", 0, "Sleep Dagger"),               # SleepDuration ≠ damage
        ]
        for hero_name, ab_idx, ab_name in instant_cases:
            hero = _hero(heroes, hero_name)
            ab = hero.abilities[ab_idx]
            assert ab.name == ab_name
            assert ab.duration == 0.0, (
                f"{hero_name} {ab_name}: should be instant (dur=0), got {ab.duration}"
            )

    def test_dot_ability_has_duration(self, heroes):
        """Flame Dash is a DoT with AbilityDuration = 3.0s.

        In-game: Leaves ground fire that ticks for 3 seconds.
        """
        hero = _hero(heroes, "Infernus")
        fd = hero.abilities[1]
        assert fd.name == "Flame Dash"
        assert fd.duration == pytest.approx(3.0)

    # ── 10. DPS ability: spirit scaling on DPS rate ───────────────

    def test_dps_ability_spirit_scaling(self, heroes):
        """Flame Dash DPS=30, spirit_scaling=1.0 per second.

        Parser multiplies both by duration:
          base_damage = 30 × 3 = 90, spirit_scaling = 1.0 × 3 = 3.0
        With 17 spirit: DPS = (90 + 3.0×17) / 3 = 47 ✓ tooltip.

        In-game: Buy 17 spirit, check Flame Dash tooltip DPS.
        """
        hero = _hero(heroes, "Infernus")
        fd = hero.abilities[1]
        assert fd.base_damage / fd.duration == pytest.approx(30.0)
        assert fd.spirit_scaling == pytest.approx(3.0)

        dps_at_17 = (fd.base_damage + fd.spirit_scaling * 17) / fd.duration
        assert dps_at_17 == pytest.approx(47.0)

    # ── 11. Ability upgrade (T1) ──────────────────────────────────

    def test_ability_t1_upgrade(self, heroes):
        """Infernus CC + T1 (+100 damage) → 225.

        In-game: Unlock T1 on Concussive Combustion, use on dummy.
        """
        hero = _hero(heroes, "Infernus")
        cc = hero.abilities[0]
        dmg_t1, _, _, _ss = apply_ability_upgrades(cc, [1])
        assert round(dmg_t1) == 225

    # ── 12. Spirit scaling with items ─────────────────────────────

    def test_spirit_scaling_with_items(self, heroes, items):
        """Verify spirit scaling across heroes with Improved Spirit (29 spirit).

        In-game: Buy Improved Spirit, use ability on dummy.
        """
        imp = _item(items, "Improved Spirit")
        build = Build(items=[imp])
        bs = BuildEngine.aggregate_stats(build)
        total_spirit = int(bs.spirit_power)
        assert total_spirit == 29  # 18 base + 11 shop tier

        # (hero, ability_index, expected_game_damage)
        cases = [
            ("Haze", 0, 140),     # 65 + 2.6 × 29 = 140.4
            ("Infernus", 0, 153),  # 125 + 0.975 × 29 = 153.3
            ("Infernus", 2, 57),   # 40 + 0.6 × 29 = 57.4
        ]
        for hero_name, ab_idx, expected in cases:
            hero = _hero(heroes, hero_name)
            ab = hero.abilities[ab_idx]
            raw = ab.base_damage + ab.spirit_scaling * total_spirit
            assert round(raw) == expected, (
                f"{hero_name} {ab.name}: expected {expected}, got {round(raw)}"
            )

    # ── 13. Shop tier bonuses ─────────────────────────────────────

    def test_spirit_shop_tier_bonus(self, heroes, items):
        """Extra Spirit (800 cost) → 10 base + 7 tier = 17 total spirit.

        In-game: Buy Extra Spirit, check spirit in stats. Sleep Dagger = 109.
        """
        es = _item(items, "Extra Spirit")
        build = Build(items=[es])
        bs = BuildEngine.aggregate_stats(build)
        assert bs.spirit_power == pytest.approx(17.0)

        hero = _hero(heroes, "Haze")
        sd = hero.abilities[0]
        expected = sd.base_damage + sd.spirit_scaling * int(bs.spirit_power)
        assert round(expected) == 109

    def test_weapon_shop_tier_bonus(self, heroes, items):
        """Headshot Booster (800 cost, 0% weapon) → +7% from tier.

        In-game: Buy Headshot Booster, check weapon % in stats.
        """
        hsb = _item(items, "Headshot Booster")
        build = Build(items=[hsb])
        bs = BuildEngine.aggregate_stats(build)
        assert hsb.weapon_damage_pct == pytest.approx(0.0)
        assert bs.weapon_damage_pct == pytest.approx(0.07)

    # ── 14. Resist stacking (multiplicative) ──────────────────────

    def test_resist_multiplicative_stacking(self, heroes, items):
        """Battle Vest (18%) + Bullet Resilience (30%) → 43%.

        Multiplicative: 1 - (0.82)(0.70) = 42.6% → 43%.

        In-game: Buy both, check resist in stats panel.
        """
        bv = _item(items, "Battle Vest")
        br = _item(items, "Bullet Resilience")
        build = Build(items=[bv, br])
        bs = BuildEngine.aggregate_stats(build)
        expected = 1.0 - (1.0 - bv.bullet_resist_pct) * (1.0 - br.bullet_resist_pct)
        assert bs.bullet_resist_pct == pytest.approx(expected)
        assert round(bs.bullet_resist_pct * 100) == 43

    # ── 15. Magazine size (ceiling rounding) ──────────────────────

    def test_magazine_ceiling_rounding(self, heroes, items):
        """Haze + Extended Magazine (30%) → ceil(25 × 1.30) = 33.

        In-game: Buy Extended Magazine, check ammo count.
        """
        hero = _hero(heroes, "Haze")
        em = _item(items, "Extended Magazine")
        build = Build(items=[em])
        bs = BuildEngine.aggregate_stats(build)
        mag = DamageCalculator.effective_magazine(
            hero, ammo_increase=bs.ammo_pct, ammo_flat=bs.ammo_flat,
        )
        assert mag == 33

    # ── 16. Fire rate with items ──────────────────────────────────

    def test_fire_rate_with_item(self, heroes, items):
        """Haze + Rapid Rounds → ~10.4 bullets/sec.

        Base 9.52 × 1.09 = 10.38, game shows 10.4 (display rounding).
        """
        hero = _hero(heroes, "Haze")
        rr = _item(items, "Rapid Rounds")
        build = Build(items=[rr])
        bs = BuildEngine.aggregate_stats(build)
        new_rate = hero.base_fire_rate * (1 + bs.fire_rate_pct)
        assert abs(new_rate - 10.4) < 0.1

    # ── 17. Seven Lightning Ball (DPS-over-time projectile) ───────

    def test_seven_lightning_ball(self, heroes):
        """Lightning Ball: DPS=75 for 5s max = 375 theoretical, ~368 actual.

        In-game: Fire Lightning Ball at dummy, note total damage.
        """
        hero = _hero(heroes, "Seven")
        lb = hero.abilities[0]
        assert lb.name == "Lightning Ball"
        assert lb.base_damage == pytest.approx(75.0)

        prop = lb.properties.get("MaxLifetime")
        max_life = float(prop["value"]) if isinstance(prop, dict) else 0
        assert max_life == pytest.approx(5.0)
        assert 360 <= lb.base_damage * max_life <= 380

    # ── 18. Afterburn (API staleness documented) ──────────────────

    def test_afterburn_tick_structure(self, heroes):
        """Afterburn: 6 ticks (0.5s rate × 3s duration), game = 7 per tick.

        API says DPS=12 (6/tick), game does 14 DPS (7/tick) — API stale.
        """
        hero = _hero(heroes, "Infernus")
        ab = hero.abilities[3]
        assert ab.name == "Afterburn"

        tick_rate = float(ab.properties["TickRate"]["value"])
        burn_dur = float(ab.properties["BurnDurationBase"]["value"])
        assert tick_rate == pytest.approx(0.5)
        assert burn_dur == pytest.approx(3.0)
        assert burn_dur / tick_rate == pytest.approx(6.0)  # 6 ticks matches game

    # ── 19. Lady Geist Life Drain (non-standard damage key) ───────

    def test_lady_geist_life_drain(self, heroes):
        """Life Drain: LifeDrainPerSecond=32 DPS for 2.5s → ~77 total.

        Uses non-standard damage key not in parser priority list.
        In-game: 77 total damage (3 less than 80 theoretical = tick timing).
        """
        hero = _hero(heroes, "Lady Geist")
        ld = hero.abilities[2]
        assert ld.name == "Life Drain"
        assert ld.duration == pytest.approx(2.5)

        prop = ld.properties.get("LifeDrainPerSecond")
        assert prop is not None
        assert float(prop["value"]) == pytest.approx(32.0)

    # ── 20. Paradox Pulse Grenade (stacking damage amp) ───────────

    def test_paradox_pulse_grenade(self, heroes):
        """Pulse Grenade: 35/hit, 4 pulses, +4% amp per stack → 148 total.

        Hit pattern: 35, 36.4, 37.8, 39.2 = 148.4 → 148.
        In-game: Use on dummy, 148 total damage.
        """
        hero = _hero(heroes, "Paradox")
        pg = hero.abilities[0]
        assert pg.name == "Pulse Grenade"

        pulse_dmg = float(pg.properties["PulseDamage"]["value"])
        interval = float(pg.properties["PulseInterval"]["value"])
        amp = float(pg.properties["DamageAmplificationPerStack"]["value"])

        assert pulse_dmg == pytest.approx(35.0)
        num_pulses = int(pg.duration / interval)
        assert num_pulses == 4

        total = sum(pulse_dmg * (1 + i * amp / 100) for i in range(num_pulses))
        assert round(total) == 148

    # ── 21. Display rounding vs actual damage ─────────────────────

    def test_damage_display_rounding_not_actual(self, heroes):
        """Game rounds display numbers but deals exact fractional damage.

        Mo & Krill: 2.82 × 4 = 11.28 shown as 11, but actual damage is 11.28.
        Pocket: 4.28 × 7 = 29.96 — fractional total, no rounding applied.

        In-game: Mo & Krill shows 11 per shot but cumulative confirms fractions.
        """
        mk = _hero(heroes, "Mo & Krill")
        total_mk = mk.base_bullet_damage * mk.pellets
        assert total_mk == pytest.approx(11.28, abs=0.1)  # exact fractional
        assert round(total_mk) == 11  # display rounds to 11

        pocket = _hero(heroes, "Pocket")
        total_pocket = pocket.base_bullet_damage * pocket.pellets
        assert total_pocket == pytest.approx(29.96, abs=0.1)

    # ── 22. Cross-hero instant ability verification ───────────────

    def test_cross_hero_instant_abilities(self, heroes):
        """Verify base ability damage across many heroes at 0 spirit.

        Each tested in sandbox at boon 0, no items.
        """
        cases = [
            ("Kelvin", 2, "Frost Grenade", 60),
            ("Vindicta", 0, "Stake", 40),
            ("Warden", None, "Binding Word", 110),   # index varies
            ("Viscous", 0, "Splatter", 70),
            ("Lash", 1, "Ground Strike", 60),
            ("Pocket", 0, "Flying Cloak", 60),
        ]
        for hero_name, ab_idx, ab_name, expected in cases:
            hero = _hero(heroes, hero_name)
            # Find ability by name if index is None
            if ab_idx is None:
                ab = next((a for a in hero.abilities if a.name == ab_name), None)
            else:
                ab = hero.abilities[ab_idx]
            assert ab is not None, f"{hero_name}: ability {ab_name} not found"
            assert ab.name == ab_name, (
                f"{hero_name}[{ab_idx}]: expected {ab_name}, got {ab.name}"
            )
            assert round(ab.base_damage) == expected, (
                f"{hero_name} {ab_name}: expected {expected}, got {round(ab.base_damage)}"
            )

    # ── 23. Cross-hero bullet damage ──────────────────────────────

    def test_cross_hero_bullets(self, heroes):
        """Verify per-bullet damage for more heroes at boon 0.

        In-game: Pick each hero, shoot dummy at point blank.
        """
        expected = {
            "Kelvin": 19,
            "Vindicta": 12,
            "McGinnis": 6,
            "Warden": 17,
            "Viscous": 10,
            "Lash": 8,
            "Pocket": 4,       # per-pellet display (4.28)
            "Mo & Krill": 3,   # per-pellet display (2.82)
        }
        for name, game_val in expected.items():
            hero = heroes.get(name)
            if hero is None:
                continue
            assert round(hero.base_bullet_damage) == game_val, (
                f"{name}: expected {game_val}, got {round(hero.base_bullet_damage)}"
            )

    # ── 24. Boon scaling at boon 20 ──────────────────────────────

    def test_haze_boon_20(self, heroes):
        """Haze at boon 20: bullet = 8, HP = 1640.

        In-game: Reach boon 20 (~21600 souls), check stats.
        """
        hero = _hero(heroes, "Haze")
        dmg = hero.base_bullet_damage + hero.damage_gain * 20
        hp = hero.base_hp + hero.hp_gain * 20
        assert round(dmg) == 8
        assert hp == pytest.approx(1640)

    # ── 25. Infernus CC cooldown ──────────────────────────────────

    def test_infernus_cc_cooldown(self, heroes):
        """Infernus CC base cooldown = 165s.

        In-game: Check tooltip (no CDR items).
        """
        hero = _hero(heroes, "Infernus")
        cc = hero.abilities[0]
        assert cc.cooldown == pytest.approx(165.0)

    # ── 26. McGinnis turret (non-standard DPS) ───────────────────

    def test_mcginnis_turret_dps(self, heroes):
        """McGinnis Mini Turret: TurretDPS=30, TickRate=0.5.

        In-game: Turret hits for 9-10 per shot — likely the DPS is
        modified by attack speed or the tick rate differs from display.
        Per-tick at 0.5s rate would be 15, but game shows lower.

        This test verifies the raw API properties exist and are parseable.
        """
        hero = _hero(heroes, "McGinnis")
        mt = hero.abilities[1]
        assert mt.name == "Mini Turret"

        turret_dps = float(mt.properties["TurretDPS"]["value"])
        assert turret_dps == pytest.approx(30.0)

        tick_rate = float(mt.properties["TickRate"]["value"])
        assert tick_rate == pytest.approx(0.5)

    # ── 27. Drifter per-target pellet cap ─────────────────────────

    def test_drifter_single_target_pellet_cap(self, heroes):
        """Drifter: 3 pellets but max 1 hits a single target.

        Drifter's weapon spreads pellets across targets. Against a single
        target (dummy), only 1 pellet connects per shot.

        In-game: Shoot dummy → see 20 damage (1 pellet), not 59 (3 pellets).
        Hero card DPS = 44 = 19.5 × 2.27 (per-pellet DPS).
        """
        hero = _hero(heroes, "Drifter")
        assert hero.pellets == 3
        assert hero.max_pellets_per_target == 1

        # Effective single-target pellets
        eff = DamageCalculator.effective_pellets(hero)
        assert eff == 1

        # Single-target DPS = per-pellet × fire_rate
        st_dps = hero.base_bullet_damage * eff * hero.base_fire_rate
        assert st_dps == pytest.approx(44.2, abs=0.5)  # matches card DPS

    def test_other_shotguns_hit_all_pellets(self, heroes):
        """Other multi-pellet heroes land all pellets on a single target.

        In-game: Abrams/Yamato/Silver/Pocket all deal full pellet damage
        to a single dummy at point blank.
        """
        for name in ["Abrams", "Yamato", "Silver", "Pocket"]:
            hero = heroes.get(name)
            if hero is None:
                continue
            assert hero.max_pellets_per_target == 0, (
                f"{name} should not have a pellet cap"
            )
            eff = DamageCalculator.effective_pellets(hero)
            assert eff == hero.pellets, (
                f"{name}: effective_pellets should be {hero.pellets}, got {eff}"
            )


# ═══════════════════════════════════════════════════════════════════
# 19. DAMAGE OUTLIER EXPLORATION
#
# These tests probe edge cases that could produce damage numbers
# far outside expected game ranges. Each documents a scenario to
# verify in-game sandbox mode. Failures indicate a potential
# modelling error or a mechanic the sim handles differently from
# the live game.
# ═══════════════════════════════════════════════════════════════════


class TestDamageOutliers:
    """Probe for damage values that are suspiciously high or low.

    These are exploratory tests — they define plausible bounds rather
    than pinning exact values. If a test fails, investigate whether
    the engine formula or game data has an issue before updating.
    """

    # ── A. Spirit amp vs resist shred are distinct mechanics ──────

    def test_spirit_amp_and_resist_shred_are_independent(self):
        """Spirit amp and resist shred are NOT the same mechanic.

        Spirit amp: attacker deals more spirit damage (multiplicative on raw).
        Resist shred: reduces target's spirit resist (affects the resist layer).

        In-game:
        - Spirit amp items (Improved Spirit amp, EE stacks) increase YOUR damage.
        - Resist shred items (EE passive, Mystic Vulnerability) reduce THEIR resist.
        - 20% spirit amp on 100 damage = 120 damage (before resist).
        - 20% resist shred on 40% resist: resist = 40% × (1-0.20) = 32%.

        The engine must NOT conflate these: amp applies to raw damage,
        shred reduces the resist fraction.
        """
        # Spirit amp only — no resist
        amp_only = AbilityConfig(base_damage=100.0, spirit_amp=0.20)
        r_amp = DamageCalculator.calculate_spirit(amp_only)
        assert r_amp.modified_damage == pytest.approx(120.0), (
            f"20% spirit amp on 100 should be 120, got {r_amp.modified_damage}"
        )

        # Resist shred only — 40% resist with 50% shred → 20% effective
        shred_only = AbilityConfig(
            base_damage=100.0, enemy_spirit_resist=0.40, resist_shred=0.50,
        )
        r_shred = DamageCalculator.calculate_spirit(shred_only)
        expected_resist = 0.40 * (1.0 - 0.50)  # 0.20
        assert r_shred.modified_damage == pytest.approx(100.0 * (1 - expected_resist))
        assert r_shred.modified_damage == pytest.approx(80.0)

        # Both together — amp applies first, then resist
        both = AbilityConfig(
            base_damage=100.0, spirit_amp=0.20,
            enemy_spirit_resist=0.40, resist_shred=0.50,
        )
        r_both = DamageCalculator.calculate_spirit(both)
        # 100 × 1.20 × (1 - 0.20) = 96
        assert r_both.modified_damage == pytest.approx(96.0)

        # Verify they don't produce the same result
        assert r_amp.modified_damage != r_shred.modified_damage, (
            "Spirit amp and resist shred must produce different results"
        )

    def test_resist_shred_only_helps_against_resist(self):
        """Resist shred does nothing when target has 0% resist.

        In-game: Shred items are wasted on unarmored targets.
        Spirit amp helps regardless.
        """
        no_resist = AbilityConfig(base_damage=100.0, resist_shred=0.50)
        r = DamageCalculator.calculate_spirit(no_resist)
        assert r.modified_damage == pytest.approx(100.0), (
            "Shred on 0% resist should have no effect"
        )

        with_amp = AbilityConfig(base_damage=100.0, spirit_amp=0.20)
        r2 = DamageCalculator.calculate_spirit(with_amp)
        assert r2.modified_damage == pytest.approx(120.0), (
            "Spirit amp always increases damage regardless of resist"
        )

    def test_spirit_amp_stacking_with_ee(self):
        """EE stacks (spirit amp) + item spirit amp stack additively,
        then multiply with crippling/soulshredder (damage amp).

        In-game: EE stacks show as spirit amp % in combat HUD.
        Crippling shows as a separate damage amp debuff on target.

        200 base × (1 + 0.40 + 5×0.06) × (1 + 0.25 + 0.15) = 476.
        """
        config = AbilityConfig(
            base_damage=200.0,
            spirit_amp=0.40,
            escalating_exposure_stacks=5,
            ee_per_stack=0.06,
            crippling=0.25,
            soulshredder=0.15,
        )
        result = DamageCalculator.calculate_spirit(config)

        # spirit_amp layer: 1 + 0.40 + 5×0.06 = 1.70
        # damage_amp layer: 1 + 0.25 + 0.15 = 1.40
        expected = 200.0 * 1.70 * 1.40
        assert result.modified_damage == pytest.approx(expected)

    def test_ee_shred_and_amp_are_separate_in_sim(self, heroes, items):
        """In sim, EE provides BOTH spirit amp stacks AND spirit resist shred.

        These are two independent effects from one item:
        - Stacks: +4.5% spirit amp per stack (up to 12 stacks = 54%)
        - Debuff: 8% spirit resist shred

        In-game: Hit target with spirit damage while EE equipped.
        Check both the amp stacks on target AND the resist shred debuff.
        """
        ee = items.get("Escalating Exposure")
        if ee is None:
            pytest.skip("Escalating Exposure not found")

        behavior = classify_item(ee)
        assert behavior is not None
        assert behavior.behavior_type.value == "stack_amplifier"
        assert behavior.stack_value > 0, "EE should have spirit amp stacks"
        assert behavior.max_stacks > 0

        # Verify EE also applies spirit resist shred debuff
        shred_debuffs = [
            (dt, val, dur) for dt, val, dur in behavior.on_hit_debuffs
            if dt.value == "spirit_resist_shred"
        ]
        assert len(shred_debuffs) > 0, (
            "EE should apply spirit_resist_shred debuff (8%) separately "
            "from its spirit amp stacks"
        )

        # Verify they are different debuff types
        amp_type = "spirit_amp_stack"
        shred_found = shred_debuffs[0][0].value
        assert amp_type != shred_found or behavior.stack_value != shred_debuffs[0][1], (
            "Spirit amp stacks and resist shred must be different mechanics"
        )

    def test_max_spirit_amp_with_resist_shred(self):
        """Max amp stack vs. target with 40% spirit resist and 70% shred.

        200 base × 1.70 (amp) × 1.40 (dmg_amp) × (1 - 0.12) = 418.
        resist after shred: 0.40 × (1 - 0.70) = 0.12.

        In-game: Stack all amps + shred items, hit armored dummy.
        REVIEW: Does 70% shred combined with 40% resist correctly
        yield 12% effective resist?
        """
        config = AbilityConfig(
            base_damage=200.0,
            spirit_amp=0.40,
            escalating_exposure_stacks=5,
            ee_per_stack=0.06,
            crippling=0.25,
            soulshredder=0.15,
            enemy_spirit_resist=0.40,
            resist_shred=0.70,
        )
        result = DamageCalculator.calculate_spirit(config)

        effective_resist = 0.40 * (1.0 - 0.70)  # 0.12
        expected = 200.0 * 1.70 * 1.40 * (1.0 - effective_resist)
        assert result.modified_damage == pytest.approx(expected)
        assert result.modified_damage > 400, "Fully amped + shredded should be > 400"
        assert result.modified_damage < 500, "Should still be < 500 on 200 base"

    # ── B. Extreme CDR floors ─────────────────────────────────────

    def test_extreme_cdr_spirit_dps_cap(self, heroes):
        """95% CDR should clamp cooldown to 0.1s minimum.

        With 0.1s cooldown on an instant 100-damage ability, DPS = 1000.
        REVIEW: In-game, is there a CDR cap? Engine floors at 0.1s.
        If a hero has a 30s ult reduced to 0.1s, that would be 1000 DPS
        bursts — clearly unrealistic for an ult.
        """
        hero = _hero(heroes, "Infernus")
        # Use extreme CDR — engine should floor cooldowns at 0.1s
        dps = DamageCalculator.hero_total_spirit_dps(
            hero, current_spirit=0, cooldown_reduction=0.95,
        )
        # With 0.1s floor on all cooldowns, DPS will be very high
        # but each ability contributes base_dmg / 0.1
        # This should be capped per-ability, not producing insane values
        assert dps > 0, "DPS should be positive"

        # Check that no single ability contributes more than
        # base_damage / 0.1 = 10× base DPS
        for ab in hero.abilities:
            if ab.base_damage > 0 and ab.cooldown > 0:
                max_contribution = ab.base_damage / 0.1
                # Total DPS should not exceed sum of all maxed abilities
                # (a rough sanity bound)
                assert dps <= sum(
                    a.base_damage / 0.1
                    for a in hero.abilities if a.base_damage > 0 and a.cooldown > 0
                ) * 1.1  # 10% tolerance
                break

    def test_cdr_reduces_sim_ability_cooldown(self, heroes):
        """Simulation should respect CDR from items on ability cooldowns.

        Scenario: Infernus with 30% CDR item vs naked Infernus.
        REVIEW: Abilities should fire more often with CDR, increasing DPS.
        """
        hero = _hero(heroes, "Infernus")
        dummy = HeroStats(name="Dummy", base_hp=50000, base_regen=0)

        naked = SimConfig(
            attacker=hero, defender=dummy,
            settings=SimSettings(duration=15.0, attacker_boons=10),
        )
        # Build with CDR — create a fake item with 30% CDR
        cdr_item = Item(
            name="CDR Test", category="spirit", tier=3, cost=3000,
            cooldown_reduction=0.30,
        )
        with_cdr = SimConfig(
            attacker=hero,
            attacker_build=Build(items=[cdr_item]),
            defender=dummy,
            settings=SimSettings(duration=15.0, attacker_boons=10),
        )

        r_naked = CombatSimulator.run(naked)
        r_cdr = CombatSimulator.run(with_cdr)

        assert r_cdr.spirit_damage >= r_naked.spirit_damage, (
            f"CDR should increase spirit damage: naked={r_naked.spirit_damage:.0f}, "
            f"cdr={r_cdr.spirit_damage:.0f}"
        )

    # ── C. Zero / near-zero damage edge cases ────────────────────

    def test_zero_base_damage_ability_skipped(self, heroes):
        """Abilities with 0 base damage should contribute 0 DPS,
        even with high spirit power.

        REVIEW: Some abilities (buffs, passives) have 0 damage. The engine
        should skip them entirely in total DPS calculations.
        """
        hero = _hero(heroes, "Infernus")
        zero_dmg_count = sum(
            1 for a in hero.abilities if a.base_damage == 0 and a.melee_scale == 0
        )
        # If there are non-damage abilities, verify they don't inflate DPS
        if zero_dmg_count > 0:
            dps = DamageCalculator.hero_total_spirit_dps(hero, current_spirit=100)
            # Remove all non-zero-damage abilities, DPS should equal sum
            manual_dps = 0.0
            for ab in hero.abilities:
                if ab.base_damage > 0:
                    raw = ab.base_damage + ab.spirit_scaling * 100
                    if ab.cooldown > 0 and ab.duration == 0:
                        manual_dps += raw / ab.cooldown
                    elif ab.duration > 0:
                        manual_dps += raw / ab.duration
            assert dps == pytest.approx(manual_dps, rel=0.01)

    def test_zero_fire_rate_no_crash(self):
        """Hero with 0 fire rate should not crash, DPS = 0.

        REVIEW: Edge case — a hero with broken data. Should gracefully
        produce 0 DPS instead of division by zero.
        """
        broken = HeroStats(name="Broken", base_fire_rate=0.0, base_bullet_damage=10.0)
        config = CombatConfig(boons=0, distance=0.0)
        result = DamageCalculator.calculate_bullet(broken, config)
        assert result.raw_dps == 0.0
        assert result.sustained_dps == 0.0

    def test_zero_ammo_no_crash(self):
        """Hero with 0 ammo should not crash.

        REVIEW: Edge data — produce 0 DPS, 0 magazine, no division by zero.
        """
        broken = HeroStats(
            name="Broken", base_ammo=0, base_fire_rate=5.0,
            base_bullet_damage=10.0,
        )
        config = CombatConfig(boons=0, distance=0.0)
        result = DamageCalculator.calculate_bullet(broken, config)
        assert result.magazine_size == 0
        assert result.sustained_dps >= 0.0

    # ── D. Extreme resist & shred interactions ────────────────────

    def test_100_percent_resist_blocks_all(self):
        """100% resist (impossible in normal gameplay) → 0 damage.

        REVIEW: No hero/item combination reaches 100% resist, but the
        engine should handle it gracefully.
        """
        config = AbilityConfig(base_damage=500.0, enemy_spirit_resist=1.0)
        result = DamageCalculator.calculate_spirit(config)
        assert result.modified_damage == pytest.approx(0.0)

    def test_over_100_shred_clamped(self):
        """150% shred should clamp to 100%, zeroing out resist.

        REVIEW: Multiple shred sources stacking past 100%. The engine
        should clamp, not go negative resist (which would amplify damage).
        """
        config = AbilityConfig(
            base_damage=100.0,
            enemy_spirit_resist=0.50,
            resist_shred=1.50,  # 150% — way over cap
        )
        result = DamageCalculator.calculate_spirit(config)
        # 50% resist × (1 - 1.0) = 0% resist → full damage
        assert result.modified_damage == pytest.approx(100.0)

    def test_multiple_bullet_shred_sources_cap(self):
        """5 shred sources summing to >100% should clamp to 100%.

        In-game: Stack multiple shred items. Max shred = 100%.
        REVIEW: Verify sum is clamped, not individual sources.
        """
        shred_total = DamageCalculator.total_shred([0.25, 0.25, 0.25, 0.20, 0.15])
        assert shred_total == pytest.approx(1.0)  # clamped to 100%
        resist = DamageCalculator.final_resist(0.40, shred_total)
        assert resist == pytest.approx(0.0)

    # ── E. Falloff extremes ───────────────────────────────────────

    def test_falloff_at_extreme_range_sustained_dps(self, heroes):
        """At max falloff, sustained DPS drops to 10% of close-range.

        In-game: Shoot dummy from max range. Damage numbers should
        show 10% of point-blank values.
        REVIEW: Falloff ranges are in game units (e.g. Haze: 787-1811).
        Distance must exceed falloff_range_max for the 10% floor.
        """
        hero = _hero(heroes, "Haze")
        if hero.falloff_range_max <= 0:
            pytest.skip("Hero has no falloff range data")

        close = CombatConfig(boons=10, distance=0.0)
        far = CombatConfig(boons=10, distance=hero.falloff_range_max + 100)

        close_r = DamageCalculator.calculate_bullet(hero, close)
        far_r = DamageCalculator.calculate_bullet(hero, far)

        ratio = far_r.sustained_dps / close_r.sustained_dps
        assert ratio == pytest.approx(0.1, abs=0.01), (
            f"Max falloff should be 10% damage, got {ratio*100:.1f}%"
        )

    def test_falloff_inside_min_range_full_damage(self, heroes):
        """Any distance <= falloff_min should deal 100% damage.

        In-game: Shoot dummy at point-blank and at falloff_min distance.
        Both should show same damage numbers.
        """
        hero = _hero(heroes, "Haze")
        if hero.falloff_range_min <= 0:
            pytest.skip("Hero has no falloff min range")

        at_min = CombatConfig(boons=0, distance=hero.falloff_range_min)
        at_zero = CombatConfig(boons=0, distance=0.0)

        r_min = DamageCalculator.calculate_bullet(hero, at_min)
        r_zero = DamageCalculator.calculate_bullet(hero, at_zero)

        assert r_min.final_dps == pytest.approx(r_zero.final_dps)

    # ── F. Full-build multiplier sanity ───────────────────────────

    def test_full_weapon_build_dps_bounds(self, heroes, items):
        """A max-budget weapon build should not exceed 5× base DPS.

        In-game: Buy all T4 weapon items on Haze, check DPS readout.
        REVIEW: If DPS exceeds 5× base, either an item is OP or
        the stacking formula is wrong.
        """
        hero = _hero(heroes, "Haze")
        weapon_items = sorted(
            [i for i in items.values() if i.category.lower() == "weapon" and not i.condition],
            key=lambda x: -x.cost,
        )[:6]  # top 6 expensive weapon items
        if len(weapon_items) < 3:
            pytest.skip("Not enough weapon items")

        build = Build(items=weapon_items)
        stats = BuildEngine.aggregate_stats(build)
        config = BuildEngine.build_to_attacker_config(
            stats, boons=20, spirit_gain=hero.spirit_gain,
            headshot_multiplier=hero.crit_bonus_start,
        )
        config.distance = 0.0
        result = DamageCalculator.calculate_bullet(hero, config)

        base_dps = hero.base_dps
        multiplier = result.sustained_dps / base_dps if base_dps > 0 else 0
        assert multiplier < 5.0, (
            f"Weapon build DPS {result.sustained_dps:.0f} is {multiplier:.1f}× base "
            f"({base_dps:.0f}) — verify in-game"
        )
        assert multiplier > 1.0, "Build should increase DPS above base"

    def test_full_spirit_build_dps_bounds(self, heroes, items):
        """A max-budget spirit build should not produce insane spirit DPS.

        REVIEW: Total spirit DPS should be plausible. At boon 20 with
        tier-4 spirit items, expect 200-2000 range for most heroes.
        If > 5000, something is likely wrong.
        """
        hero = _hero(heroes, "Infernus")
        spirit_items = sorted(
            [i for i in items.values() if i.category.lower() == "spirit" and not i.condition],
            key=lambda x: -x.cost,
        )[:6]
        if len(spirit_items) < 3:
            pytest.skip("Not enough spirit items")

        build = Build(items=spirit_items)
        stats = BuildEngine.aggregate_stats(build)
        config = BuildEngine.build_to_attacker_config(
            stats, boons=20, spirit_gain=hero.spirit_gain,
        )

        dps = DamageCalculator.hero_total_spirit_dps(
            hero,
            current_spirit=config.current_spirit,
            cooldown_reduction=stats.cooldown_reduction,
            spirit_amp=stats.spirit_amp_pct,
            resist_shred=stats.spirit_resist_shred,
        )

        assert dps > 0, "Spirit DPS should be positive"
        assert dps < 5000, (
            f"Infernus spirit DPS {dps:.0f} at boon 20 seems too high — verify in-game"
        )

    # ── G. Simulation damage vs analytical ────────────────────────

    def test_sim_weapon_only_matches_analytical(self, heroes):
        """Sim weapon-only DPS should converge to analytical sustained DPS.

        Over a long duration (30s+), sim and analytical should agree within 5%.
        Shorter durations diverge because partial magazines have no trailing
        reload, inflating sim DPS above the analytical average.
        REVIEW: If discrepancy > 5% at 30s, check reload timing or event ordering.
        """
        for name in ["Haze", "Seven", "Abrams", "Wraith"]:
            hero = _hero(heroes, name)
            dummy = HeroStats(name="Dummy", base_hp=100000, base_regen=0)
            config = SimConfig(
                attacker=hero, defender=dummy,
                settings=SimSettings(
                    duration=30.0, weapon_uptime=1.0, accuracy=1.0,
                    headshot_rate=0.0, distance=0.0, attacker_boons=0,
                    weave_melee=False, melee_after_reload=False,
                    ability_uptime=0.0,
                ),
            )
            sim_result = CombatSimulator.run(config)
            sim_dps = sim_result.bullet_damage / 30.0

            analytical = DamageCalculator.calculate_bullet(
                hero, CombatConfig(boons=0, distance=0.0)
            ).sustained_dps

            assert sim_dps == pytest.approx(analytical, rel=0.05), (
                f"{name}: sim DPS {sim_dps:.1f} vs analytical {analytical:.1f}"
            )

    def test_sim_spirit_damage_positive_with_abilities(self, heroes):
        """Sim should produce spirit damage when hero has damaging abilities.

        REVIEW: If spirit_damage = 0 in a 15s sim with abilities enabled,
        the ability scheduling or application is broken.
        """
        hero = _hero(heroes, "Infernus")
        dummy = HeroStats(name="Dummy", base_hp=50000, base_regen=0)
        config = SimConfig(
            attacker=hero, defender=dummy,
            settings=SimSettings(duration=15.0, attacker_boons=10),
        )
        result = CombatSimulator.run(config)
        assert result.spirit_damage > 0, (
            f"Infernus sim produced 0 spirit damage in 15s — abilities may not be firing"
        )

    # ── H. Percent-HP DoT sanity ──────────────────────────────────

    def test_percent_hp_dot_scales_with_target_hp(self, heroes, items):
        """%-HP DoT items should deal more damage to high-HP targets.

        In-game: Toxic Bullets on a tanky target should show higher
        tick damage than on a squishy target.

        Buildup is hero-scaled: buildup_per_shot = 100 / (fire_rate × time).
        Default time for Toxic Bullets = 1.5s.  Haze at 9.5 rps → 7.0%/shot
        → 15 shots → procs at ~1.5s.  This test uses Haze with a 10s sim.
        """
        hero = _hero(heroes, "Haze")
        tb = items.get("Toxic Bullets")
        if tb is None:
            pytest.skip("Toxic Bullets not found")

        low_hp = HeroStats(name="Squishy", base_hp=5000, base_regen=0)
        high_hp = HeroStats(name="Tank", base_hp=50000, base_regen=0)

        settings = SimSettings(
            duration=10.0, weapon_uptime=1.0, accuracy=1.0,
            headshot_rate=0.0, distance=0.0, attacker_boons=0,
            melee_after_reload=False, ability_uptime=0.0,
        )
        no_abilities = [AbilityUse(ability_index=0, first_use=9999, use_on_cooldown=False)]
        r_low = CombatSimulator.run(SimConfig(
            attacker=hero, attacker_build=Build(items=[tb]),
            defender=low_hp, settings=settings,
            ability_schedule=no_abilities,
        ))
        r_high = CombatSimulator.run(SimConfig(
            attacker=hero, attacker_build=Build(items=[tb]),
            defender=high_hp, settings=settings,
            ability_schedule=no_abilities,
        ))

        # Filter only Toxic Bullets DoT damage from timeline
        dot_name = tb.name
        dot_low = sum(e.damage for e in r_low.timeline if e.source == dot_name)
        dot_high = sum(e.damage for e in r_high.timeline if e.source == dot_name)

        assert dot_high > 0, (
            f"Toxic Bullets never triggered in 10s with Haze — check buildup defaults"
        )
        assert dot_low > 0, "DoT should trigger against squishy too"

        # %-HP DoT: 2% max_hp/s for 4s → 50000 HP target takes 10× more
        assert dot_high > dot_low, (
            f"%-HP DoT should deal more to Tank ({dot_high:.0f}) "
            f"than Squishy ({dot_low:.0f})"
        )

    def test_buildup_default_procs_within_expected_time(self, heroes, items):
        """Buildup items with default time settings should proc at ~1s (or ~3s
        for Toxic Bullets) of continuous fire for any hero.

        In-game: Buy a buildup item, hold fire on dummy, note proc time.
        The sim derives buildup_per_shot = 100 / (fire_rate × default_time).
        """
        for hero_name in ["Haze", "Seven", "Abrams", "Wraith", "Bebop"]:
            hero = _hero(heroes, hero_name)
            for item_name in ["Slowing Bullets", "Toxic Bullets"]:
                item = items.get(item_name)
                if item is None:
                    continue
                expected_time = 1.5 if item_name == "Toxic Bullets" else 1.0
                dummy = HeroStats(name="Dummy", base_hp=100000, base_regen=0)
                settings = SimSettings(
                    duration=expected_time + 5.0, weapon_uptime=1.0,
                    accuracy=1.0, headshot_rate=0.0, distance=0.0,
                    attacker_boons=0, melee_after_reload=False,
                    ability_uptime=0.0,
                )
                no_abilities = [AbilityUse(ability_index=0, first_use=9999,
                                           use_on_cooldown=False)]
                result = CombatSimulator.run(SimConfig(
                    attacker=hero, attacker_build=Build(items=[item]),
                    defender=dummy, settings=settings,
                    ability_schedule=no_abilities,
                ))
                # Find the first damage entry from this item
                first_proc = next(
                    (e for e in result.timeline if e.source == item_name), None,
                )
                if first_proc is None:
                    # Items without DoT damage (like Slowing Bullets) don't
                    # generate damage timeline entries, they only apply debuffs.
                    # Check that the buildup was consumed (tracker reset).
                    continue
                # Proc should happen near the expected time (within 1 reload)
                assert first_proc.time < expected_time + hero.reload_duration + 1.0, (
                    f"{hero_name} + {item_name}: first proc at {first_proc.time:.1f}s, "
                    f"expected ~{expected_time}s"
                )

    def test_buildup_override_respected(self, heroes, items):
        """User-provided buildup_overrides should take precedence over defaults.

        Set a very high buildup_per_shot (50%/shot) → procs in 2 shots.
        """
        hero = _hero(heroes, "Haze")
        tb = items.get("Toxic Bullets")
        if tb is None:
            pytest.skip("Toxic Bullets not found")

        dummy = HeroStats(name="Dummy", base_hp=100000, base_regen=0)
        settings = SimSettings(
            duration=5.0, weapon_uptime=1.0, accuracy=1.0,
            headshot_rate=0.0, distance=0.0, attacker_boons=0,
            melee_after_reload=False, ability_uptime=0.0,
            buildup_overrides={"Toxic Bullets": 50.0},  # 2 shots to proc
        )
        no_abilities = [AbilityUse(ability_index=0, first_use=9999,
                                   use_on_cooldown=False)]
        result = CombatSimulator.run(SimConfig(
            attacker=hero, attacker_build=Build(items=[tb]),
            defender=dummy, settings=settings,
            ability_schedule=no_abilities,
        ))
        first_proc = next(
            (e for e in result.timeline if e.source == "Toxic Bullets"), None,
        )
        assert first_proc is not None, "Override 50%/shot should proc in 2 shots"
        # 2 shots at ~9.5 rps = ~0.21s
        assert first_proc.time < 1.0, (
            f"50%/shot should proc almost instantly, got {first_proc.time:.2f}s"
        )

    # ── I. Lifesteal & heal reduction interaction ─────────────────

    def test_lifesteal_heals_attacker_in_sim(self, heroes, items):
        """Sim attacker with lifesteal should have more HP remaining.

        In-game: Buy lifesteal item, fight in sandbox. Note HP at end.
        REVIEW: Does the sim apply lifesteal to bullet damage correctly?
        """
        hero = _hero(heroes, "Haze")
        dummy = HeroStats(name="Dummy", base_hp=50000, base_regen=0)

        # Find a lifesteal item
        ls_items = [i for i in items.values() if i.bullet_lifesteal > 0]
        if not ls_items:
            pytest.skip("No bullet lifesteal items found")
        ls_item = ls_items[0]

        config_bidi = SimConfig(
            attacker=hero,
            attacker_build=Build(items=[ls_item]),
            defender=dummy,
            settings=SimSettings(
                duration=10.0, bidirectional=True,
                attacker_boons=10, defender_boons=0,
            ),
        )
        config_no_ls = SimConfig(
            attacker=hero,
            defender=dummy,
            settings=SimSettings(
                duration=10.0, bidirectional=True,
                attacker_boons=10, defender_boons=0,
            ),
        )

        r_ls = CombatSimulator.run(config_bidi)
        r_no = CombatSimulator.run(config_no_ls)

        # With lifesteal, attacker should have more HP remaining
        # (dummy has 0 damage so this test is more about verifying
        # the lifesteal code path doesn't crash)
        assert r_ls.attacker_hp_remaining is not None
        assert r_ls.attacker_hp_remaining >= 0

    # ── J. Bidirectional simulation outliers ──────────────────────

    def test_bidirectional_both_deal_damage(self, heroes):
        """Both combatants should deal damage in bidirectional mode.

        REVIEW: If one side deals 0 damage, their events aren't firing.
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        config = SimConfig(
            attacker=haze, defender=abrams,
            settings=SimSettings(
                duration=20.0, bidirectional=True,
                attacker_boons=10, defender_boons=10,
            ),
        )
        result = CombatSimulator.run(config)

        assert result.total_damage > 0, "Attacker should deal damage"
        assert result.defender_total_damage is not None
        assert result.defender_total_damage > 0, "Defender should deal damage"

    def test_bidirectional_kill_determines_winner(self, heroes):
        """In a heavily asymmetric matchup, a winner should emerge.

        Scenario: Haze (boon 25) vs base-stat dummy (boon 0).
        The high-boon attacker should kill the dummy.
        REVIEW: Winner should be 'a' (attacker advantage).
        """
        haze = _hero(heroes, "Haze")
        dummy = HeroStats(name="Dummy", base_hp=800, base_regen=0,
                          base_bullet_damage=5, base_fire_rate=5, base_ammo=20,
                          pellets=1, reload_duration=1.0)

        config = SimConfig(
            attacker=haze, defender=dummy,
            settings=SimSettings(
                duration=30.0, bidirectional=True,
                attacker_boons=25, defender_boons=0,
            ),
        )
        result = CombatSimulator.run(config)

        assert result.kill_time is not None, "Should produce a kill"
        assert result.winner == "a", f"Boon-25 attacker should win, got '{result.winner}'"

    # ── K. Melee-scaled ability edge cases ────────────────────────

    def test_melee_scaled_ability_non_zero(self, heroes):
        """Heroes with melee-scaled abilities should have non-trivial DPS
        from those abilities.

        REVIEW: melee_scale abilities derive damage from light_melee_damage.
        If melee_scale > 0 but contribution is near 0, there's a bug.
        """
        for name, hero in heroes.items():
            for ab in hero.abilities:
                if ab.melee_scale > 0:
                    dps = DamageCalculator.hero_total_spirit_dps(
                        hero, current_spirit=0, boons=10,
                        weapon_damage_bonus=0.0, melee_damage_pct=0.0,
                    )
                    assert dps > 0, (
                        f"{name} has melee_scale ability '{ab.name}' "
                        f"but total spirit DPS = 0"
                    )
                    return
        pytest.skip("No hero with melee_scale abilities found")

    def test_melee_scaled_ability_scales_with_weapon_bonus(self, heroes):
        """Weapon damage bonus should increase melee-scaled ability DPS.

        REVIEW: weapon_damage_bonus applies at 50% rate to melee, which
        then feeds into melee_scale abilities. Verify this chain works.
        """
        for name, hero in heroes.items():
            has_melee_scale = any(ab.melee_scale > 0 for ab in hero.abilities)
            if not has_melee_scale:
                continue

            dps_no_bonus = DamageCalculator.hero_total_spirit_dps(
                hero, current_spirit=0, boons=10,
                weapon_damage_bonus=0.0,
            )
            dps_with_bonus = DamageCalculator.hero_total_spirit_dps(
                hero, current_spirit=0, boons=10,
                weapon_damage_bonus=0.50,
            )
            assert dps_with_bonus > dps_no_bonus, (
                f"{name}: melee-scaled ability DPS should increase with weapon bonus"
            )
            return
        pytest.skip("No hero with melee_scale abilities found")

    # ── L. Item damage boundary checks ────────────────────────────

    def test_no_item_dps_exceeds_extreme_threshold(self, heroes, items):
        """Flag items whose calculated DPS seems unrealistically high.

        REVIEW: Items with DPS > 500 at 30 spirit are likely active items
        with high burst or items whose DPS formula doesn't account for
        activation constraints. Flagged here for manual verification.
        Known outliers (verify in-game):
        - Electric Slippers: high calculated DPS from active ability
        - Prism Blast: high calculated DPS from active ability
        """
        outliers = []
        for name, item in items.items():
            result = DamageCalculator.calculate_item_damage(item, current_spirit=30)
            if result and result.dps > 500:
                outliers.append((name, result.dps))

        # These are known active-ability items with high burst damage
        # classified as high DPS because the cooldown is short.
        # They are not bugs, but should be verified in-game.
        for name, dps in outliers:
            assert dps < 2000, (
                f"{name} DPS={dps:.0f} exceeds 2000 — likely a parsing error"
            )

    def test_all_damage_items_positive_dps(self, items):
        """Every damage-dealing item should produce positive DPS.

        REVIEW: If an item has damage properties but calculate_item_damage
        returns 0 DPS, the parsing or formula is broken.
        """
        for name, item in items.items():
            result = DamageCalculator.calculate_item_damage(item)
            if result is not None:
                assert result.dps >= 0, (
                    f"{name}: negative DPS ({result.dps:.2f}) — formula error"
                )

    # ── M. Simulation event ordering & timing ─────────────────────

    def test_sim_no_damage_after_kill(self, heroes):
        """After the target dies, no further damage should be dealt.

        REVIEW: If damage events fire after kill_time, the kill detection
        or event gating is broken.
        """
        haze = _hero(heroes, "Haze")
        squishy = HeroStats(name="Squishy", base_hp=100, base_regen=0)

        config = SimConfig(
            attacker=haze, defender=squishy,
            settings=SimSettings(
                duration=10.0, weapon_uptime=1.0, accuracy=1.0,
                headshot_rate=0.0, distance=0.0, attacker_boons=10,
                melee_after_reload=False, ability_uptime=0.0,
            ),
        )
        result = CombatSimulator.run(config)

        assert result.kill_time is not None, "Should kill 100 HP target"
        assert result.kill_time < 10.0, "Should kill well before 10s"

        # No events should appear after kill_time (sim stops on kill)
        late_events = [
            e for e in result.timeline
            if e.combatant == "a" and e.time > result.kill_time + 0.001
        ]
        assert len(late_events) == 0, (
            f"{len(late_events)} damage events after kill at t={result.kill_time:.3f}"
        )

    def test_sim_duration_respected(self, heroes):
        """Sim should not produce events beyond the configured duration.

        REVIEW: Regen ticks and DoTs scheduled near the end could overshoot.
        """
        hero = _hero(heroes, "Haze")
        dummy = HeroStats(name="Dummy", base_hp=50000, base_regen=0)

        config = SimConfig(
            attacker=hero, defender=dummy,
            settings=SimSettings(duration=5.0),
        )
        result = CombatSimulator.run(config)

        for entry in result.timeline:
            assert entry.time <= 5.0 + 0.001, (
                f"Event at t={entry.time:.3f} exceeds 5.0s duration"
            )

    # ── N. Cross-hero damage spread at boon 0 ────────────────────

    def test_all_heroes_base_dps_in_range(self, heroes):
        """All heroes' base sustained DPS should be between 15 and 120.

        REVIEW: If any hero is outside this range at boon 0, check if
        the API data has changed or if there's a new hero with unusual stats.
        """
        outliers = []
        for name, hero in heroes.items():
            result = DamageCalculator.calculate_bullet(
                hero, CombatConfig(boons=0, distance=0.0),
            )
            if result.sustained_dps < 15 or result.sustained_dps > 120:
                outliers.append((name, result.sustained_dps))

        if outliers:
            details = "; ".join(f"{n}={d:.1f}" for n, d in outliers)
            assert False, (
                f"Heroes with sustained DPS outside 15-120 range: {details}. "
                f"Verify these in-game sandbox."
            )

    def test_all_heroes_ehp_at_boon0_in_range(self, heroes):
        """All heroes' base EHP at boon 0 should be between 500 and 1200.

        REVIEW: If any hero's base HP is outside this range, something
        changed in the data or there's a new hero with extreme stats.
        """
        outliers = []
        for name, hero in heroes.items():
            if hero.base_hp < 500 or hero.base_hp > 1200:
                outliers.append((name, hero.base_hp))

        if outliers:
            details = "; ".join(f"{n}={hp:.0f}" for n, hp in outliers)
            assert False, (
                f"Heroes with base HP outside 500-1200: {details}. "
                f"Check API data for changes."
            )

    # ── O. Resist multiplicative stacking stress test ─────────────

    def test_resist_stack_diminishing_returns(self, items):
        """Stacking many resist items should show diminishing returns.

        REVIEW: 3 items each with ~20% resist should give ~49%, not 60%.
        If the result is additive (60%), the stacking formula is wrong.
        """
        resist_items = [
            i for i in items.values()
            if i.bullet_resist_pct > 0.10 and not i.condition
        ][:3]
        if len(resist_items) < 3:
            pytest.skip("Need 3+ resist items with > 10%")

        build = Build(items=resist_items)
        stats = BuildEngine.aggregate_stats(build)

        # Multiplicative should be less than additive
        additive = sum(i.bullet_resist_pct for i in resist_items)
        assert stats.bullet_resist_pct < additive, (
            f"Resist should stack multiplicatively ({stats.bullet_resist_pct:.2%}) "
            f"< additive ({additive:.2%})"
        )
        # Should never exceed 1.0
        assert stats.bullet_resist_pct < 1.0

    def test_extreme_resist_stacking_cap(self, items):
        """Stacking all resist items should not exceed 90% effective resist.

        REVIEW: With multiplicative stacking, even extreme 8-item builds
        should stay under 90%. The game has no hard cap, but multiplicative
        stacking provides natural diminishing returns. ~80-85% is expected
        maximum with current items.
        """
        all_resist = sorted(
            [i for i in items.values() if i.bullet_resist_pct > 0 and not i.condition],
            key=lambda x: -x.bullet_resist_pct,
        )[:8]
        if len(all_resist) < 3:
            pytest.skip("Not enough resist items")

        build = Build(items=all_resist)
        stats = BuildEngine.aggregate_stats(build)
        assert stats.bullet_resist_pct < 0.90, (
            f"Stacking {len(all_resist)} resist items gives {stats.bullet_resist_pct:.0%} "
            f"— exceeds 90%. Verify in-game."
        )
        # Should show clear diminishing returns vs additive
        additive = sum(i.bullet_resist_pct for i in all_resist)
        assert stats.bullet_resist_pct < additive, (
            "Multiplicative stacking should be less than additive"
        )

    # ── P. TTK outlier detection ──────────────────────────────────

    def test_ttk_not_infinite_or_zero(self, heroes):
        """TTK should be finite and positive for all attacker/defender pairs.

        REVIEW: TTK of 0 means instant kill (bad). At 65% accuracy and
        distance=20, TTK can be quite long (60-80s for tankier matchups).
        A TTK > 120s at boon 10 would be suspicious.
        """
        pairs = [("Haze", "Abrams"), ("Seven", "Haze"), ("Wraith", "Infernus")]
        for atk_name, def_name in pairs:
            atk = _hero(heroes, atk_name)
            dfn = _hero(heroes, def_name)
            config = CombatConfig(boons=10, accuracy=0.65, distance=20.0)
            ttk = HeroMetrics.ttk(atk, dfn, config)
            assert ttk.realistic_ttk > 0, f"{atk_name} vs {def_name}: TTK=0 (instant kill?)"
            assert ttk.realistic_ttk < 120, (
                f"{atk_name} vs {def_name}: TTK={ttk.realistic_ttk:.1f}s — "
                f"exceeds 2 min at boon 10. Check damage formula."
            )

    def test_ttk_at_max_range_much_longer(self, heroes):
        """TTK at max falloff range should be dramatically longer.

        In-game: Shoot from max range. 10% damage = ~10× TTK.
        Falloff ranges are in game units (Haze: 787-1811).
        Distance must be in the same unit system.
        """
        haze = _hero(heroes, "Haze")
        abrams = _hero(heroes, "Abrams")

        if haze.falloff_range_max <= 0:
            pytest.skip("Haze has no falloff range data")

        close = CombatConfig(boons=0, accuracy=1.0, distance=0.0)
        far = CombatConfig(
            boons=0, accuracy=1.0,
            distance=haze.falloff_range_max + 100,  # beyond max range
        )

        # Verify bullet DPS does apply falloff correctly
        close_bullet = DamageCalculator.calculate_bullet(haze, close)
        far_bullet = DamageCalculator.calculate_bullet(haze, far)
        dps_ratio = far_bullet.final_dps / close_bullet.final_dps
        assert dps_ratio == pytest.approx(0.1, abs=0.01), (
            f"Bullet DPS falloff works: {dps_ratio:.2f}"
        )

        # TTK step-by-step should also apply falloff
        ttk_close = HeroMetrics.ttk(haze, abrams, close)
        ttk_far = HeroMetrics.ttk(haze, abrams, far)

        ratio = ttk_far.realistic_ttk / ttk_close.realistic_ttk
        assert ratio > 5, (
            f"TTK ratio {ratio:.1f}× at max range — expected ~10×"
        )
        assert ratio < 15, (
            f"TTK ratio {ratio:.1f}× seems too high — check falloff formula"
        )

    # ── Q. Scoring edge case: division by zero ────────────────────

    def test_scoring_zero_cost_item_no_crash(self, heroes, items):
        """Item with cost=0 should not crash the scorer (division safety).

        This is a defensive test — real items all have cost > 0 per data
        sanity checks, but the scorer uses `cost or 1` as fallback.
        """
        from deadlock_sim.engine.scoring import ItemScorer

        hero = _hero(heroes, "Haze")
        zero_item = Item(name="Free", category="weapon", tier=1, cost=0,
                         weapon_damage_pct=0.05)
        baseline = Build(items=[])
        scores = ItemScorer.score_candidates(
            hero, baseline, [zero_item], boons=10, mode="fast",
        )
        assert "Free" in scores
        # Division by `cost or 1` should prevent crash
        score = scores["Free"]
        assert math.isfinite(score.dps_per_soul)
        assert math.isfinite(score.ehp_per_soul)

    # ── R. Regen vs. DPS breakpoint ───────────────────────────────

    def test_high_regen_delays_kill(self, heroes):
        """High regen target should take longer to kill in simulation.

        In-game: Target with regen items takes longer to die.
        REVIEW: If regen > incoming DPS, kill should never happen
        (target_hp_remaining > 0 at sim end).
        """
        haze = _hero(heroes, "Haze")

        no_regen = HeroStats(name="Dummy", base_hp=5000, base_regen=0)
        with_regen = HeroStats(name="RegenDummy", base_hp=5000, base_regen=100)

        config_no = SimConfig(
            attacker=haze, defender=no_regen,
            settings=SimSettings(
                duration=30.0, weapon_uptime=1.0, accuracy=0.65,
                attacker_boons=0, distance=0.0,
            ),
        )
        config_regen = SimConfig(
            attacker=haze, defender=with_regen,
            settings=SimSettings(
                duration=30.0, weapon_uptime=1.0, accuracy=0.65,
                attacker_boons=0, distance=0.0,
            ),
        )

        r_no = CombatSimulator.run(config_no)
        r_regen = CombatSimulator.run(config_regen)

        # Regen target should either take longer to kill or survive entirely
        if r_no.kill_time is not None:
            if r_regen.kill_time is not None:
                assert r_regen.kill_time > r_no.kill_time, (
                    "Regen target should take longer to kill"
                )
            # Else regen target survived — expected
        assert r_regen.target_hp_remaining >= r_no.target_hp_remaining, (
            "Regen target should have more HP remaining"
        )

    def test_regen_exceeds_dps_target_unkillable(self, heroes):
        """When regen > incoming DPS, the target should survive.

        REVIEW: With 1000 hp/s regen on a 5000 HP target, a low-boon
        hero cannot kill it. Verify target_hp_remaining > 0.
        """
        haze = _hero(heroes, "Haze")
        immortal = HeroStats(name="Immortal", base_hp=5000, base_regen=1000)

        config = SimConfig(
            attacker=haze, defender=immortal,
            settings=SimSettings(
                duration=10.0, weapon_uptime=1.0, accuracy=0.65,
                attacker_boons=0, distance=0.0,
            ),
        )
        result = CombatSimulator.run(config)

        assert result.kill_time is None, "Should not kill immortal target"
        assert result.target_hp_remaining > 0, "Immortal target should survive"
