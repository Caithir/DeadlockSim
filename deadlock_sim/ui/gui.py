"""Dear PyGui UI for the Deadlock combat simulator.

GPU-accelerated desktop UI with tabs for each simulator feature.
All calculations delegated to deadlock_sim.engine — this module
is purely presentation.
"""

from __future__ import annotations

import math

import dearpygui.dearpygui as dpg

from ..data import load_heroes, load_items, load_shop_tiers
from ..engine.builds import BuildEngine, BuildOptimizer
from ..engine.comparison import ComparisonEngine
from ..engine.damage import DamageCalculator
from ..engine.scaling import ScalingCalculator
from ..engine.ttk import TTKCalculator
from ..models import AbilityConfig, Build, CombatConfig, HeroStats, Item

# ── Global state ──────────────────────────────────────────────────

_heroes: dict[str, HeroStats] = {}
_hero_names: list[str] = []
_items: dict[str, Item] = {}
_item_names: list[str] = []
_build_items: list[Item] = []

# ── Helpers ───────────────────────────────────────────────────────


def _get_hero(tag: str) -> HeroStats | None:
    name = dpg.get_value(tag)
    return _heroes.get(name)


def _pct(tag: str) -> float:
    """Read a percentage input and return as 0-1 fraction."""
    return dpg.get_value(tag) / 100.0


def _fv(v: float, fmt: str = ".2f", zero_as_na: bool = True) -> str:
    """Format a numeric value for display, showing '-' for missing/inf/nan."""
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
        return "-"
    if zero_as_na and v == 0:
        return "-"
    return f"{v:{fmt}}"


# ── Tab: Hero Stats ──────────────────────────────────────────────


def _build_hero_stats_tab(parent: int | str) -> None:
    with dpg.group(parent=parent):
        dpg.add_combo(
            _hero_names,
            label="Hero",
            tag="hs_hero",
            default_value=_hero_names[0] if _hero_names else "",
            callback=_on_hero_stats_changed,
            width=200,
        )
        dpg.add_separator()

        with dpg.group(tag="hs_output"):
            pass

    _on_hero_stats_changed(None, None)


def _on_hero_stats_changed(sender, app_data) -> None:
    hero = _get_hero("hs_hero")
    if not hero:
        return

    if dpg.does_item_exist("hs_output"):
        dpg.delete_item("hs_output", children_only=True)

    with dpg.group(parent="hs_output"):
        dpg.add_text(f"{hero.name}", color=(255, 200, 50))
        if hero.hero_labs:
            dpg.add_text("[Hero Labs - stats may be incomplete]", color=(255, 100, 100))
        dpg.add_spacer(height=5)

        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, resizable=True):
            dpg.add_table_column(label="Stat", width_fixed=True, init_width_or_weight=200)
            dpg.add_table_column(label="Value", width_fixed=True, init_width_or_weight=120)

            has_gun = hero.base_bullet_damage > 0 or hero.base_fire_rate > 0
            stats = [
                ("Bullet Damage", f"{hero.base_bullet_damage:.2f}" if has_gun else "-"),
                ("Pellets", f"{hero.pellets}" if has_gun else "-"),
                ("Fire Rate", f"{hero.base_fire_rate:.2f} /s" if hero.base_fire_rate > 0 else "-"),
                ("Base DPS", _fv(hero.base_dps)),
                ("Magazine", _fv(hero.base_ammo, "d")),
                ("DPM", _fv(hero.base_dpm)),
                ("Falloff Range", f"{hero.falloff_range_min:.0f}m - {hero.falloff_range_max:.0f}m" if has_gun else "-"),
                ("", ""),
                ("HP", _fv(hero.base_hp, ".0f")),
                ("Regen", f"{hero.base_regen:.1f} /s"),
                ("Move Speed", _fv(hero.base_move_speed)),
                ("Sprint", f"{hero.base_sprint:.1f}"),
                ("Stamina", _fv(hero.base_stamina, "d")),
                ("", ""),
                ("Dmg Gain / Boon", _fv(hero.damage_gain, "+.2f")),
                ("HP Gain / Boon", _fv(hero.hp_gain, "+.0f")),
                ("Spirit Gain / Boon", _fv(hero.spirit_gain, "+.1f")),
            ]

            for label, val in stats:
                with dpg.table_row():
                    dpg.add_text(label)
                    dpg.add_text(val)


# ── Tab: Bullet Damage ──────────────────────────────────────────


def _build_bullet_tab(parent: int | str) -> None:
    with dpg.group(parent=parent, horizontal=True):
        # Left: inputs
        with dpg.child_window(width=320, height=-1):
            dpg.add_text("Attacker", color=(255, 200, 50))
            dpg.add_combo(
                _hero_names, label="Hero", tag="bd_hero",
                default_value=_hero_names[0] if _hero_names else "",
                callback=_on_bullet_changed, width=180,
            )
            dpg.add_input_int(label="Boons", tag="bd_boons", default_value=0,
                              min_value=0, max_value=50, callback=_on_bullet_changed, width=120)
            dpg.add_input_float(label="Weapon Dmg %", tag="bd_wpn", default_value=0,
                                min_value=0, max_value=500, callback=_on_bullet_changed, width=120)
            dpg.add_input_float(label="Fire Rate %", tag="bd_fr", default_value=0,
                                min_value=0, max_value=500, callback=_on_bullet_changed, width=120)
            dpg.add_input_float(label="Ammo Increase %", tag="bd_ammo", default_value=0,
                                min_value=0, max_value=500, callback=_on_bullet_changed, width=120)

            dpg.add_separator()
            dpg.add_text("Shred Sources", color=(255, 200, 50))
            dpg.add_input_float(label="Shred 1 %", tag="bd_shred1", default_value=0,
                                min_value=0, max_value=100, callback=_on_bullet_changed, width=120)
            dpg.add_input_float(label="Shred 2 %", tag="bd_shred2", default_value=0,
                                min_value=0, max_value=100, callback=_on_bullet_changed, width=120)

            dpg.add_separator()
            dpg.add_text("Defender", color=(255, 200, 50))
            dpg.add_input_float(label="Bullet Resist %", tag="bd_resist", default_value=0,
                                min_value=0, max_value=100, callback=_on_bullet_changed, width=120)

            dpg.add_separator()
            dpg.add_text("Accuracy Model", color=(255, 200, 50))
            dpg.add_input_float(label="Accuracy %", tag="bd_acc", default_value=100,
                                min_value=0, max_value=100, callback=_on_bullet_changed, width=120)
            dpg.add_input_float(label="Headshot Rate %", tag="bd_hs", default_value=0,
                                min_value=0, max_value=100, callback=_on_bullet_changed, width=120)

        # Right: results
        with dpg.child_window(width=-1, height=-1):
            dpg.add_text("Results", color=(100, 200, 255))
            dpg.add_separator()
            with dpg.group(tag="bd_output"):
                pass

    _on_bullet_changed(None, None)


def _on_bullet_changed(sender, app_data) -> None:
    hero = _get_hero("bd_hero")
    if not hero:
        return

    shred_sources = []
    s1, s2 = _pct("bd_shred1"), _pct("bd_shred2")
    if s1 > 0:
        shred_sources.append(s1)
    if s2 > 0:
        shred_sources.append(s2)

    config = CombatConfig(
        boons=dpg.get_value("bd_boons"),
        weapon_damage_bonus=_pct("bd_wpn"),
        fire_rate_bonus=_pct("bd_fr"),
        ammo_increase=_pct("bd_ammo"),
        shred=shred_sources,
        enemy_bullet_resist=_pct("bd_resist"),
        accuracy=_pct("bd_acc"),
        headshot_rate=_pct("bd_hs"),
    )

    result = DamageCalculator.calculate_bullet(hero, config)
    realistic_dps = DamageCalculator.dps_with_accuracy(hero, config)

    if dpg.does_item_exist("bd_output"):
        dpg.delete_item("bd_output", children_only=True)

    with dpg.group(parent="bd_output"):
        if result.bullets_per_second == 0 and result.damage_per_bullet == 0:
            dpg.add_text(f"No gun data available for {hero.name}.", color=(255, 100, 100))
            return

        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, resizable=True):
            dpg.add_table_column(label="Metric", width_fixed=True, init_width_or_weight=200)
            dpg.add_table_column(label="Value", width_fixed=True, init_width_or_weight=140)

            rows = [
                ("Damage / Bullet", _fv(result.damage_per_bullet)),
                ("Bullets / Sec", _fv(result.bullets_per_second)),
                ("Raw DPS", _fv(result.raw_dps)),
                ("", ""),
                ("Total Shred", f"{result.total_shred:.1%}"),
                ("Final Resist", f"{result.final_resist:.1%}"),
                ("Final DPS", _fv(result.final_dps)),
                ("", ""),
                ("Magazine Size", _fv(result.magazine_size, "d")),
                ("Damage / Magazine", _fv(result.damage_per_magazine)),
                ("Magdump Time", _fv(result.magdump_time) + ("s" if result.magdump_time > 0 else "")),
                ("", ""),
                ("Realistic DPS", _fv(realistic_dps)),
            ]
            for label, val in rows:
                with dpg.table_row():
                    dpg.add_text(label)
                    t = dpg.add_text(val)
                    if label == "Final DPS":
                        dpg.configure_item(t, color=(100, 255, 100))
                    elif label == "Realistic DPS":
                        dpg.configure_item(t, color=(100, 200, 255))


# ── Tab: Spirit Damage ───────────────────────────────────────────


def _build_spirit_tab(parent: int | str) -> None:
    with dpg.group(parent=parent, horizontal=True):
        with dpg.child_window(width=320, height=-1):
            dpg.add_text("Ability", color=(200, 120, 255))
            dpg.add_input_float(label="Base Damage", tag="sp_base", default_value=100,
                                callback=_on_spirit_changed, width=120)
            dpg.add_input_float(label="Spirit Multiplier", tag="sp_mult", default_value=1.0,
                                callback=_on_spirit_changed, width=120, format="%.2f")
            dpg.add_input_int(label="Current Spirit", tag="sp_spirit", default_value=0,
                              callback=_on_spirit_changed, width=120)

            dpg.add_separator()
            dpg.add_text("Duration (DoT)", color=(200, 120, 255))
            dpg.add_input_float(label="Ability Duration", tag="sp_dur", default_value=0,
                                callback=_on_spirit_changed, width=120)
            dpg.add_input_float(label="Bonus Duration", tag="sp_bonus_dur", default_value=0,
                                callback=_on_spirit_changed, width=120)

            dpg.add_separator()
            dpg.add_text("Resist / Modifiers", color=(200, 120, 255))
            dpg.add_input_float(label="Spirit Resist %", tag="sp_resist", default_value=0,
                                min_value=0, max_value=100, callback=_on_spirit_changed, width=120)
            dpg.add_input_float(label="Resist Shred %", tag="sp_shred", default_value=0,
                                min_value=0, max_value=100, callback=_on_spirit_changed, width=120)
            dpg.add_input_float(label="Mystic Vuln %", tag="sp_vuln", default_value=0,
                                min_value=0, max_value=100, callback=_on_spirit_changed, width=120)
            dpg.add_input_float(label="Spirit Amp %", tag="sp_amp", default_value=0,
                                min_value=0, max_value=500, callback=_on_spirit_changed, width=120)

            dpg.add_separator()
            dpg.add_text("Item Effects", color=(200, 120, 255))
            dpg.add_input_int(label="EE Stacks", tag="sp_ee", default_value=0,
                              min_value=0, max_value=20, callback=_on_spirit_changed, width=120)
            dpg.add_input_float(label="Crippling %", tag="sp_crip", default_value=0,
                                callback=_on_spirit_changed, width=120)
            dpg.add_input_float(label="Soulshredder %", tag="sp_soul", default_value=0,
                                callback=_on_spirit_changed, width=120)

        with dpg.child_window(width=-1, height=-1):
            dpg.add_text("Results", color=(100, 200, 255))
            dpg.add_separator()
            with dpg.group(tag="sp_output"):
                pass

    _on_spirit_changed(None, None)


def _on_spirit_changed(sender, app_data) -> None:
    ability = AbilityConfig(
        base_damage=dpg.get_value("sp_base"),
        spirit_multiplier=dpg.get_value("sp_mult"),
        current_spirit=dpg.get_value("sp_spirit"),
        ability_duration=dpg.get_value("sp_dur"),
        bonus_duration=dpg.get_value("sp_bonus_dur"),
        enemy_spirit_resist=_pct("sp_resist"),
        resist_shred=_pct("sp_shred"),
        mystic_vuln=_pct("sp_vuln"),
        spirit_amp=_pct("sp_amp"),
        escalating_exposure_stacks=dpg.get_value("sp_ee"),
        crippling=_pct("sp_crip"),
        soulshredder=_pct("sp_soul"),
    )

    result = DamageCalculator.calculate_spirit(ability)
    total_duration = ability.ability_duration + ability.bonus_duration

    if dpg.does_item_exist("sp_output"):
        dpg.delete_item("sp_output", children_only=True)

    with dpg.group(parent="sp_output"):
        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, resizable=True):
            dpg.add_table_column(label="Metric", width_fixed=True, init_width_or_weight=200)
            dpg.add_table_column(label="Value", width_fixed=True, init_width_or_weight=140)

            rows = [
                ("Raw Damage", f"{result.raw_damage:.2f}"),
                ("Spirit Contribution", f"{result.spirit_contribution:.2f}"),
                ("Modified Damage", f"{result.modified_damage:.2f}", (100, 255, 100)),
            ]
            if total_duration > 0:
                rows.append(("Total Duration", f"{total_duration:.1f}s"))
                rows.append(("DPS", f"{result.dps:.2f}", (100, 200, 255)))
                rows.append(("Total DoT Damage", f"{result.total_dot_damage:.2f}"))

            for item in rows:
                label, val = item[0], item[1]
                color = item[2] if len(item) > 2 else None
                with dpg.table_row():
                    dpg.add_text(label)
                    t = dpg.add_text(val)
                    if color:
                        dpg.configure_item(t, color=color)


# ── Tab: Scaling ─────────────────────────────────────────────────


def _build_scaling_tab(parent: int | str) -> None:
    with dpg.group(parent=parent):
        with dpg.group(horizontal=True):
            dpg.add_combo(
                _hero_names, label="Hero", tag="sc_hero",
                default_value=_hero_names[0] if _hero_names else "",
                callback=_on_scaling_changed, width=200,
            )
            dpg.add_input_int(label="Max Boons", tag="sc_max", default_value=35,
                              min_value=1, max_value=50, callback=_on_scaling_changed, width=120)

        dpg.add_separator()

        # DPS plot
        with dpg.plot(label="DPS Scaling", height=250, width=-1, tag="sc_dps_plot"):
            dpg.add_plot_legend()
            dpg.add_plot_axis(dpg.mvXAxis, label="Boons", tag="sc_dps_x")
            dpg.add_plot_axis(dpg.mvYAxis, label="DPS", tag="sc_dps_y")

        # HP plot
        with dpg.plot(label="HP Scaling", height=250, width=-1, tag="sc_hp_plot"):
            dpg.add_plot_legend()
            dpg.add_plot_axis(dpg.mvXAxis, label="Boons", tag="sc_hp_x")
            dpg.add_plot_axis(dpg.mvYAxis, label="HP", tag="sc_hp_y")

        dpg.add_separator()
        with dpg.group(tag="sc_growth"):
            pass

    _on_scaling_changed(None, None)


def _on_scaling_changed(sender, app_data) -> None:
    hero = _get_hero("sc_hero")
    if not hero:
        return

    max_b = dpg.get_value("sc_max")
    curve = ScalingCalculator.scaling_curve(hero, max_b)
    growth = ScalingCalculator.growth_percentage(hero, max_b)

    boons = [float(s.boon_level) for s in curve]
    dps_vals = [s.dps for s in curve]
    hp_vals = [s.hp for s in curve]

    # Update DPS plot
    dpg.delete_item("sc_dps_y", children_only=True)
    dpg.add_line_series(boons, dps_vals, label=hero.name, parent="sc_dps_y")
    dpg.fit_axis_data("sc_dps_x")
    dpg.fit_axis_data("sc_dps_y")

    # Update HP plot
    dpg.delete_item("sc_hp_y", children_only=True)
    dpg.add_line_series(boons, hp_vals, label=hero.name, parent="sc_hp_y")
    dpg.fit_axis_data("sc_hp_x")
    dpg.fit_axis_data("sc_hp_y")

    # Growth info
    if dpg.does_item_exist("sc_growth"):
        dpg.delete_item("sc_growth", children_only=True)

    dps_g = f"{growth['dps_growth']:.1%}" if growth['dps_growth'] else "-"
    hp_g = f"{growth['hp_growth']:.1%}" if growth['hp_growth'] else "-"
    agg_g = f"{growth['aggregate_growth']:.1%}" if growth['aggregate_growth'] else "-"
    with dpg.group(parent="sc_growth"):
        dpg.add_text(
            f"Growth (0 -> {max_b} boons):  "
            f"DPS {dps_g}  |  HP {hp_g}  |  Aggregate {agg_g}",
            color=(180, 180, 180),
        )


# ── Tab: TTK ─────────────────────────────────────────────────────


def _build_ttk_tab(parent: int | str) -> None:
    with dpg.group(parent=parent, horizontal=True):
        # Left: inputs
        with dpg.child_window(width=320, height=-1):
            dpg.add_text("Attacker", color=(255, 200, 50))
            dpg.add_combo(
                _hero_names, label="Attacker", tag="ttk_atk",
                default_value=_hero_names[0] if _hero_names else "",
                callback=_on_ttk_changed, width=180,
            )

            dpg.add_separator()
            dpg.add_text("Defender", color=(255, 100, 100))
            dpg.add_combo(
                _hero_names, label="Defender", tag="ttk_def",
                default_value=_hero_names[1] if len(_hero_names) > 1 else "",
                callback=_on_ttk_changed, width=180,
            )

            dpg.add_separator()
            dpg.add_text("Config", color=(100, 200, 255))
            dpg.add_input_int(label="Boons", tag="ttk_boons", default_value=0,
                              min_value=0, max_value=50, callback=_on_ttk_changed, width=120)
            dpg.add_input_float(label="Weapon Dmg %", tag="ttk_wpn", default_value=0,
                                callback=_on_ttk_changed, width=120)
            dpg.add_input_float(label="Fire Rate %", tag="ttk_fr", default_value=0,
                                callback=_on_ttk_changed, width=120)
            dpg.add_input_float(label="Bullet Resist %", tag="ttk_resist", default_value=0,
                                min_value=0, max_value=100, callback=_on_ttk_changed, width=120)
            dpg.add_input_float(label="Shred %", tag="ttk_shred", default_value=0,
                                min_value=0, max_value=100, callback=_on_ttk_changed, width=120)
            dpg.add_input_float(label="Bonus HP", tag="ttk_hp", default_value=0,
                                callback=_on_ttk_changed, width=120)
            dpg.add_input_float(label="Accuracy %", tag="ttk_acc", default_value=50,
                                min_value=0, max_value=100, callback=_on_ttk_changed, width=120)
            dpg.add_input_float(label="Headshot %", tag="ttk_hs", default_value=15,
                                min_value=0, max_value=100, callback=_on_ttk_changed, width=120)

        # Right: results + plot
        with dpg.child_window(width=-1, height=-1):
            dpg.add_text("Results", color=(100, 200, 255))
            dpg.add_separator()
            with dpg.group(tag="ttk_output"):
                pass

            dpg.add_separator()
            dpg.add_text("TTK Over Boons", color=(100, 200, 255))
            with dpg.plot(label="TTK Curve", height=280, width=-1, tag="ttk_plot"):
                dpg.add_plot_legend()
                dpg.add_plot_axis(dpg.mvXAxis, label="Boons", tag="ttk_x")
                dpg.add_plot_axis(dpg.mvYAxis, label="TTK (s)", tag="ttk_y")

    _on_ttk_changed(None, None)


def _on_ttk_changed(sender, app_data) -> None:
    atk = _get_hero("ttk_atk")
    defender = _get_hero("ttk_def")
    if not atk or not defender:
        return

    shred_val = _pct("ttk_shred")
    config = CombatConfig(
        boons=dpg.get_value("ttk_boons"),
        weapon_damage_bonus=_pct("ttk_wpn"),
        fire_rate_bonus=_pct("ttk_fr"),
        shred=[shred_val] if shred_val > 0 else [],
        enemy_bullet_resist=_pct("ttk_resist"),
        enemy_bonus_hp=dpg.get_value("ttk_hp"),
        accuracy=_pct("ttk_acc"),
        headshot_rate=_pct("ttk_hs"),
    )

    result = TTKCalculator.calculate(atk, defender, config)

    # Update results table
    if dpg.does_item_exist("ttk_output"):
        dpg.delete_item("ttk_output", children_only=True)

    no_dps = result.effective_dps == 0
    no_hp = result.target_hp == 0

    with dpg.group(parent="ttk_output"):
        if no_dps:
            dpg.add_text(f"{atk.name} has no gun DPS data.", color=(255, 100, 100))
        if no_hp:
            dpg.add_text(f"{defender.name} has no HP data.", color=(255, 100, 100))
        if no_dps or no_hp:
            return

        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, resizable=True):
            dpg.add_table_column(label="Metric", width_fixed=True, init_width_or_weight=200)
            dpg.add_table_column(label="Value", width_fixed=True, init_width_or_weight=140)

            ideal_str = _fv(result.ttk_seconds) + ("s" if result.ttk_seconds > 0 else "")
            real_str = _fv(result.realistic_ttk) + ("s" if result.realistic_ttk > 0 else "")
            rows = [
                ("Target HP", f"{result.target_hp:.0f}"),
                ("Effective DPS", _fv(result.effective_dps)),
                ("Realistic DPS", _fv(result.realistic_dps)),
                ("", ""),
                ("Ideal TTK", ideal_str, (100, 255, 100)),
                ("Realistic TTK", real_str, (100, 200, 255)),
                ("Can One-Mag", "Yes" if result.can_one_mag else "No",
                 (100, 255, 100) if result.can_one_mag else (255, 100, 100)),
                ("Magazines Needed", _fv(result.magazines_needed, "d")),
            ]
            for item in rows:
                label, val = item[0], item[1]
                color = item[2] if len(item) > 2 else None
                with dpg.table_row():
                    dpg.add_text(label)
                    t = dpg.add_text(val)
                    if color:
                        dpg.configure_item(t, color=color)

    # Update TTK curve plot
    curve = TTKCalculator.ttk_curve(atk, defender, config, max_boons=35)
    boons = [float(b) for b, _ in curve]
    ideal = [r.ttk_seconds for _, r in curve]
    realistic = [r.realistic_ttk for _, r in curve]

    dpg.delete_item("ttk_y", children_only=True)
    dpg.add_line_series(boons, ideal, label="Ideal TTK", parent="ttk_y")
    dpg.add_line_series(boons, realistic, label="Realistic TTK", parent="ttk_y")
    dpg.fit_axis_data("ttk_x")
    dpg.fit_axis_data("ttk_y")


# ── Tab: Comparison ──────────────────────────────────────────────


def _build_comparison_tab(parent: int | str) -> None:
    with dpg.group(parent=parent):
        with dpg.group(horizontal=True):
            dpg.add_combo(
                _hero_names, label="Hero A", tag="cmp_a",
                default_value=_hero_names[0] if _hero_names else "",
                callback=_on_cmp_changed, width=180,
            )
            dpg.add_combo(
                _hero_names, label="Hero B", tag="cmp_b",
                default_value=_hero_names[1] if len(_hero_names) > 1 else "",
                callback=_on_cmp_changed, width=180,
            )
            dpg.add_input_int(label="Boon Level", tag="cmp_boon", default_value=0,
                              min_value=0, max_value=50, callback=_on_cmp_changed, width=120)

        dpg.add_separator()
        with dpg.group(tag="cmp_output"):
            pass

        dpg.add_separator()
        dpg.add_text("DPS Scaling Comparison", color=(100, 200, 255))
        with dpg.plot(label="DPS Comparison", height=280, width=-1, tag="cmp_plot"):
            dpg.add_plot_legend()
            dpg.add_plot_axis(dpg.mvXAxis, label="Boons", tag="cmp_x")
            dpg.add_plot_axis(dpg.mvYAxis, label="DPS", tag="cmp_y")

    _on_cmp_changed(None, None)


def _on_cmp_changed(sender, app_data) -> None:
    hero_a = _get_hero("cmp_a")
    hero_b = _get_hero("cmp_b")
    if not hero_a or not hero_b:
        return

    boon = dpg.get_value("cmp_boon")
    comp = ComparisonEngine.compare_two(hero_a, hero_b, boon)

    if dpg.does_item_exist("cmp_output"):
        dpg.delete_item("cmp_output", children_only=True)

    with dpg.group(parent="cmp_output"):
        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, resizable=True):
            dpg.add_table_column(label="Stat", width_fixed=True, init_width_or_weight=100)
            dpg.add_table_column(label=hero_a.name, width_fixed=True, init_width_or_weight=140)
            dpg.add_table_column(label=hero_b.name, width_fixed=True, init_width_or_weight=140)
            dpg.add_table_column(label="Ratio (A/B)", width_fixed=True, init_width_or_weight=100)

            rows = [
                ("DPS", comp.hero_a_dps, comp.hero_b_dps, comp.dps_ratio),
                ("HP", comp.hero_a_hp, comp.hero_b_hp, comp.hp_ratio),
                ("DPM", comp.hero_a_dpm, comp.hero_b_dpm, comp.dpm_ratio),
            ]
            for label, va, vb, ratio in rows:
                with dpg.table_row():
                    dpg.add_text(label)
                    dpg.add_text(_fv(va))
                    dpg.add_text(_fv(vb))
                    ratio_str = _fv(ratio)
                    t = dpg.add_text(ratio_str)
                    if ratio_str != "-" and ratio > 1.05:
                        dpg.configure_item(t, color=(100, 255, 100))
                    elif ratio_str != "-" and ratio < 0.95:
                        dpg.configure_item(t, color=(255, 100, 100))

    # DPS scaling plot
    curve_a = ScalingCalculator.scaling_curve(hero_a, 35)
    curve_b = ScalingCalculator.scaling_curve(hero_b, 35)
    boons_x = [float(s.boon_level) for s in curve_a]
    dps_a = [s.dps for s in curve_a]
    dps_b = [s.dps for s in curve_b]

    dpg.delete_item("cmp_y", children_only=True)
    dpg.add_line_series(boons_x, dps_a, label=hero_a.name, parent="cmp_y")
    dpg.add_line_series(boons_x, dps_b, label=hero_b.name, parent="cmp_y")
    dpg.fit_axis_data("cmp_x")
    dpg.fit_axis_data("cmp_y")


# ── Tab: Rankings ────────────────────────────────────────────────

_RANK_STATS = ["dps", "hp", "dpm", "bullet_damage", "fire_rate", "dps_growth", "hp_growth"]


def _build_rankings_tab(parent: int | str) -> None:
    with dpg.group(parent=parent):
        with dpg.group(horizontal=True):
            dpg.add_combo(
                _RANK_STATS, label="Rank By", tag="rk_stat",
                default_value="dps", callback=_on_rank_changed, width=160,
            )
            dpg.add_input_int(label="Boon Level", tag="rk_boon", default_value=0,
                              min_value=0, max_value=50, callback=_on_rank_changed, width=120)

        dpg.add_separator()
        with dpg.group(tag="rk_output"):
            pass

    _on_rank_changed(None, None)


def _on_rank_changed(sender, app_data) -> None:
    stat = dpg.get_value("rk_stat")
    boon = dpg.get_value("rk_boon")
    rankings = ComparisonEngine.rank_heroes(_heroes, stat, boon)

    if dpg.does_item_exist("rk_output"):
        dpg.delete_item("rk_output", children_only=True)

    with dpg.group(parent="rk_output"):
        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, resizable=True,
                       scrollY=True, height=500):
            dpg.add_table_column(label="#", width_fixed=True, init_width_or_weight=40)
            dpg.add_table_column(label="Hero", width_fixed=True, init_width_or_weight=160)
            dpg.add_table_column(label=stat.upper(), width_fixed=True, init_width_or_weight=140)

            for entry in rankings:
                with dpg.table_row():
                    dpg.add_text(f"{entry.rank}")
                    dpg.add_text(entry.hero_name)
                    if "growth" in stat:
                        fmt = f"{entry.value:.1%}" if entry.value != 0 else "-"
                    else:
                        fmt = _fv(entry.value)
                    t = dpg.add_text(fmt)
                    # Top 3 highlight
                    if entry.rank == 1:
                        dpg.configure_item(t, color=(255, 215, 0))
                    elif entry.rank == 2:
                        dpg.configure_item(t, color=(200, 200, 200))
                    elif entry.rank == 3:
                        dpg.configure_item(t, color=(205, 127, 50))


# ── Tab: Build Evaluator ────────────────────────────────────────


def _build_eval_tab(parent: int | str) -> None:
    with dpg.group(parent=parent, horizontal=True):
        # Left: inputs
        with dpg.child_window(width=380, height=-1):
            dpg.add_text("Hero", color=(255, 200, 50))
            dpg.add_combo(
                _hero_names, label="Hero", tag="bld_hero",
                default_value=_hero_names[0] if _hero_names else "",
                callback=_on_build_changed, width=200,
            )
            with dpg.group(horizontal=True):
                dpg.add_input_int(label="Boons", tag="bld_boons", default_value=0,
                                  min_value=0, max_value=50, callback=_on_build_changed, width=100)
                dpg.add_input_float(label="Accuracy %", tag="bld_acc", default_value=50,
                                    min_value=0, max_value=100, callback=_on_build_changed, width=100)

            dpg.add_separator()
            dpg.add_text("Add Item", color=(255, 200, 50))
            _cat_filter = ["All", "Weapon", "Vitality", "Spirit"]
            dpg.add_combo(
                _cat_filter, label="Category", tag="bld_cat_filter",
                default_value="All", callback=_on_item_filter_changed, width=120,
            )
            dpg.add_input_text(label="Search", tag="bld_search",
                               callback=_on_item_filter_changed, width=180)
            with dpg.child_window(height=250, tag="bld_item_list"):
                pass

            dpg.add_separator()
            dpg.add_text("Current Build", color=(100, 255, 100))
            with dpg.child_window(height=180, tag="bld_selected"):
                pass
            dpg.add_button(label="Clear Build", callback=_on_clear_build)

        # Right: results
        with dpg.child_window(width=-1, height=-1):
            dpg.add_text("Build Results", color=(100, 200, 255))
            dpg.add_separator()
            with dpg.group(tag="bld_output"):
                pass

    _on_item_filter_changed(None, None)


def _on_item_filter_changed(sender, app_data) -> None:
    """Update the item list based on category filter and search."""
    cat = dpg.get_value("bld_cat_filter").lower()
    search = dpg.get_value("bld_search").lower().strip()

    filtered = []
    for item in _items.values():
        if cat != "all" and item.category != cat:
            continue
        if search and search not in item.name.lower():
            continue
        filtered.append(item)

    filtered.sort(key=lambda x: (x.tier, x.cost, x.name))

    if dpg.does_item_exist("bld_item_list"):
        dpg.delete_item("bld_item_list", children_only=True)

    with dpg.group(parent="bld_item_list"):
        for item in filtered:
            cond = f"  [{item.condition}]" if item.condition else ""
            label = f"T{item.tier} {item.name} ({item.cost}){cond}"
            dpg.add_button(
                label=label,
                callback=_on_add_item,
                user_data=item.name,
                width=-1,
            )


def _on_add_item(sender, app_data, user_data) -> None:
    """Add an item to the build."""
    item_name = user_data
    if item_name in _items:
        _build_items.append(_items[item_name])
        _refresh_build_display()
        _on_build_changed(None, None)


def _on_remove_item(sender, app_data, user_data) -> None:
    """Remove an item from the build by index."""
    idx = user_data
    if 0 <= idx < len(_build_items):
        _build_items.pop(idx)
        _refresh_build_display()
        _on_build_changed(None, None)


def _on_clear_build(sender=None, app_data=None) -> None:
    """Clear all items from the build."""
    _build_items.clear()
    _refresh_build_display()
    _on_build_changed(None, None)


def _refresh_build_display() -> None:
    """Refresh the selected items display."""
    if dpg.does_item_exist("bld_selected"):
        dpg.delete_item("bld_selected", children_only=True)

    total_cost = sum(item.cost for item in _build_items)
    with dpg.group(parent="bld_selected"):
        dpg.add_text(f"Items: {len(_build_items)} | Cost: {total_cost}", color=(180, 180, 180))
        for i, item in enumerate(_build_items):
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="X",
                    callback=_on_remove_item,
                    user_data=i,
                    width=20,
                )
                dpg.add_text(f"{item.name} (T{item.tier}, {item.cost})")


def _on_build_changed(sender, app_data) -> None:
    """Recalculate and display build results."""
    hero = _get_hero("bld_hero")
    if not hero:
        return

    build = Build(items=list(_build_items))
    boons = dpg.get_value("bld_boons")
    accuracy = _pct("bld_acc")

    result = BuildEngine.evaluate_build(
        hero, build, boons=boons, accuracy=accuracy, headshot_rate=0.15,
    )

    if dpg.does_item_exist("bld_output"):
        dpg.delete_item("bld_output", children_only=True)

    with dpg.group(parent="bld_output"):
        bs = result.build_stats

        # Aggregated stats table
        dpg.add_text("Aggregated Stats", color=(255, 200, 50))
        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, resizable=True):
            dpg.add_table_column(label="Stat", width_fixed=True, init_width_or_weight=180)
            dpg.add_table_column(label="Value", width_fixed=True, init_width_or_weight=120)

            stat_rows = []
            if bs.weapon_damage_pct:
                stat_rows.append(("Weapon Damage", f"+{bs.weapon_damage_pct:.0%}"))
            if bs.fire_rate_pct:
                stat_rows.append(("Fire Rate", f"+{bs.fire_rate_pct:.0%}"))
            if bs.ammo_flat:
                stat_rows.append(("Ammo (flat)", f"+{bs.ammo_flat}"))
            if bs.ammo_pct:
                stat_rows.append(("Ammo (%)", f"+{bs.ammo_pct:.0%}"))
            if bs.bonus_hp:
                stat_rows.append(("Bonus HP", f"+{bs.bonus_hp:.0f}"))
            if bs.spirit_power:
                stat_rows.append(("Spirit Power", f"+{bs.spirit_power:.0f}"))
            if bs.bullet_resist_pct:
                stat_rows.append(("Bullet Resist", f"+{bs.bullet_resist_pct:.0%}"))
            if bs.spirit_resist_pct:
                stat_rows.append(("Spirit Resist", f"+{bs.spirit_resist_pct:.0%}"))
            if bs.bullet_resist_shred:
                stat_rows.append(("Bullet Shred", f"{bs.bullet_resist_shred:.0%}"))
            if bs.bullet_lifesteal:
                stat_rows.append(("Bullet Lifesteal", f"{bs.bullet_lifesteal:.0%}"))
            if bs.bullet_shield:
                stat_rows.append(("Bullet Shield", f"{bs.bullet_shield:.0f}"))
            if bs.cooldown_reduction:
                stat_rows.append(("CDR", f"{bs.cooldown_reduction:.0%}"))
            stat_rows.append(("Total Cost", f"{bs.total_cost}"))
            stat_rows.append(("Effective HP", f"{result.effective_hp:.0f}"))

            for label, val in stat_rows:
                with dpg.table_row():
                    dpg.add_text(label)
                    dpg.add_text(val)

        dpg.add_spacer(height=10)

        # Damage results
        if result.bullet_result:
            br = result.bullet_result
            dpg.add_text("DPS Output", color=(100, 255, 100))
            with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                           borders_innerV=True, borders_outerV=True, resizable=True):
                dpg.add_table_column(label="Metric", width_fixed=True, init_width_or_weight=180)
                dpg.add_table_column(label="Value", width_fixed=True, init_width_or_weight=120)

                dps_rows = [
                    ("Damage / Bullet", _fv(br.damage_per_bullet)),
                    ("Bullets / Sec", _fv(br.bullets_per_second)),
                    ("Raw DPS", _fv(br.raw_dps)),
                    ("Final DPS", _fv(br.final_dps)),
                    ("Magazine Size", _fv(br.magazine_size, "d")),
                    ("Damage / Mag", _fv(br.damage_per_magazine)),
                    ("Magdump Time", _fv(br.magdump_time) + "s" if br.magdump_time > 0 else "-"),
                ]
                for label, val in dps_rows:
                    with dpg.table_row():
                        dpg.add_text(label)
                        t = dpg.add_text(val)
                        if label == "Final DPS":
                            dpg.configure_item(t, color=(100, 255, 100))


# ── Tab: Build Optimizer ────────────────────────────────────────


def _build_optimizer_tab(parent: int | str) -> None:
    with dpg.group(parent=parent, horizontal=True):
        # Left: inputs
        with dpg.child_window(width=320, height=-1):
            dpg.add_text("Hero", color=(255, 200, 50))
            dpg.add_combo(
                _hero_names, label="Hero", tag="opt_hero",
                default_value=_hero_names[0] if _hero_names else "",
                width=200,
            )
            dpg.add_input_int(label="Boons", tag="opt_boons", default_value=0,
                              min_value=0, max_value=50, width=120)
            dpg.add_input_int(label="Soul Budget", tag="opt_budget", default_value=15000,
                              min_value=500, max_value=100000, width=120)
            dpg.add_input_int(label="Max Items", tag="opt_max_items", default_value=12,
                              min_value=1, max_value=24, width=120)

            dpg.add_separator()
            dpg.add_checkbox(label="Exclude conditional items", tag="opt_excl_cond",
                             default_value=True)

            dpg.add_separator()
            dpg.add_button(label="Optimize for Max DPS", callback=_on_optimize_dps, width=-1)

        # Right: results
        with dpg.child_window(width=-1, height=-1):
            dpg.add_text("Optimizer Results", color=(100, 200, 255))
            dpg.add_separator()
            with dpg.group(tag="opt_output"):
                pass


def _on_optimize_dps(sender=None, app_data=None) -> None:
    hero = _get_hero("opt_hero")
    if not hero:
        return

    budget = dpg.get_value("opt_budget")
    boons = dpg.get_value("opt_boons")
    max_items = dpg.get_value("opt_max_items")
    excl_cond = dpg.get_value("opt_excl_cond")

    build = BuildOptimizer.best_dps_items(
        _items, hero, budget=budget, boons=boons,
        max_items=max_items, exclude_conditional=excl_cond,
    )
    result = BuildEngine.evaluate_build(hero, build, boons=boons)

    if dpg.does_item_exist("opt_output"):
        dpg.delete_item("opt_output", children_only=True)

    with dpg.group(parent="opt_output"):
        dpg.add_text(
            f"Budget: {budget} | Spent: {build.total_cost} | Items: {len(build.items)}",
            color=(180, 180, 180),
        )
        dpg.add_spacer(height=5)

        # Item list
        dpg.add_text("Optimal Items", color=(255, 200, 50))
        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, resizable=True):
            dpg.add_table_column(label="#", width_fixed=True, init_width_or_weight=30)
            dpg.add_table_column(label="Item", width_fixed=True, init_width_or_weight=220)
            dpg.add_table_column(label="Category", width_fixed=True, init_width_or_weight=80)
            dpg.add_table_column(label="Tier", width_fixed=True, init_width_or_weight=40)
            dpg.add_table_column(label="Cost", width_fixed=True, init_width_or_weight=60)

            for i, item in enumerate(build.items, 1):
                with dpg.table_row():
                    dpg.add_text(f"{i}")
                    dpg.add_text(item.name)
                    dpg.add_text(item.category.title())
                    dpg.add_text(f"T{item.tier}")
                    dpg.add_text(f"{item.cost}")

        dpg.add_spacer(height=10)

        # DPS results
        if result.bullet_result:
            br = result.bullet_result
            dpg.add_text("DPS Output", color=(100, 255, 100))
            with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                           borders_innerV=True, borders_outerV=True, resizable=True):
                dpg.add_table_column(label="Metric", width_fixed=True, init_width_or_weight=180)
                dpg.add_table_column(label="Value", width_fixed=True, init_width_or_weight=120)

                rows = [
                    ("Raw DPS", _fv(br.raw_dps)),
                    ("Final DPS", _fv(br.final_dps)),
                    ("Damage / Bullet", _fv(br.damage_per_bullet)),
                    ("Bullets / Sec", _fv(br.bullets_per_second)),
                    ("Magazine Size", _fv(br.magazine_size, "d")),
                    ("Damage / Mag", _fv(br.damage_per_magazine)),
                    ("Effective HP", f"{result.effective_hp:.0f}"),
                ]
                for label, val in rows:
                    with dpg.table_row():
                        dpg.add_text(label)
                        t = dpg.add_text(val)
                        if label in ("Raw DPS", "Final DPS"):
                            dpg.configure_item(t, color=(100, 255, 100))


# ── Main entry point ─────────────────────────────────────────────


def run_gui() -> None:
    """Launch the Dear PyGui Deadlock simulator."""
    global _heroes, _hero_names, _items, _item_names

    _heroes = load_heroes()
    _hero_names = sorted(_heroes.keys())
    _items = load_items()
    _item_names = sorted(_items.keys())

    dpg.create_context()

    with dpg.window(tag="primary_window"):
        dpg.add_text("DEADLOCK COMBAT SIMULATOR", color=(255, 200, 50))
        dpg.add_text(f"{len(_heroes)} heroes, {len(_items)} items loaded", color=(140, 140, 140))
        dpg.add_separator()

        with dpg.tab_bar():
            with dpg.tab(label="Hero Stats"):
                _build_hero_stats_tab(dpg.last_item())

            with dpg.tab(label="Bullet Damage"):
                _build_bullet_tab(dpg.last_item())

            with dpg.tab(label="Spirit Damage"):
                _build_spirit_tab(dpg.last_item())

            with dpg.tab(label="Scaling"):
                _build_scaling_tab(dpg.last_item())

            with dpg.tab(label="TTK"):
                _build_ttk_tab(dpg.last_item())

            with dpg.tab(label="Comparison"):
                _build_comparison_tab(dpg.last_item())

            with dpg.tab(label="Rankings"):
                _build_rankings_tab(dpg.last_item())

            with dpg.tab(label="Build"):
                _build_eval_tab(dpg.last_item())

            with dpg.tab(label="Optimizer"):
                _build_optimizer_tab(dpg.last_item())

    dpg.create_viewport(title="Deadlock Combat Simulator", width=1100, height=750)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("primary_window", True)
    dpg.start_dearpygui()
    dpg.destroy_context()


if __name__ == "__main__":
    run_gui()
