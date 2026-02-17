"""NiceGUI web UI for the Deadlock combat simulator.

Browser-based UI with tabs for each simulator feature.
Item shop uses an icon grid with hover tooltips matching the in-game style.
All calculations delegated to deadlock_sim.engine.
"""

from __future__ import annotations

import math
from pathlib import Path

from nicegui import app, ui

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

# ── Image mapping ─────────────────────────────────────────────────

_ITEM_IMAGE: dict[str, str] = {
    "Active Reload": "fast_reload.png",
    "Alchemical Fire": "electrified_bullets.png",
    "Arcane Surge": "arcane_eater.png",
    "Arctic Blast": "ice_blast.png",
    "Armor Piercing Rounds": "armor_breaking_bullets.png",
    "Backstabber": "acolytes_glove.png",
    "Ballistic Enchantment": "advanced_weaponry.png",
    "Battle Vest": "bullet_armor.png",
    "Berserker": "berserker.png",
    "Blood Tribute": "bullet_damage_aura.png",
    "Boundless Spirit": "boundless_spirit.png",
    "Bullet Lifesteal": "health_stealing_bullets.png",
    "Bullet Resilience": "bullet_armor_plus.png",
    "Bullet Resist Shredder": "bullet_resist_shredder.png",
    "Burst Fire": "fire_rate_plus.png",
    "Capacitor": "tech_range.png",
    "Cheat Death": "last_stand.png",
    "Close Quarters": "close_range.png",
    "Cold Front": "ice_blast.png",
    "Colossus": "colossus.png",
    "Compress Cooldown": "advanced_recharge.png",
    "Counterspell": "magic_burst.png",
    "Crippling Headshot": "headshot_booster.png",
    "Crushing Fists": "boxing_glove.png",
    "Cultist Sacrifice": "reaper_rounds.png",
    "Cursed Relic": "quantum_chimaera.png",
    "Debuff Reducer": "debuff_reducer.png",
    "Decay": "rupture.png",
    "Disarming Hex": "disarm.png",
    "Dispel Magic": "tech_purge.png",
    "Divine Barrier": "deployable_bullet_shield.png",
    "Diviner's Kevlar": "arcane_medallion.png",
    "Duration Extender": "duration_extender.png",
    "Echo Shard": "echo_shard.png",
    "Enchanter's Emblem": "pristine_emblem.png",
    "Enduring Speed": "zipline_speed.png",
    "Escalating Exposure": "escalating_exposure.png",
    "Escalating Resilience": "bullet_armor_pulse.png",
    "Ethereal Shift": "shifting_shroud.png",
    "Express Shot": "fire_rate_plus.png",
    "Extended Magazine": "titanic_magazine.png",
    "Extra Charge": "extra_charge.png",
    "Extra Health": "health.png",
    "Extra Regen": "health_regen.png",
    "Extra Spirit": "soaring_spirit.png",
    "Extra Stamina": "superior_stamina.png",
    "Fleetfoot": "fleetfoot_boots.png",
    "Focus Lens": "enhanced_precision.png",
    "Fortitude": "health_tank.png",
    "Frenzy": "fervor.png",
    "Fury Trance": "soaring_spirit.png",
    "Glass Cannon": "glass_cannon.png",
    "Greater Expansion": "area_immobilize.png",
    "Guardian Ward": "bullet_armor_reduction_aura.png",
    "Headhunter": "headhunter.png",
    "Headshot Booster": "headshot_booster.png",
    "Healbane": "healbane.png",
    "Healing Booster": "healing_booster.png",
    "Healing Nova": "health_nova.png",
    "Healing Rite": "healing_booster.png",
    "Healing Tempo": "health_regen_aura.png",
    "Heroic Aura": "fire_rate_aura.png",
    "High-Velocity Rounds": "high_velocity_mag.png",
    "Hollow Point": "hollow_point.png",
    "Hunter's Aura": "bullet_armor_reduction_aura.png",
    "Improved Spirit": "arcane_persistance.png",
    "Infuser": "infuser.png",
    "Inhibitor": "inhibitor.png",
    "Intensifying Magazine": "clip_size.png",
    "Juggernaut": "endurance.png",
    "Kinetic Dash": "kinetic_sash.png",
    "Knockdown": "knockdown.png",
    "Leech": "leech.png",
    "Lifestrike": "lifestrike_gauntlets.png",
    "Lightning Scroll": "emp_wave.png",
    "Long Range": "long_range.png",
    "Lucky Shot": "fire_rate_plus_plus.png",
    "Magic Carpet": "soaring_spirit.png",
    "Majestic Leap": "controlled_fall.png",
    "Melee Charge": "melee_charge.png",
    "Melee Lifesteal": "health_stealing_tech.png",
    "Mercurial Magnum": "ammo_scavenger.png",
    "Metal Skin": "metal_skin.png",
    "Monster Rounds": "detention_rounds.png",
    "Mystic Burst": "magic_burst.png",
    "Mystic Expansion": "area_immobilize.png",
    "Mystic Regeneration": "health_regen.png",
    "Mystic Reverb": "magic_reverb.png",
    "Mystic Shot": "magic_shock.png",
    "Mystic Slow": "slowing_hex.png",
    "Mystic Vulnerability": "tech_vulnerability.png",
    "Opening Rounds": "detention_rounds.png",
    "Phantom Strike": "phantom_strike.png",
    "Plated Armor": "base_armor.png",
    "Point Blank": "point_blank.png",
    "Quicksilver Reload": "quick_reload.png",
    "Radiant Regeneration": "medic_bullets.png",
    "Rapid Recharge": "rapid_recharge.png",
    "Rapid Rounds": "rapid_rounds.png",
    "Reactive Barrier": "bullet_shield.png",
    "Rebuttal": "melee_deflector.png",
    "Recharging Rush": "adrenaline_rush.png",
    "Refresher": "refresher_module.png",
    "Rescue Beam": "medic_beam.png",
    "Restorative Locket": "restorative_locket.png",
    "Restorative Shot": "medic_bullets.png",
    "Return Fire": "return_fire.png",
    "Ricochet": "ricochet.png",
    "Rusted Barrel": "ammo_scavenger.png",
    "Scourge": "spiritual_dominion.png",
    "Shadow Weave": "cloaking_device.png",
    "Sharpshooter": "longshot.png",
    "Silence Wave": "emp_wave.png",
    "Silencer": "cloaking_device.png",
    "Siphon Bullets": "siphon_bullets.png",
    "Slowing Bullets": "slowing_bullets.png",
    "Slowing Hex": "slowing_tech.png",
    "Spellbreaker": "tech_purge.png",
    "Spellslinger": "advanced_weaponry.png",
    "Spirit Burn": "thermal_detonator.png",
    "Spirit Lifesteal": "health_stealing_bullets.png",
    "Spirit Rend": "piercing_bullets.png",
    "Spirit Resilience": "tech_armor_aura.png",
    "Spirit Sap": "spiritual_flow.png",
    "Spirit Shielding": "tech_shield_pulse.png",
    "Spirit Shredder Bullets": "serrated_bullets.png",
    "Spirit Snatch": "spiritual_dominion.png",
    "Spirit Strike": "magic_shock.png",
    "Spiritual Overflow": "magic_overflow.png",
    "Split Shot": "banshee_slugs.png",
    "Sprint Boots": "springy_boots.png",
    "Stamina Mastery": "improved_stamina.png",
    "Superior Cooldown": "advanced_recharge.png",
    "Superior Duration": "duration_extender.png",
    "Suppressor": "tech_damage.png",
    "Surge of Power": "soaring_spirit.png",
    "Swift Striker": "fire_rate.png",
    "Tankbuster": "rupture.png",
    "Tesla Bullets": "emp_bullets.png",
    "Titanic Magazine": "titanic_magazine.png",
    "Torment Pulse": "torment_aura.png",
    "Toxic Bullets": "toxic_bullets.png",
    "Transcendent Cooldown": "advanced_recharge.png",
    "Trophy Collector": "rebirth.png",
    "Unstoppable": "unstoppable.png",
    "Vampiric Burst": "vampiric_burst.png",
    "Veil Walker": "veil_walker.png",
    "Vortex Web": "force_blast.png",
    "Warp Stone": "warp_stone.png",
    "Weakening Headshot": "headshot_booster.png",
    "Weapon Shielding": "tech_shield_pulse.png",
    "Weighted Shots": "fire_rate.png",
    "Witchmail": "tech_armor.png",
}

# Category colors matching in-game (orange weapon, green vitality, purple spirit)
_CAT_COLORS = {
    "weapon": {"bg": "#3d2a12", "border": "#d97e1f", "text": "#f5a623", "label": "Weapon"},
    "vitality": {"bg": "#1a3320", "border": "#4caf50", "text": "#6dd56e", "label": "Vitality"},
    "spirit": {"bg": "#2a1a3d", "border": "#9c5dce", "text": "#c084fc", "label": "Spirit"},
}

_TIER_COSTS = {1: 500, 2: 1250, 3: 3000, 4: 6200}

# Sort criteria available for items
_SORT_OPTIONS = {
    "Cost": lambda item: item.cost,
    "Name": lambda item: item.name,
    "Weapon Damage %": lambda item: -item.weapon_damage_pct,
    "Fire Rate %": lambda item: -item.fire_rate_pct,
    "Bonus HP": lambda item: -item.bonus_hp,
    "Bullet Resist %": lambda item: -item.bullet_resist_pct,
    "Spirit Resist %": lambda item: -item.spirit_resist_pct,
    "Spirit Power": lambda item: -item.spirit_power,
    "Bullet Lifesteal %": lambda item: -item.bullet_lifesteal,
    "HP Regen": lambda item: -item.hp_regen,
    "Bullet Shield": lambda item: -item.bullet_shield,
    "Bullet Shred %": lambda item: -item.bullet_resist_shred,
    "Cooldown Reduction %": lambda item: -item.cooldown_reduction,
}


# ── Helpers ───────────────────────────────────────────────────────


def _fv(v: float, fmt: str = ".2f", zero_as_na: bool = True) -> str:
    """Format a numeric value for display, showing '-' for missing/inf/nan."""
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
        return "-"
    if zero_as_na and v == 0:
        return "-"
    return f"{v:{fmt}}"


def _item_image_url(item: Item) -> str:
    """Return the static URL for an item's icon."""
    fname = _ITEM_IMAGE.get(item.name, "")
    if fname:
        return f"/static/items/{fname}"
    return "/static/ui/all_stats.png"


def _item_stat_lines(item: Item) -> list[str]:
    """Build human-readable stat lines for an item tooltip."""
    lines: list[str] = []
    if item.weapon_damage_pct:
        lines.append(f"+{item.weapon_damage_pct:.0%} Weapon Damage")
    if item.fire_rate_pct:
        lines.append(f"+{item.fire_rate_pct:.0%} Fire Rate")
    if item.ammo_flat:
        lines.append(f"+{item.ammo_flat} Ammo")
    if item.ammo_pct:
        lines.append(f"+{item.ammo_pct:.0%} Ammo")
    if item.bonus_hp:
        lines.append(f"+{item.bonus_hp:.0f} HP")
    if item.hp_regen:
        lines.append(f"+{item.hp_regen:.1f} HP Regen")
    if item.spirit_power:
        lines.append(f"+{item.spirit_power:.0f} Spirit Power")
    if item.bullet_resist_pct:
        lines.append(f"+{item.bullet_resist_pct:.0%} Bullet Resist")
    if item.spirit_resist_pct:
        lines.append(f"+{item.spirit_resist_pct:.0%} Spirit Resist")
    if item.bullet_lifesteal:
        lines.append(f"+{item.bullet_lifesteal:.0%} Bullet Lifesteal")
    if item.spirit_lifesteal:
        lines.append(f"+{item.spirit_lifesteal:.0%} Spirit Lifesteal")
    if item.bullet_shield:
        lines.append(f"+{item.bullet_shield:.0f} Bullet Shield")
    if item.spirit_shield:
        lines.append(f"+{item.spirit_shield:.0f} Spirit Shield")
    if item.headshot_bonus:
        lines.append(f"+{item.headshot_bonus:.0f} Headshot Damage")
    if item.bullet_resist_shred:
        lines.append(f"{item.bullet_resist_shred:.0%} Bullet Resist Shred")
    if item.spirit_resist_shred:
        lines.append(f"{item.spirit_resist_shred:.0%} Spirit Resist Shred")
    if item.cooldown_reduction:
        lines.append(f"{item.cooldown_reduction:.0%} CDR")
    if item.spirit_amp_pct:
        lines.append(f"+{item.spirit_amp_pct:.0%} Spirit Amp")
    if item.move_speed:
        lines.append(f"+{item.move_speed:.1f} Move Speed")
    if item.sprint_speed:
        lines.append(f"+{item.sprint_speed:.1f} Sprint Speed")
    if item.condition:
        lines.append(f"Condition: {item.condition}")
    return lines


# ── Custom CSS ────────────────────────────────────────────────────

_CUSTOM_CSS = """
.item-icon-btn {
    position: relative;
    width: 64px; height: 64px;
    border-radius: 6px;
    cursor: pointer;
    transition: transform 0.1s, box-shadow 0.1s;
    padding: 0; margin: 2px;
    display: flex; align-items: center; justify-content: center;
    overflow: visible;
}
.item-icon-btn:hover {
    transform: scale(1.15);
    box-shadow: 0 0 12px rgba(255,255,255,0.3);
    z-index: 100;
}
.item-icon-btn img {
    width: 48px; height: 48px;
    object-fit: contain;
    filter: brightness(1.1);
}
.item-tooltip {
    display: none;
    position: absolute;
    bottom: 72px; left: 50%;
    transform: translateX(-50%);
    min-width: 220px; max-width: 300px;
    padding: 10px 14px;
    border-radius: 8px;
    z-index: 9999;
    pointer-events: none;
    white-space: nowrap;
}
.item-icon-btn:hover .item-tooltip {
    display: block;
}
.tooltip-name {
    font-weight: bold; font-size: 14px;
    margin-bottom: 4px;
}
.tooltip-cost {
    font-size: 12px; color: #e8c252;
    margin-bottom: 6px;
}
.tooltip-stat {
    font-size: 12px; color: #b0e8b0;
    line-height: 1.5;
}
.tooltip-condition {
    font-size: 11px; color: #ffb347;
    font-style: italic; margin-top: 4px;
}
.tier-header {
    font-size: 14px; font-weight: bold;
    padding: 6px 12px;
    border-radius: 4px;
    margin: 8px 0 4px 0;
}
.shop-grid {
    display: flex; flex-wrap: wrap;
    gap: 2px; padding: 4px;
    align-items: flex-start;
}
.build-item-chip {
    display: flex; align-items: center;
    gap: 6px; padding: 4px 8px;
    border-radius: 6px;
    margin: 2px;
}
.build-item-chip img {
    width: 28px; height: 28px;
    object-fit: contain;
}
.cat-tab { padding: 8px 20px; font-weight: bold; border-radius: 6px 6px 0 0; cursor: pointer; }
.cat-tab-active { border-bottom: 3px solid; }
"""


def _render_item_icon(item: Item, on_click_fn) -> None:
    """Render a single item as an icon button with hover tooltip."""
    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
    stat_lines = _item_stat_lines(item)

    stat_html = ""
    for line in stat_lines:
        if line.startswith("Condition:"):
            stat_html += f'<div class="tooltip-condition">{line}</div>'
        else:
            stat_html += f'<div class="tooltip-stat">{line}</div>'

    tooltip_html = f"""
        <div class="item-tooltip" style="background: {colors['bg']}; border: 1px solid {colors['border']};">
            <div class="tooltip-name" style="color: {colors['text']};">{item.name}</div>
            <div class="tooltip-cost">T{item.tier} - {item.cost} Souls</div>
            {stat_html}
        </div>
    """

    with ui.element("div").classes("item-icon-btn").style(
        f"background: {colors['bg']}; border: 2px solid {colors['border']};"
    ).on("click", lambda _, it=item: on_click_fn(it)):
        ui.image(_item_image_url(item)).style("width: 48px; height: 48px; object-fit: contain;")
        ui.html(tooltip_html)


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
        growth_label.text = f"Growth (0 \u2192 {max_b} boons):  DPS {dps_g}  |  HP {hp_g}  |  Aggregate {agg_g}"

    sc_hero.on_value_change(update)
    sc_max.on_value_change(update)
    update()


# ── Tab: TTK ─────────────────────────────────────────────────────


def _build_ttk_tab() -> None:
    with ui.row().classes("w-full gap-6"):
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


# ── Tab: Build Evaluator (shop-style) ───────────────────────────


def _build_eval_tab() -> None:
    # ── Top bar: hero selection + build config
    with ui.row().classes("w-full items-end gap-4"):
        bld_hero = ui.select(options=_hero_names, value=_hero_names[0] if _hero_names else "", label="Hero").classes("w-48")
        bld_boons = ui.number(label="Boons", value=0, min=0, max=50, step=1).classes("w-28")
        bld_acc = ui.number(label="Accuracy %", value=50, min=0, max=100).classes("w-28")

    ui.separator()

    with ui.row().classes("w-full gap-4"):
        # ── LEFT: Item Shop ──
        with ui.column().classes("flex-grow"):
            # Category tabs + filter controls
            with ui.row().classes("w-full items-center gap-3 flex-wrap"):
                cat_filter = ui.select(
                    options=["All", "Weapon", "Vitality", "Spirit"],
                    value="All", label="Category",
                ).classes("w-32")
                tier_filter = ui.select(
                    options=["All Tiers", "T1", "T2", "T3", "T4"],
                    value="All Tiers", label="Tier",
                ).classes("w-28")
                sort_select = ui.select(
                    options=list(_SORT_OPTIONS.keys()),
                    value="Cost", label="Sort By",
                ).classes("w-40")
                bld_search = ui.input(label="Search", placeholder="Filter items...").classes("w-40")

            # Item icon grid area
            shop_container = ui.scroll_area().classes("w-full border rounded").style(
                "height: 420px; background: #1a1a2e;"
            )

        # ── RIGHT: Build + Results ──
        with ui.column().classes("w-96"):
            ui.label("Current Build").classes("text-lg font-bold text-green-400")
            build_display = ui.scroll_area().classes("w-full border rounded").style(
                "height: 200px; background: #1a1a2e;"
            )
            with ui.row().classes("w-full gap-2"):
                ui.button("Clear Build", on_click=lambda: clear_build()).classes("flex-grow")

            ui.separator()
            ui.label("Build Results").classes("text-lg font-bold text-sky-400")
            bld_output = ui.scroll_area().classes("w-full").style(
                "height: 300px;"
            )

    def refresh_shop(_=None):
        cat = (cat_filter.value or "All").lower()
        tier_str = tier_filter.value or "All Tiers"
        search = (bld_search.value or "").lower().strip()
        sort_key_name = sort_select.value or "Cost"
        sort_fn = _SORT_OPTIONS.get(sort_key_name, _SORT_OPTIONS["Cost"])

        filtered = []
        for item in _items.values():
            if cat != "all" and item.category != cat:
                continue
            if tier_str != "All Tiers" and f"T{item.tier}" != tier_str:
                continue
            if search and search not in item.name.lower():
                continue
            filtered.append(item)

        filtered.sort(key=sort_fn)

        shop_container.clear()
        with shop_container:
            if sort_key_name == "Cost":
                # Group by tier when sorting by cost (like in-game shop)
                for tier in [1, 2, 3, 4]:
                    tier_items = [i for i in filtered if i.tier == tier]
                    if not tier_items:
                        continue

                    # Group within tier by category
                    for cat_key in ["weapon", "vitality", "spirit"]:
                        cat_items = [i for i in tier_items if i.category == cat_key]
                        if not cat_items:
                            continue
                        colors = _CAT_COLORS[cat_key]
                        with ui.element("div").style(
                            f"background: {colors['bg']}; border-left: 3px solid {colors['border']}; "
                            f"margin: 4px 0; padding: 4px 8px; border-radius: 4px;"
                        ):
                            ui.label(
                                f"{colors['label']} T{tier} - {tier_items[0].cost} Souls"
                            ).style(f"color: {colors['text']}; font-size: 13px; font-weight: bold;")
                            with ui.element("div").classes("shop-grid"):
                                for item in cat_items:
                                    _render_item_icon(item, add_item)
            else:
                # Flat grid for non-cost sorting
                with ui.element("div").classes("shop-grid"):
                    for item in filtered:
                        _render_item_icon(item, add_item)

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
            ui.label(f"{len(_build_items)} items | {total_cost} Souls").classes("text-gray-400 text-sm")
            with ui.element("div").style("display: flex; flex-wrap: wrap; gap: 2px;"):
                for i, item in enumerate(_build_items):
                    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
                    with ui.element("div").classes("build-item-chip").style(
                        f"background: {colors['bg']}; border: 1px solid {colors['border']}; cursor: pointer;"
                    ).on("click", lambda _, idx=i: remove_item(idx)):
                        ui.image(_item_image_url(item)).style("width: 28px; height: 28px; object-fit: contain;")
                        ui.label(item.name).style(f"color: {colors['text']}; font-size: 12px;")
                        ui.label("x").style("color: #ff6b6b; font-size: 11px; margin-left: 4px;")

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
            ui.table(columns=columns, rows=stat_rows, row_key="stat").classes("w-full").props("dense flat bordered")

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
                ui.table(columns=dps_columns, rows=dps_rows, row_key="metric").classes("w-full").props("dense flat bordered")

    cat_filter.on_value_change(refresh_shop)
    tier_filter.on_value_change(refresh_shop)
    sort_select.on_value_change(refresh_shop)
    bld_search.on_value_change(refresh_shop)
    bld_hero.on_value_change(update_results)
    bld_boons.on_value_change(update_results)
    bld_acc.on_value_change(update_results)

    refresh_shop()
    refresh_build_display()
    update_results()


# ── Tab: Build Optimizer ────────────────────────────────────────


def _build_optimizer_tab() -> None:
    with ui.row().classes("w-full gap-6"):
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

            # Show optimal items with icons
            ui.label("Optimal Items").classes("text-amber-400 font-bold mt-2")
            with ui.element("div").style("display: flex; flex-wrap: wrap; gap: 4px;"):
                for item in build.items:
                    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
                    with ui.element("div").classes("build-item-chip").style(
                        f"background: {colors['bg']}; border: 1px solid {colors['border']};"
                    ):
                        ui.image(_item_image_url(item)).style("width: 28px; height: 28px; object-fit: contain;")
                        ui.label(f"{item.name} ({item.cost})").style(f"color: {colors['text']}; font-size: 12px;")

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

    # Serve item images and UI icons as static files
    data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "images"
    app.add_static_files("/static/items", str(data_dir / "items"))
    app.add_static_files("/static/ui", str(data_dir / "ui"))

    @ui.page("/")
    def index():
        ui.dark_mode(True)
        ui.add_css(_CUSTOM_CSS)

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
