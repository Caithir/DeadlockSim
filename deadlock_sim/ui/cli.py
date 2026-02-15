"""CLI reference UI for the Deadlock simulator.

This is a pure presentation layer - all calculations come from the engine.
Designed to be replaceable with any other UI (web, TUI, GUI) by swapping
only this module.
"""

from __future__ import annotations

import sys

from ..data import load_heroes, load_shop_tiers
from ..engine.comparison import ComparisonEngine
from ..engine.damage import DamageCalculator
from ..engine.scaling import ScalingCalculator
from ..engine.ttk import TTKCalculator
from ..models import AbilityConfig, CombatConfig, HeroStats


def _divider(char: str = "-", width: int = 60) -> str:
    return char * width


def _header(title: str, width: int = 60) -> str:
    return f"\n{'=' * width}\n  {title}\n{'=' * width}"


def _prompt_choice(prompt: str, options: list[str]) -> str:
    """Generic choice prompt. Returns selected value."""
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        try:
            raw = input(f"\n{prompt} [1-{len(options)}]: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except (ValueError, EOFError):
            pass
        print("  Invalid choice, try again.")


def _prompt_int(prompt: str, default: int = 0) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _prompt_float(prompt: str, default: float = 0.0) -> float:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _pick_hero(heroes: dict[str, HeroStats], prompt: str = "Select hero") -> HeroStats:
    names = sorted(heroes.keys())
    print(f"\n{prompt}:")
    for i, name in enumerate(names, 1):
        print(f"  {i:2d}. {name}")
    while True:
        raw = input(f"\n  Enter number or name: ").strip()
        # Try numeric
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(names):
                return heroes[names[idx]]
        except ValueError:
            pass
        # Try name match (case insensitive)
        for name in names:
            if name.lower() == raw.lower():
                return heroes[name]
        print("  Not found, try again.")


# ─── Display Functions ───────────────────────────────────────────

def display_hero_stats(hero: HeroStats) -> None:
    """Print a hero's base stats."""
    print(_header(f"{hero.name} - Base Stats"))
    print(f"  Bullet Damage:   {hero.base_bullet_damage:.2f} x{hero.pellets} pellets")
    print(f"  Fire Rate:       {hero.base_fire_rate:.2f} shots/sec")
    print(f"  Base DPS:        {hero.base_dps:.2f}")
    print(f"  Magazine:        {hero.base_ammo} rounds")
    print(f"  DPM:             {hero.base_dpm:.2f}")
    print(f"  Falloff:         {hero.falloff_range_min:.0f}m - {hero.falloff_range_max:.0f}m")
    print(f"  HP:              {hero.base_hp:.0f}")
    print(f"  Regen:           {hero.base_regen:.1f}/s")
    print(f"  Move Speed:      {hero.base_move_speed:.2f}")
    print(f"  Sprint Speed:    {hero.base_sprint:.1f}")
    print(f"  Stamina:         {hero.base_stamina}")
    print(_divider())
    print(f"  Per-Boon Scaling:")
    print(f"    Damage Gain:   +{hero.damage_gain:.2f}/boon")
    print(f"    HP Gain:       +{hero.hp_gain:.0f}/boon")
    print(f"    Spirit Gain:   +{hero.spirit_gain:.1f}/boon")
    if hero.hero_labs:
        print(f"  [Hero Labs - stats may be incomplete]")


def display_bullet_calc(hero: HeroStats, config: CombatConfig) -> None:
    """Run and display bullet damage calculation."""
    result = DamageCalculator.calculate_bullet(hero, config)
    print(_header(f"{hero.name} - Bullet Damage (Boon {config.boons})"))
    print(f"  Damage/Bullet:   {result.damage_per_bullet:.2f}")
    print(f"  Bullets/Sec:     {result.bullets_per_second:.2f}")
    print(f"  Raw DPS:         {result.raw_dps:.2f}")
    print(f"  Shred:           {result.total_shred:.1%}")
    print(f"  Enemy Resist:    {config.enemy_bullet_resist:.1%} -> {result.final_resist:.1%}")
    print(f"  Final DPS:       {result.final_dps:.2f}")
    print(_divider())
    print(f"  Magazine:        {result.magazine_size} rounds")
    print(f"  Damage/Mag:      {result.damage_per_magazine:.2f}")
    print(f"  Magdump Time:    {result.magdump_time:.2f}s")

    if config.accuracy < 1.0:
        realistic = DamageCalculator.dps_with_accuracy(hero, config)
        print(f"  Realistic DPS:   {realistic:.2f} ({config.accuracy:.0%} acc, {config.headshot_rate:.0%} HS)")


def display_scaling(hero: HeroStats, max_boons: int = 35) -> None:
    """Display scaling curve in a table."""
    curve = ScalingCalculator.scaling_curve(hero, max_boons)
    growth = ScalingCalculator.growth_percentage(hero, max_boons)

    print(_header(f"{hero.name} - Scaling (0 to {max_boons} Boons)"))
    print(f"  {'Boon':>4}  {'Bullet Dmg':>10}  {'DPS':>10}  {'HP':>8}  {'Spirit':>7}")
    print(f"  {_divider('─', 47)}")

    step = max(1, max_boons // 10)
    for snap in curve:
        if snap.boon_level % step == 0 or snap.boon_level == max_boons:
            print(
                f"  {snap.boon_level:4d}"
                f"  {snap.bullet_damage:10.2f}"
                f"  {snap.dps:10.2f}"
                f"  {snap.hp:8.0f}"
                f"  {snap.spirit:7.1f}"
            )

    print(_divider())
    print(f"  Growth (0 -> {max_boons} boons):")
    print(f"    DPS:  {growth['dps_growth']:.1%}")
    print(f"    HP:   {growth['hp_growth']:.1%}")
    print(f"    Total: {growth['aggregate_growth']:.1%}")


def display_ttk(
    attacker: HeroStats,
    defender: HeroStats,
    config: CombatConfig,
) -> None:
    """Run and display TTK calculation."""
    result = TTKCalculator.calculate(attacker, defender, config)

    print(_header(f"TTK: {attacker.name} vs {defender.name}"))
    print(f"  Attacker ({attacker.name}):")
    print(f"    Boons:         {config.boons}")
    print(f"    Effective DPS: {result.effective_dps:.2f}")
    print(f"    Realistic DPS: {result.realistic_dps:.2f}")
    print(f"    Dmg/Magazine:  {result.damage_per_magazine:.2f}")
    print(f"  Defender ({defender.name}):")
    print(f"    Target HP:     {result.target_hp:.0f}")
    print(f"    Bullet Resist: {config.enemy_bullet_resist:.0%}")
    print(_divider())
    print(f"  Ideal TTK:       {result.ttk_seconds:.2f}s")
    print(f"  Realistic TTK:   {result.realistic_ttk:.2f}s")
    print(f"  Can One-Mag:     {'Yes' if result.can_one_mag else 'No'}")
    print(f"  Magazines Needed: {result.magazines_needed}")


def display_comparison(
    hero_a: HeroStats,
    hero_b: HeroStats,
    boon_level: int = 0,
) -> None:
    """Display side-by-side comparison."""
    comp = ComparisonEngine.compare_two(hero_a, hero_b, boon_level)

    print(_header(f"Comparison: {hero_a.name} vs {hero_b.name} (Boon {boon_level})"))
    print(f"  {'':16} {'':>2}{hero_a.name:>14}  {hero_b.name:>14}  {'Ratio':>8}")
    print(f"  {_divider('─', 56)}")
    print(f"  {'DPS':16}   {comp.hero_a_dps:14.2f}  {comp.hero_b_dps:14.2f}  {comp.dps_ratio:8.2f}")
    print(f"  {'HP':16}   {comp.hero_a_hp:14.0f}  {comp.hero_b_hp:14.0f}  {comp.hp_ratio:8.2f}")
    print(f"  {'DPM':16}   {comp.hero_a_dpm:14.2f}  {comp.hero_b_dpm:14.2f}  {comp.dpm_ratio:8.2f}")


def display_rankings(
    heroes: dict[str, HeroStats],
    stat: str,
    boon_level: int = 0,
    top_n: int = 10,
) -> None:
    """Display hero rankings for a stat."""
    rankings = ComparisonEngine.rank_heroes(heroes, stat, boon_level)

    print(_header(f"Hero Rankings - {stat.upper()} (Boon {boon_level})"))
    print(f"  {'Rank':>4}  {'Hero':<16}  {'Value':>12}")
    print(f"  {_divider('─', 36)}")
    for entry in rankings[:top_n]:
        print(f"  {entry.rank:4d}  {entry.hero_name:<16}  {entry.value:12.2f}")


# ─── Menu / Main Loop ────────────────────────────────────────────

MAIN_MENU = [
    "Hero Stats Lookup",
    "Bullet Damage Calculator",
    "Spirit Damage Calculator",
    "Scaling Curve",
    "Time-to-Kill Calculator",
    "Hero Comparison",
    "Hero Rankings",
    "Quit",
]


def run_cli() -> None:
    """Main CLI entry point."""
    print(_header("DEADLOCK COMBAT SIMULATOR", 40))
    print("  Loading hero data...")

    try:
        heroes = load_heroes()
    except Exception as e:
        print(f"  Error loading data: {e}")
        sys.exit(1)

    print(f"  Loaded {len(heroes)} heroes.\n")

    while True:
        print(f"\n{'─' * 40}")
        print("  MAIN MENU")
        choice = _prompt_choice("Choose", MAIN_MENU)

        if choice == "Quit":
            print("\n  Goodbye!")
            break

        try:
            if choice == "Hero Stats Lookup":
                hero = _pick_hero(heroes)
                display_hero_stats(hero)

            elif choice == "Bullet Damage Calculator":
                hero = _pick_hero(heroes, "Select attacker")
                boons = _prompt_int("  Boons", 0)
                wpn_dmg = _prompt_float("  Weapon damage bonus %", 0) / 100
                fire_rate = _prompt_float("  Fire rate bonus %", 0) / 100
                resist = _prompt_float("  Enemy bullet resist %", 0) / 100
                shred = _prompt_float("  Shred %", 0) / 100
                accuracy = _prompt_float("  Accuracy % (100 = perfect)", 100) / 100

                config = CombatConfig(
                    boons=boons,
                    weapon_damage_bonus=wpn_dmg,
                    fire_rate_bonus=fire_rate,
                    enemy_bullet_resist=resist,
                    shred=[shred] if shred > 0 else [],
                    accuracy=accuracy,
                )
                display_bullet_calc(hero, config)

            elif choice == "Spirit Damage Calculator":
                base_dmg = _prompt_float("  Ability base damage", 100)
                spirit_mult = _prompt_float("  Spirit multiplier", 1.0)
                spirit = _prompt_int("  Current spirit", 0)
                resist = _prompt_float("  Enemy spirit resist %", 0) / 100
                duration = _prompt_float("  Ability duration (0 = instant)", 0)

                ability = AbilityConfig(
                    base_damage=base_dmg,
                    spirit_multiplier=spirit_mult,
                    current_spirit=spirit,
                    enemy_spirit_resist=resist,
                    ability_duration=duration,
                )
                result = DamageCalculator.calculate_spirit(ability)
                print(_header("Spirit Damage Result"))
                print(f"  Raw Damage:      {result.raw_damage:.2f}")
                print(f"  Spirit Contrib:  {result.spirit_contribution:.2f}")
                print(f"  Modified Damage: {result.modified_damage:.2f}")
                if duration > 0:
                    print(f"  DPS:             {result.dps:.2f}")
                    print(f"  Total DoT:       {result.total_dot_damage:.2f}")

            elif choice == "Scaling Curve":
                hero = _pick_hero(heroes)
                max_b = _prompt_int("  Max boons to show", 35)
                display_scaling(hero, max_b)

            elif choice == "Time-to-Kill Calculator":
                attacker = _pick_hero(heroes, "Select attacker")
                defender = _pick_hero(heroes, "Select defender")
                boons = _prompt_int("  Boons (both)", 0)
                resist = _prompt_float("  Defender bullet resist %", 0) / 100
                bonus_hp = _prompt_float("  Defender bonus HP (items)", 0)
                accuracy = _prompt_float("  Accuracy %", 50) / 100
                hs_rate = _prompt_float("  Headshot rate %", 15) / 100

                config = CombatConfig(
                    boons=boons,
                    enemy_bullet_resist=resist,
                    enemy_bonus_hp=bonus_hp,
                    accuracy=accuracy,
                    headshot_rate=hs_rate,
                )
                display_ttk(attacker, defender, config)

            elif choice == "Hero Comparison":
                hero_a = _pick_hero(heroes, "Select hero A")
                hero_b = _pick_hero(heroes, "Select hero B")
                boons = _prompt_int("  Boon level", 0)
                display_comparison(hero_a, hero_b, boons)

            elif choice == "Hero Rankings":
                stat_options = ["dps", "hp", "dpm", "bullet_damage", "fire_rate", "dps_growth", "hp_growth"]
                stat = _prompt_choice("Rank by", stat_options)
                boons = _prompt_int("  Boon level", 0)
                display_rankings(heroes, stat, boons)

        except KeyboardInterrupt:
            print("\n  (Cancelled)")
        except Exception as e:
            print(f"\n  Error: {e}")
