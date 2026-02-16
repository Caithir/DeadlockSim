"""NiceGUI web UI for the Deadlock combat simulator.

Browser-based UI with tabs for each simulator feature.
All calculations delegated to deadlock_sim.engine — this module
is purely presentation.
"""

from __future__ import annotations

import math

from nicegui import ui

from ..data import load_heroes, load_items
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


def _fv(v: float, fmt: str = ".2f", zero_as_na: bool = True) -> str:
    """Format a numeric value for display, showing '-' for missing/inf/nan."""
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
        return "-"
    if zero_as_na and v == 0:
        return "-"
    return f"{v:{fmt}}"


# ── Tab: Hero Stats ──────────────────────────────────────────────


def _build_hero_stats_tab() -> None:
    hero_select = ui.select(
        options=_hero_names,
        value=_hero_names[0] if _hero_names else "",
        label="Hero",
    ).classes("w-52")
    output = ui.column().classes("w-full")

    def update(_=None):
        hero = _heroes.get(hero_select.value)
        output.clear()
        if not hero:
            return
        with output:
            ui.label(hero.name).classes("text-lg font-bold text-amber-400")
            if hero.hero_labs:
                ui.label("[Hero Labs - stats may be incomplete]").classes("text-red-400")

            has_gun = hero.base_bullet_damage > 0 or hero.base_fire_rate > 0
            rows = [
                {"stat": "Bullet Damage", "value": f"{hero.base_bullet_damage:.2f}" if has_gun else "-"},
                {"stat": "Pellets", "value": f"{hero.pellets}" if has_gun else "-"},
                {"stat": "Fire Rate", "value": f"{hero.base_fire_rate:.2f} /s" if hero.base_fire_rate > 0 else "-"},
                {"stat": "Base DPS", "value": _fv(hero.base_dps)},
                {"stat": "Magazine", "value": _fv(hero.base_ammo, "d")},
                {"stat": "DPM", "value": _fv(hero.base_dpm)},
                {"stat": "Falloff Range", "value": f"{hero.falloff_range_min:.0f}m - {hero.falloff_range_max:.0f}m" if has_gun else "-"},
                {"stat": "", "value": ""},
                {"stat": "HP", "value": _fv(hero.base_hp, ".0f")},
                {"stat": "Regen", "value": f"{hero.base_regen:.1f} /s"},
                {"stat": "Move Speed", "value": _fv(hero.base_move_speed)},
                {"stat": "Sprint", "value": f"{hero.base_sprint:.1f}"},
                {"stat": "Stamina", "value": _fv(hero.base_stamina, "d")},
                {"stat": "", "value": ""},
                {"stat": "Dmg Gain / Boon", "value": _fv(hero.damage_gain, "+.2f")},
                {"stat": "HP Gain / Boon", "value": _fv(hero.hp_gain, "+.0f")},
                {"stat": "Spirit Gain / Boon", "value": _fv(hero.spirit_gain, "+.1f")},
            ]

            columns = [
                {"name": "stat", "label": "Stat", "field": "stat", "align": "left"},
                {"name": "value", "label": "Value", "field": "value", "align": "left"},
            ]
            ui.table(columns=columns, rows=rows, row_key="stat").classes("w-96").props("dense flat bordered")

    hero_select.on_value_change(update)
    update()


# ── Tab: Bullet Damage ──────────────────────────────────────────


def _build_bullet_tab() -> None:
    with ui.row().classes("w-full gap-6"):
        # Left: inputs
        with ui.column().classes("w-80 gap-2"):
            ui.label("Attacker").classes("text-amber-400 font-bold")
            bd_hero = ui.select(options=_hero_names, value=_hero_names[0] if _hero_names else "", label="Hero").classes("w-48")
            bd_boons = ui.number(label="Boons", value=0, min=0, max=50, step=1).classes("w-32")
            bd_wpn = ui.number(label="Weapon Dmg %", value=0, min=0, max=500).classes("w-32")
            bd_fr = ui.number(label="Fire Rate %", value=0, min=0, max=500).classes("w-32")
            bd_ammo = ui.number(label="Ammo Increase %", value=0, min=0, max=500).classes("w-32")

            ui.separator()
            ui.label("Shred Sources").classes("text-amber-400 font-bold")
            bd_shred1 = ui.number(label="Shred 1 %", value=0, min=0, max=100).classes("w-32")
            bd_shred2 = ui.number(label="Shred 2 %", value=0, min=0, max=100).classes("w-32")

            ui.separator()
            ui.label("Defender").classes("text-amber-400 font-bold")
            bd_resist = ui.number(label="Bullet Resist %", value=0, min=0, max=100).classes("w-32")

            ui.separator()
            ui.label("Accuracy Model").classes("text-amber-400 font-bold")
            bd_acc = ui.number(label="Accuracy %", value=100, min=0, max=100).classes("w-32")
            bd_hs = ui.number(label="Headshot Rate %", value=0, min=0, max=100).classes("w-32")

        # Right: results
        with ui.column().classes("flex-grow"):
            ui.label("Results").classes("text-sky-400 font-bold")
            ui.separator()
            bd_output = ui.column().classes("w-full")

    def update(_=None):
        hero = _heroes.get(bd_hero.value)
        bd_output.clear()
        if not hero:
            return

        shred_sources = []
        s1, s2 = (bd_shred1.value or 0) / 100.0, (bd_shred2.value or 0) / 100.0
        if s1 > 0:
            shred_sources.append(s1)
        if s2 > 0:
            shred_sources.append(s2)

        config = CombatConfig(
            boons=int(bd_boons.value or 0),
            weapon_damage_bonus=(bd_wpn.value or 0) / 100.0,
            fire_rate_bonus=(bd_fr.value or 0) / 100.0,
            ammo_increase=(bd_ammo.value or 0) / 100.0,
            shred=shred_sources,
            enemy_bullet_resist=(bd_resist.value or 0) / 100.0,
            accuracy=(bd_acc.value or 0) / 100.0,
            headshot_rate=(bd_hs.value or 0) / 100.0,
        )

        result = DamageCalculator.calculate_bullet(hero, config)
        realistic_dps = DamageCalculator.dps_with_accuracy(hero, config)

        with bd_output:
            if result.bullets_per_second == 0 and result.damage_per_bullet == 0:
                ui.label(f"No gun data available for {hero.name}.").classes("text-red-400")
                return

            rows = [
                {"metric": "Damage / Bullet", "value": _fv(result.damage_per_bullet)},
                {"metric": "Bullets / Sec", "value": _fv(result.bullets_per_second)},
                {"metric": "Raw DPS", "value": _fv(result.raw_dps)},
                {"metric": "", "value": ""},
                {"metric": "Total Shred", "value": f"{result.total_shred:.1%}"},
                {"metric": "Final Resist", "value": f"{result.final_resist:.1%}"},
                {"metric": "Final DPS", "value": _fv(result.final_dps)},
                {"metric": "", "value": ""},
                {"metric": "Magazine Size", "value": _fv(result.magazine_size, "d")},
                {"metric": "Damage / Magazine", "value": _fv(result.damage_per_magazine)},
                {"metric": "Magdump Time", "value": _fv(result.magdump_time) + ("s" if result.magdump_time > 0 else "")},
                {"metric": "", "value": ""},
                {"metric": "Realistic DPS", "value": _fv(realistic_dps)},
            ]
            columns = [
                {"name": "metric", "label": "Metric", "field": "metric", "align": "left"},
                {"name": "value", "label": "Value", "field": "value", "align": "left"},
            ]
            ui.table(columns=columns, rows=rows, row_key="metric").classes("w-96").props("dense flat bordered")

    for inp in [bd_hero, bd_boons, bd_wpn, bd_fr, bd_ammo, bd_shred1, bd_shred2, bd_resist, bd_acc, bd_hs]:
        inp.on_value_change(update)
    update()


# ── Tab: Spirit Damage ───────────────────────────────────────────


def _build_spirit_tab() -> None:
    with ui.row().classes("w-full gap-6"):
        with ui.column().classes("w-80 gap-2"):
            ui.label("Ability").classes("text-purple-400 font-bold")
            sp_base = ui.number(label="Base Damage", value=100).classes("w-32")
            sp_mult = ui.number(label="Spirit Multiplier", value=1.0, step=0.1, format="%.2f").classes("w-32")
            sp_spirit = ui.number(label="Current Spirit", value=0, step=1).classes("w-32")

            ui.separator()
            ui.label("Duration (DoT)").classes("text-purple-400 font-bold")
            sp_dur = ui.number(label="Ability Duration", value=0).classes("w-32")
            sp_bonus_dur = ui.number(label="Bonus Duration", value=0).classes("w-32")

            ui.separator()
            ui.label("Resist / Modifiers").classes("text-purple-400 font-bold")
            sp_resist = ui.number(label="Spirit Resist %", value=0, min=0, max=100).classes("w-32")
            sp_shred = ui.number(label="Resist Shred %", value=0, min=0, max=100).classes("w-32")
            sp_vuln = ui.number(label="Mystic Vuln %", value=0, min=0, max=100).classes("w-32")
            sp_amp = ui.number(label="Spirit Amp %", value=0, min=0, max=500).classes("w-32")

            ui.separator()
            ui.label("Item Effects").classes("text-purple-400 font-bold")
            sp_ee = ui.number(label="EE Stacks", value=0, min=0, max=20, step=1).classes("w-32")
            sp_crip = ui.number(label="Crippling %", value=0).classes("w-32")
            sp_soul = ui.number(label="Soulshredder %", value=0).classes("w-32")

        with ui.column().classes("flex-grow"):
            ui.label("Results").classes("text-sky-400 font-bold")
            ui.separator()
            sp_output = ui.column().classes("w-full")

    def update(_=None):
        ability = AbilityConfig(
            base_damage=sp_base.value or 0,
            spirit_multiplier=sp_mult.value or 0,
            current_spirit=int(sp_spirit.value or 0),
            ability_duration=sp_dur.value or 0,
            bonus_duration=sp_bonus_dur.value or 0,
            enemy_spirit_resist=(sp_resist.value or 0) / 100.0,
            resist_shred=(sp_shred.value or 0) / 100.0,
            mystic_vuln=(sp_vuln.value or 0) / 100.0,
            spirit_amp=(sp_amp.value or 0) / 100.0,
            escalating_exposure_stacks=int(sp_ee.value or 0),
            crippling=(sp_crip.value or 0) / 100.0,
            soulshredder=(sp_soul.value or 0) / 100.0,
        )

        result = DamageCalculator.calculate_spirit(ability)
        total_duration = ability.ability_duration + ability.bonus_duration

        sp_output.clear()
        with sp_output:
            rows = [
                {"metric": "Raw Damage", "value": f"{result.raw_damage:.2f}"},
                {"metric": "Spirit Contribution", "value": f"{result.spirit_contribution:.2f}"},
                {"metric": "Modified Damage", "value": f"{result.modified_damage:.2f}"},
            ]
            if total_duration > 0:
                rows.append({"metric": "Total Duration", "value": f"{total_duration:.1f}s"})
                rows.append({"metric": "DPS", "value": f"{result.dps:.2f}"})
                rows.append({"metric": "Total DoT Damage", "value": f"{result.total_dot_damage:.2f}"})

            columns = [
                {"name": "metric", "label": "Metric", "field": "metric", "align": "left"},
                {"name": "value", "label": "Value", "field": "value", "align": "left"},
            ]
            ui.table(columns=columns, rows=rows, row_key="metric").classes("w-96").props("dense flat bordered")

    for inp in [sp_base, sp_mult, sp_spirit, sp_dur, sp_bonus_dur, sp_resist, sp_shred, sp_vuln, sp_amp, sp_ee, sp_crip, sp_soul]:
        inp.on_value_change(update)
    update()


# ── Tab: Scaling ─────────────────────────────────────────────────


def _build_scaling_tab() -> None:
    with ui.row().classes("gap-4 items-end"):
        sc_hero = ui.select(options=_hero_names, value=_hero_names[0] if _hero_names else "", label="Hero").classes("w-52")
        sc_max = ui.number(label="Max Boons", value=35, min=1, max=50, step=1).classes("w-32")

    ui.separator()
    dps_chart = ui.echart({
        "title": {"text": "DPS Scaling", "textStyle": {"color": "#ccc"}},
        "tooltip": {"trigger": "axis"},
        "legend": {"textStyle": {"color": "#ccc"}},
        "xAxis": {"type": "value", "name": "Boons", "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"}},
        "yAxis": {"type": "value", "name": "DPS", "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"}},
        "series": [],
        "backgroundColor": "transparent",
    }).classes("w-full h-64")

    hp_chart = ui.echart({
        "title": {"text": "HP Scaling", "textStyle": {"color": "#ccc"}},
        "tooltip": {"trigger": "axis"},
        "legend": {"textStyle": {"color": "#ccc"}},
        "xAxis": {"type": "value", "name": "Boons", "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"}},
        "yAxis": {"type": "value", "name": "HP", "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"}},
        "series": [],
        "backgroundColor": "transparent",
    }).classes("w-full h-64")

    ui.separator()
    growth_label = ui.label("").classes("text-gray-400")

    def update(_=None):
        hero = _heroes.get(sc_hero.value)
        if not hero:
            return

        max_b = int(sc_max.value or 35)
        curve = ScalingCalculator.scaling_curve(hero, max_b)
        growth = ScalingCalculator.growth_percentage(hero, max_b)

        boons = [s.boon_level for s in curve]
        dps_vals = [s.dps for s in curve]
        hp_vals = [s.hp for s in curve]

        dps_chart.options["series"] = [
            {"name": hero.name, "type": "line", "data": list(zip(boons, dps_vals)), "smooth": True},
        ]
        dps_chart.update()

        hp_chart.options["series"] = [
            {"name": hero.name, "type": "line", "data": list(zip(boons, hp_vals)), "smooth": True},
        ]
        hp_chart.update()

        dps_g = f"{growth['dps_growth']:.1%}" if growth["dps_growth"] else "-"
        hp_g = f"{growth['hp_growth']:.1%}" if growth["hp_growth"] else "-"
        agg_g = f"{growth['aggregate_growth']:.1%}" if growth["aggregate_growth"] else "-"
        growth_label.text = f"Growth (0 → {max_b} boons):  DPS {dps_g}  |  HP {hp_g}  |  Aggregate {agg_g}"

    sc_hero.on_value_change(update)
    sc_max.on_value_change(update)
    update()


# ── Tab: TTK ─────────────────────────────────────────────────────


def _build_ttk_tab() -> None:
    with ui.row().classes("w-full gap-6"):
        # Left: inputs
        with ui.column().classes("w-80 gap-2"):
            ui.label("Attacker").classes("text-amber-400 font-bold")
            ttk_atk = ui.select(options=_hero_names, value=_hero_names[0] if _hero_names else "", label="Attacker").classes("w-48")

            ui.separator()
            ui.label("Defender").classes("text-red-400 font-bold")
            ttk_def = ui.select(options=_hero_names, value=_hero_names[1] if len(_hero_names) > 1 else "", label="Defender").classes("w-48")

            ui.separator()
            ui.label("Config").classes("text-sky-400 font-bold")
            ttk_boons = ui.number(label="Boons", value=0, min=0, max=50, step=1).classes("w-32")
            ttk_wpn = ui.number(label="Weapon Dmg %", value=0).classes("w-32")
            ttk_fr = ui.number(label="Fire Rate %", value=0).classes("w-32")
            ttk_resist = ui.number(label="Bullet Resist %", value=0, min=0, max=100).classes("w-32")
            ttk_shred = ui.number(label="Shred %", value=0, min=0, max=100).classes("w-32")
            ttk_hp = ui.number(label="Bonus HP", value=0).classes("w-32")
            ttk_acc = ui.number(label="Accuracy %", value=50, min=0, max=100).classes("w-32")
            ttk_hs = ui.number(label="Headshot %", value=15, min=0, max=100).classes("w-32")

        # Right: results + plot
        with ui.column().classes("flex-grow"):
            ui.label("Results").classes("text-sky-400 font-bold")
            ui.separator()
            ttk_output = ui.column().classes("w-full")

            ui.separator()
            ui.label("TTK Over Boons").classes("text-sky-400 font-bold")
            ttk_chart = ui.echart({
                "title": {"text": "TTK Curve", "textStyle": {"color": "#ccc"}},
                "tooltip": {"trigger": "axis"},
                "legend": {"textStyle": {"color": "#ccc"}},
                "xAxis": {"type": "value", "name": "Boons", "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"}},
                "yAxis": {"type": "value", "name": "TTK (s)", "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"}},
                "series": [],
                "backgroundColor": "transparent",
            }).classes("w-full h-72")

    def update(_=None):
        atk = _heroes.get(ttk_atk.value)
        defender = _heroes.get(ttk_def.value)
        if not atk or not defender:
            return

        shred_val = (ttk_shred.value or 0) / 100.0
        config = CombatConfig(
            boons=int(ttk_boons.value or 0),
            weapon_damage_bonus=(ttk_wpn.value or 0) / 100.0,
            fire_rate_bonus=(ttk_fr.value or 0) / 100.0,
            shred=[shred_val] if shred_val > 0 else [],
            enemy_bullet_resist=(ttk_resist.value or 0) / 100.0,
            enemy_bonus_hp=ttk_hp.value or 0,
            accuracy=(ttk_acc.value or 0) / 100.0,
            headshot_rate=(ttk_hs.value or 0) / 100.0,
        )

        result = TTKCalculator.calculate(atk, defender, config)

        ttk_output.clear()
        no_dps = result.effective_dps == 0
        no_hp = result.target_hp == 0

        with ttk_output:
            if no_dps:
                ui.label(f"{atk.name} has no gun DPS data.").classes("text-red-400")
            if no_hp:
                ui.label(f"{defender.name} has no HP data.").classes("text-red-400")
            if no_dps or no_hp:
                return

            ideal_str = _fv(result.ttk_seconds) + ("s" if result.ttk_seconds > 0 else "")
            real_str = _fv(result.realistic_ttk) + ("s" if result.realistic_ttk > 0 else "")
            rows = [
                {"metric": "Target HP", "value": f"{result.target_hp:.0f}"},
                {"metric": "Effective DPS", "value": _fv(result.effective_dps)},
                {"metric": "Realistic DPS", "value": _fv(result.realistic_dps)},
                {"metric": "", "value": ""},
                {"metric": "Ideal TTK", "value": ideal_str},
                {"metric": "Realistic TTK", "value": real_str},
                {"metric": "Can One-Mag", "value": "Yes" if result.can_one_mag else "No"},
                {"metric": "Magazines Needed", "value": _fv(result.magazines_needed, "d")},
            ]
            columns = [
                {"name": "metric", "label": "Metric", "field": "metric", "align": "left"},
                {"name": "value", "label": "Value", "field": "value", "align": "left"},
            ]
            ui.table(columns=columns, rows=rows, row_key="metric").classes("w-96").props("dense flat bordered")

        # Update TTK curve plot
        curve = TTKCalculator.ttk_curve(atk, defender, config, max_boons=35)
        boons = [float(b) for b, _ in curve]
        ideal = [r.ttk_seconds for _, r in curve]
        realistic = [r.realistic_ttk for _, r in curve]

        ttk_chart.options["series"] = [
            {"name": "Ideal TTK", "type": "line", "data": list(zip(boons, ideal)), "smooth": True},
            {"name": "Realistic TTK", "type": "line", "data": list(zip(boons, realistic)), "smooth": True},
        ]
        ttk_chart.update()

    for inp in [ttk_atk, ttk_def, ttk_boons, ttk_wpn, ttk_fr, ttk_resist, ttk_shred, ttk_hp, ttk_acc, ttk_hs]:
        inp.on_value_change(update)
    update()


# ── Tab: Comparison ──────────────────────────────────────────────


def _build_comparison_tab() -> None:
    with ui.row().classes("gap-4 items-end"):
        cmp_a = ui.select(options=_hero_names, value=_hero_names[0] if _hero_names else "", label="Hero A").classes("w-48")
        cmp_b = ui.select(options=_hero_names, value=_hero_names[1] if len(_hero_names) > 1 else "", label="Hero B").classes("w-48")
        cmp_boon = ui.number(label="Boon Level", value=0, min=0, max=50, step=1).classes("w-32")

    ui.separator()
    cmp_output = ui.column().classes("w-full")

    ui.separator()
    ui.label("DPS Scaling Comparison").classes("text-sky-400 font-bold")
    cmp_chart = ui.echart({
        "title": {"text": "DPS Comparison", "textStyle": {"color": "#ccc"}},
        "tooltip": {"trigger": "axis"},
        "legend": {"textStyle": {"color": "#ccc"}},
        "xAxis": {"type": "value", "name": "Boons", "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"}},
        "yAxis": {"type": "value", "name": "DPS", "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"}},
        "series": [],
        "backgroundColor": "transparent",
    }).classes("w-full h-72")

    def update(_=None):
        hero_a = _heroes.get(cmp_a.value)
        hero_b = _heroes.get(cmp_b.value)
        if not hero_a or not hero_b:
            return

        boon = int(cmp_boon.value or 0)
        comp = ComparisonEngine.compare_two(hero_a, hero_b, boon)

        cmp_output.clear()
        with cmp_output:
            rows_data = [
                ("DPS", comp.hero_a_dps, comp.hero_b_dps, comp.dps_ratio),
                ("HP", comp.hero_a_hp, comp.hero_b_hp, comp.hp_ratio),
                ("DPM", comp.hero_a_dpm, comp.hero_b_dpm, comp.dpm_ratio),
            ]
            rows = []
            for label, va, vb, ratio in rows_data:
                rows.append({
                    "stat": label,
                    "hero_a": _fv(va),
                    "hero_b": _fv(vb),
                    "ratio": _fv(ratio),
                })
            columns = [
                {"name": "stat", "label": "Stat", "field": "stat", "align": "left"},
                {"name": "hero_a", "label": hero_a.name, "field": "hero_a", "align": "left"},
                {"name": "hero_b", "label": hero_b.name, "field": "hero_b", "align": "left"},
                {"name": "ratio", "label": "Ratio (A/B)", "field": "ratio", "align": "left"},
            ]
            ui.table(columns=columns, rows=rows, row_key="stat").classes("w-full max-w-2xl").props("dense flat bordered")

        # DPS scaling plot
        curve_a = ScalingCalculator.scaling_curve(hero_a, 35)
        curve_b = ScalingCalculator.scaling_curve(hero_b, 35)
        boons_x = [s.boon_level for s in curve_a]
        dps_a = [s.dps for s in curve_a]
        dps_b = [s.dps for s in curve_b]

        cmp_chart.options["series"] = [
            {"name": hero_a.name, "type": "line", "data": list(zip(boons_x, dps_a)), "smooth": True},
            {"name": hero_b.name, "type": "line", "data": list(zip(boons_x, dps_b)), "smooth": True},
        ]
        cmp_chart.update()

    for inp in [cmp_a, cmp_b, cmp_boon]:
        inp.on_value_change(update)
    update()


# ── Tab: Rankings ────────────────────────────────────────────────

_RANK_STATS = ["dps", "hp", "dpm", "bullet_damage", "fire_rate", "dps_growth", "hp_growth"]


def _build_rankings_tab() -> None:
    with ui.row().classes("gap-4 items-end"):
        rk_stat = ui.select(options=_RANK_STATS, value="dps", label="Rank By").classes("w-44")
        rk_boon = ui.number(label="Boon Level", value=0, min=0, max=50, step=1).classes("w-32")

    ui.separator()
    rk_output = ui.column().classes("w-full")

    def update(_=None):
        stat = rk_stat.value
        boon = int(rk_boon.value or 0)
        rankings = ComparisonEngine.rank_heroes(_heroes, stat, boon)

        rk_output.clear()
        with rk_output:
            rows = []
            for entry in rankings:
                if "growth" in stat:
                    fmt = f"{entry.value:.1%}" if entry.value != 0 else "-"
                else:
                    fmt = _fv(entry.value)
                rows.append({
                    "rank": entry.rank,
                    "hero": entry.hero_name,
                    "value": fmt,
                })

            columns = [
                {"name": "rank", "label": "#", "field": "rank", "align": "left", "sortable": True},
                {"name": "hero", "label": "Hero", "field": "hero", "align": "left", "sortable": True},
                {"name": "value", "label": stat.upper(), "field": "value", "align": "left", "sortable": True},
            ]
            ui.table(
                columns=columns, rows=rows, row_key="rank",
            ).classes("w-full max-w-xl").props("dense flat bordered").style("max-height: 500px")

    rk_stat.on_value_change(update)
    rk_boon.on_value_change(update)
    update()


# ── Tab: Build Evaluator ────────────────────────────────────────


def _build_eval_tab() -> None:
    with ui.row().classes("w-full gap-6"):
        # Left: inputs
        with ui.column().classes("w-96 gap-2"):
            ui.label("Hero").classes("text-amber-400 font-bold")
            bld_hero = ui.select(options=_hero_names, value=_hero_names[0] if _hero_names else "", label="Hero").classes("w-52")
            with ui.row().classes("gap-2"):
                bld_boons = ui.number(label="Boons", value=0, min=0, max=50, step=1).classes("w-28")
                bld_acc = ui.number(label="Accuracy %", value=50, min=0, max=100).classes("w-28")

            ui.separator()
            ui.label("Add Item").classes("text-amber-400 font-bold")
            cat_filter = ui.select(options=["All", "Weapon", "Vitality", "Spirit"], value="All", label="Category").classes("w-32")
            bld_search = ui.input(label="Search", placeholder="Filter items...").classes("w-48")
            item_list_container = ui.scroll_area().classes("w-full h-64 border rounded")

            ui.separator()
            ui.label("Current Build").classes("text-green-400 font-bold")
            build_display = ui.column().classes("w-full")
            ui.button("Clear Build", on_click=lambda: clear_build()).classes("w-full")

        # Right: results
        with ui.column().classes("flex-grow"):
            ui.label("Build Results").classes("text-sky-400 font-bold")
            ui.separator()
            bld_output = ui.column().classes("w-full")

    def refresh_item_list(_=None):
        cat = (cat_filter.value or "All").lower()
        search = (bld_search.value or "").lower().strip()

        filtered = []
        for item in _items.values():
            if cat != "all" and item.category != cat:
                continue
            if search and search not in item.name.lower():
                continue
            filtered.append(item)

        filtered.sort(key=lambda x: (x.tier, x.cost, x.name))

        item_list_container.clear()
        with item_list_container:
            with ui.column().classes("w-full gap-0"):
                for item in filtered:
                    cond = f"  [{item.condition}]" if item.condition else ""
                    label = f"T{item.tier} {item.name} ({item.cost}){cond}"
                    ui.button(
                        label,
                        on_click=lambda _, it=item: add_item(it),
                    ).props("flat dense no-caps").classes("w-full text-left justify-start text-xs")

    def add_item(item: Item):
        _build_items.append(item)
        refresh_build_display()
        update_results()

    def remove_item(idx: int):
        if 0 <= idx < len(_build_items):
            _build_items.pop(idx)
            refresh_build_display()
            update_results()

    def clear_build():
        _build_items.clear()
        refresh_build_display()
        update_results()

    def refresh_build_display():
        build_display.clear()
        total_cost = sum(item.cost for item in _build_items)
        with build_display:
            ui.label(f"Items: {len(_build_items)} | Cost: {total_cost}").classes("text-gray-400")
            for i, item in enumerate(_build_items):
                with ui.row().classes("items-center gap-1"):
                    ui.button(
                        "X",
                        on_click=lambda _, idx=i: remove_item(idx),
                    ).props("flat dense color=red size=xs")
                    ui.label(f"{item.name} (T{item.tier}, {item.cost})").classes("text-sm")

    def update_results(_=None):
        hero = _heroes.get(bld_hero.value)
        bld_output.clear()
        if not hero:
            return

        build = Build(items=list(_build_items))
        boons = int(bld_boons.value or 0)
        accuracy = (bld_acc.value or 0) / 100.0

        result = BuildEngine.evaluate_build(
            hero, build, boons=boons, accuracy=accuracy, headshot_rate=0.15,
        )

        with bld_output:
            bs = result.build_stats

            ui.label("Aggregated Stats").classes("text-amber-400 font-bold")
            stat_rows = []
            if bs.weapon_damage_pct:
                stat_rows.append({"stat": "Weapon Damage", "value": f"+{bs.weapon_damage_pct:.0%}"})
            if bs.fire_rate_pct:
                stat_rows.append({"stat": "Fire Rate", "value": f"+{bs.fire_rate_pct:.0%}"})
            if bs.ammo_flat:
                stat_rows.append({"stat": "Ammo (flat)", "value": f"+{bs.ammo_flat}"})
            if bs.ammo_pct:
                stat_rows.append({"stat": "Ammo (%)", "value": f"+{bs.ammo_pct:.0%}"})
            if bs.bonus_hp:
                stat_rows.append({"stat": "Bonus HP", "value": f"+{bs.bonus_hp:.0f}"})
            if bs.spirit_power:
                stat_rows.append({"stat": "Spirit Power", "value": f"+{bs.spirit_power:.0f}"})
            if bs.bullet_resist_pct:
                stat_rows.append({"stat": "Bullet Resist", "value": f"+{bs.bullet_resist_pct:.0%}"})
            if bs.spirit_resist_pct:
                stat_rows.append({"stat": "Spirit Resist", "value": f"+{bs.spirit_resist_pct:.0%}"})
            if bs.bullet_resist_shred:
                stat_rows.append({"stat": "Bullet Shred", "value": f"{bs.bullet_resist_shred:.0%}"})
            if bs.bullet_lifesteal:
                stat_rows.append({"stat": "Bullet Lifesteal", "value": f"{bs.bullet_lifesteal:.0%}"})
            if bs.bullet_shield:
                stat_rows.append({"stat": "Bullet Shield", "value": f"{bs.bullet_shield:.0f}"})
            if bs.cooldown_reduction:
                stat_rows.append({"stat": "CDR", "value": f"{bs.cooldown_reduction:.0%}"})
            stat_rows.append({"stat": "Total Cost", "value": f"{bs.total_cost}"})
            stat_rows.append({"stat": "Effective HP", "value": f"{result.effective_hp:.0f}"})

            columns = [
                {"name": "stat", "label": "Stat", "field": "stat", "align": "left"},
                {"name": "value", "label": "Value", "field": "value", "align": "left"},
            ]
            ui.table(columns=columns, rows=stat_rows, row_key="stat").classes("w-96").props("dense flat bordered")

            if result.bullet_result:
                br = result.bullet_result
                ui.label("DPS Output").classes("text-green-400 font-bold mt-4")
                dps_rows = [
                    {"metric": "Damage / Bullet", "value": _fv(br.damage_per_bullet)},
                    {"metric": "Bullets / Sec", "value": _fv(br.bullets_per_second)},
                    {"metric": "Raw DPS", "value": _fv(br.raw_dps)},
                    {"metric": "Final DPS", "value": _fv(br.final_dps)},
                    {"metric": "Magazine Size", "value": _fv(br.magazine_size, "d")},
                    {"metric": "Damage / Mag", "value": _fv(br.damage_per_magazine)},
                    {"metric": "Magdump Time", "value": _fv(br.magdump_time) + "s" if br.magdump_time > 0 else "-"},
                ]
                dps_columns = [
                    {"name": "metric", "label": "Metric", "field": "metric", "align": "left"},
                    {"name": "value", "label": "Value", "field": "value", "align": "left"},
                ]
                ui.table(columns=dps_columns, rows=dps_rows, row_key="metric").classes("w-96").props("dense flat bordered")

    cat_filter.on_value_change(refresh_item_list)
    bld_search.on_value_change(refresh_item_list)
    bld_hero.on_value_change(update_results)
    bld_boons.on_value_change(update_results)
    bld_acc.on_value_change(update_results)

    refresh_item_list()
    refresh_build_display()
    update_results()


# ── Tab: Build Optimizer ────────────────────────────────────────


def _build_optimizer_tab() -> None:
    with ui.row().classes("w-full gap-6"):
        # Left: inputs
        with ui.column().classes("w-80 gap-2"):
            ui.label("Hero").classes("text-amber-400 font-bold")
            opt_hero = ui.select(options=_hero_names, value=_hero_names[0] if _hero_names else "", label="Hero").classes("w-52")
            opt_boons = ui.number(label="Boons", value=0, min=0, max=50, step=1).classes("w-32")
            opt_budget = ui.number(label="Soul Budget", value=15000, min=500, max=100000, step=500).classes("w-32")
            opt_max_items = ui.number(label="Max Items", value=12, min=1, max=24, step=1).classes("w-32")

            ui.separator()
            opt_excl_cond = ui.checkbox("Exclude conditional items", value=True)

            ui.separator()
            ui.button("Optimize for Max DPS", on_click=lambda: on_optimize()).classes("w-full")

        # Right: results
        with ui.column().classes("flex-grow"):
            ui.label("Optimizer Results").classes("text-sky-400 font-bold")
            ui.separator()
            opt_output = ui.column().classes("w-full")

    def on_optimize():
        hero = _heroes.get(opt_hero.value)
        if not hero:
            return

        budget = int(opt_budget.value or 15000)
        boons = int(opt_boons.value or 0)
        max_items = int(opt_max_items.value or 12)
        excl_cond = opt_excl_cond.value

        build = BuildOptimizer.best_dps_items(
            _items, hero, budget=budget, boons=boons,
            max_items=max_items, exclude_conditional=excl_cond,
        )
        result = BuildEngine.evaluate_build(hero, build, boons=boons)

        opt_output.clear()
        with opt_output:
            ui.label(
                f"Budget: {budget} | Spent: {build.total_cost} | Items: {len(build.items)}"
            ).classes("text-gray-400")

            # Item list
            ui.label("Optimal Items").classes("text-amber-400 font-bold mt-2")
            item_rows = []
            for i, item in enumerate(build.items, 1):
                item_rows.append({
                    "num": i,
                    "item": item.name,
                    "category": item.category.title(),
                    "tier": f"T{item.tier}",
                    "cost": item.cost,
                })
            item_columns = [
                {"name": "num", "label": "#", "field": "num", "align": "left"},
                {"name": "item", "label": "Item", "field": "item", "align": "left"},
                {"name": "category", "label": "Category", "field": "category", "align": "left"},
                {"name": "tier", "label": "Tier", "field": "tier", "align": "left"},
                {"name": "cost", "label": "Cost", "field": "cost", "align": "left"},
            ]
            ui.table(columns=item_columns, rows=item_rows, row_key="num").classes("w-full max-w-2xl").props("dense flat bordered")

            # DPS results
            if result.bullet_result:
                br = result.bullet_result
                ui.label("DPS Output").classes("text-green-400 font-bold mt-4")
                dps_rows = [
                    {"metric": "Raw DPS", "value": _fv(br.raw_dps)},
                    {"metric": "Final DPS", "value": _fv(br.final_dps)},
                    {"metric": "Damage / Bullet", "value": _fv(br.damage_per_bullet)},
                    {"metric": "Bullets / Sec", "value": _fv(br.bullets_per_second)},
                    {"metric": "Magazine Size", "value": _fv(br.magazine_size, "d")},
                    {"metric": "Damage / Mag", "value": _fv(br.damage_per_magazine)},
                    {"metric": "Effective HP", "value": f"{result.effective_hp:.0f}"},
                ]
                dps_columns = [
                    {"name": "metric", "label": "Metric", "field": "metric", "align": "left"},
                    {"name": "value", "label": "Value", "field": "value", "align": "left"},
                ]
                ui.table(columns=dps_columns, rows=dps_rows, row_key="metric").classes("w-96").props("dense flat bordered")


# ── Main entry point ─────────────────────────────────────────────


def run_gui() -> None:
    """Launch the NiceGUI Deadlock simulator."""
    global _heroes, _hero_names, _items, _item_names

    _heroes = load_heroes()
    _hero_names = sorted(_heroes.keys())
    _items = load_items()
    _item_names = sorted(_items.keys())

    @ui.page("/")
    def index():
        ui.dark_mode(True)
        ui.label("DEADLOCK COMBAT SIMULATOR").classes("text-2xl font-bold text-amber-400")
        ui.label(f"{len(_heroes)} heroes, {len(_items)} items loaded").classes("text-gray-500")
        ui.separator()

        with ui.tabs().classes("w-full") as tabs:
            tab_hero = ui.tab("Hero Stats")
            tab_bullet = ui.tab("Bullet Damage")
            tab_spirit = ui.tab("Spirit Damage")
            tab_scaling = ui.tab("Scaling")
            tab_ttk = ui.tab("TTK")
            tab_cmp = ui.tab("Comparison")
            tab_rank = ui.tab("Rankings")
            tab_build = ui.tab("Build")
            tab_opt = ui.tab("Optimizer")

        with ui.tab_panels(tabs, value=tab_hero).classes("w-full"):
            with ui.tab_panel(tab_hero):
                _build_hero_stats_tab()
            with ui.tab_panel(tab_bullet):
                _build_bullet_tab()
            with ui.tab_panel(tab_spirit):
                _build_spirit_tab()
            with ui.tab_panel(tab_scaling):
                _build_scaling_tab()
            with ui.tab_panel(tab_ttk):
                _build_ttk_tab()
            with ui.tab_panel(tab_cmp):
                _build_comparison_tab()
            with ui.tab_panel(tab_rank):
                _build_rankings_tab()
            with ui.tab_panel(tab_build):
                _build_eval_tab()
            with ui.tab_panel(tab_opt):
                _build_optimizer_tab()

    ui.run(title="Deadlock Combat Simulator", port=8080, show=False)


if __name__ == "__main__":
    run_gui()
