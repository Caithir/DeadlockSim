"""NiceGUI web UI for the Deadlock combat simulator.

Browser-based UI with tabs for each simulator feature.
Item shop uses an icon grid with hover tooltips matching the in-game style.
All calculations delegated to deadlock_sim.engine.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

from nicegui import app, ui

from ..api_client import ensure_data_available, refresh_all_data
from ..data import load_heroes, load_items
from ..engine.builds import BuildEngine, BuildOptimizer
from ..engine.comparison import ComparisonEngine
from ..engine.damage import DamageCalculator
from ..engine.scaling import ScalingCalculator
from ..engine.ttk import TTKCalculator
from ..models import Build, CombatConfig, HeroStats, Item

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

# Color palette for multi-hero scaling charts
_CHART_COLORS = [
    "#4080ff", "#ff6040", "#40c060", "#c0c040",
    "#a040c0", "#40c0c0", "#ff80a0", "#80ffa0",
]


# ── Helpers ───────────────────────────────────────────────────────


def _fv(v: float, fmt: str = ".2f", zero_as_na: bool = True) -> str:
    """Format a numeric value for display, showing '-' for missing/inf/nan."""
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
        return "-"
    if zero_as_na and v == 0:
        return "-"
    return f"{v:{fmt}}"


def _item_image_url(item: Item) -> str:
    """Return the URL for an item's icon, preferring API URL over local files."""
    if item.image_url:
        return item.image_url
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
.hero-chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 20px;
    background: #1a2a3d; border: 1px solid #4080c0;
    margin: 2px;
}
"""


def _render_item_icon(item: Item, on_click_fn) -> None:
    """Render a single item as an icon button with hover tooltip."""
    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
    stat_lines = _item_stat_lines(item)

    stat_html = "".join(
        f'<div class="tooltip-condition">{line}</div>'
        if line.startswith("Condition:")
        else f'<div class="tooltip-stat">{line}</div>'
        for line in stat_lines
    )
    tooltip_inner = (
        f'<div style="min-width:200px;max-width:280px;">'
        f'<div class="tooltip-name" style="color:{colors["text"]};">{item.name}</div>'
        f'<div class="tooltip-cost">T{item.tier} — {item.cost} Souls</div>'
        f'{stat_html}'
        f'</div>'
    )

    with ui.element("div").classes("item-icon-btn").style(
        f"background: {colors['bg']}; border: 2px solid {colors['border']};"
    ).on("click", lambda _, it=item: on_click_fn(it)):
        ui.image(_item_image_url(item)).style("width: 48px; height: 48px; object-fit: contain;")
        with ui.tooltip().style(
            f"background:{colors['bg']}; border:1px solid {colors['border']}; "
            "padding:10px 14px; border-radius:8px; font-size:13px;"
        ):
            ui.html(tooltip_inner)


# ── Tab: Heroes (Abilities + Images + Upgrades) ───────────────────


def _build_heroes_tab() -> None:
    with ui.row().classes("items-end gap-4 flex-wrap"):
        heroes_select = ui.select(
            options=_hero_names,
            value=_hero_names[0] if _hero_names else "",
            label="Hero",
        ).classes("w-52")
        spirit_input = ui.number(label="Spirit Power", value=0, min=0, step=1).classes("w-32")
        cdr_input = ui.number(label="CDR %", value=0, min=0, max=100, step=1).classes("w-32")

    ui.separator()
    content_area = ui.column().classes("w-full gap-4")

    def update(_=None):
        hero = _heroes.get(heroes_select.value)
        content_area.clear()
        if not hero:
            return

        current_spirit = int(spirit_input.value or 0)
        cdr = (cdr_input.value or 0) / 100.0

        with content_area:
            # Hero image + info row
            with ui.row().classes("gap-6 items-start flex-wrap"):
                img_url = hero.hero_card_url or hero.icon_url
                if img_url:
                    ui.image(img_url).style(
                        "max-height: 200px; max-width: 150px; object-fit: contain; border-radius: 8px;"
                    )

                with ui.column().classes("gap-1"):
                    ui.label(hero.name).classes("text-2xl font-bold text-amber-400")
                    if hero.hero_labs:
                        ui.label("[Hero Labs - stats may be incomplete]").classes("text-red-400 text-sm")
                    if hero.role:
                        ui.label(f"Role: {hero.role}").classes("text-gray-300")
                    if hero.playstyle:
                        ui.label(f"Playstyle: {hero.playstyle}").classes("text-gray-400 text-sm")

                    # Spirit DPS summary
                    total_spirit_dps = DamageCalculator.hero_total_spirit_dps(
                        hero, current_spirit=current_spirit, cooldown_reduction=cdr
                    )
                    if total_spirit_dps > 0:
                        ui.label(
                            f"Total Spirit DPS: {total_spirit_dps:.1f}"
                        ).classes("text-purple-400 font-bold mt-2")
                    elif hero.abilities:
                        ui.label("No damaging abilities found").classes("text-gray-500 text-sm mt-2")

            # Abilities section
            if hero.abilities:
                ui.separator()
                ui.label("Abilities").classes("text-lg font-bold text-sky-400")

                for ability in hero.abilities:
                    if not ability.name:
                        continue

                    with ui.card().classes("w-full").style(
                        "background: #161625; border: 1px solid #2a2a4a;"
                    ):
                        with ui.row().classes("items-start gap-4 w-full"):
                            # Ability icon
                            if ability.image_url:
                                ui.image(ability.image_url).style(
                                    "width: 56px; height: 56px; object-fit: contain; "
                                    "flex-shrink: 0; border-radius: 6px;"
                                )

                            with ui.column().classes("flex-grow gap-1"):
                                # Name + type badge
                                with ui.row().classes("items-center gap-2 flex-wrap"):
                                    ui.label(ability.name).classes("font-bold text-amber-300")
                                    if ability.ability_type:
                                        atype = ability.ability_type.replace("_", " ").title()
                                        badge_color = (
                                            "purple" if "spirit" in ability.ability_type.lower()
                                            else "orange" if "weapon" in ability.ability_type.lower()
                                            else "blue"
                                        )
                                        ui.badge(atype).props(f"color={badge_color}")

                                # Description (API returns HTML markup)
                                if ability.description:
                                    ui.html(ability.description).classes(
                                        "text-gray-300 text-sm"
                                    )

                                # Key stats
                                stat_parts = []
                                if ability.base_damage:
                                    stat_parts.append(f"Damage: {ability.base_damage:.0f}")
                                if ability.spirit_scaling:
                                    stat_parts.append(f"Spirit Scaling: {ability.spirit_scaling:.2f}x")
                                if ability.cooldown:
                                    stat_parts.append(f"CD: {ability.cooldown:.1f}s")
                                if ability.duration:
                                    stat_parts.append(f"Duration: {ability.duration:.1f}s")

                                if stat_parts:
                                    ui.label(" | ".join(stat_parts)).classes(
                                        "text-purple-300 text-sm font-mono"
                                    )

                                # Upgrade hover tooltip
                                if ability.upgrades:
                                    upgrade_html = "".join(
                                        f'<div style="margin-bottom:6px;">'
                                        f'<span style="color:#c084fc;font-weight:bold;">T{u.tier}:</span> '
                                        f'<span style="color:#e2d4f0;font-size:13px;">{u.description}</span>'
                                        f'</div>'
                                        for u in ability.upgrades
                                    )
                                    with ui.element("span").style("cursor:help; display:inline-block; margin-top:4px;"):
                                        ui.label("Upgrades (hover for T1/T2/T3)").classes(
                                            "text-purple-400 text-xs underline"
                                        )
                                        with ui.tooltip().style(
                                            "background:#2a1a3d; border:1px solid #9c5dce; "
                                            "padding:10px 14px; border-radius:8px; max-width:420px;"
                                        ):
                                            ui.html(upgrade_html)

    heroes_select.on_value_change(update)
    spirit_input.on_value_change(update)
    cdr_input.on_value_change(update)
    update()


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


# ── Tab: Scaling (multi-hero) ──────────────────────────────────────


def _build_scaling_tab() -> None:
    selected_heroes: list[str] = [_hero_names[0]] if _hero_names else []

    with ui.row().classes("gap-4 items-end flex-wrap"):
        sc_hero_pick = ui.select(
            options=_hero_names,
            value=_hero_names[0] if _hero_names else "",
            label="Add Hero",
        ).classes("w-52")
        ui.button("Add Hero", icon="add", on_click=lambda: add_hero()).classes("mt-auto")
        sc_max = ui.number(label="Max Boons", value=35, min=1, max=50, step=1).classes("w-32")

    chips_row = ui.row().classes("flex-wrap gap-1 mt-1")

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
    comparison_area = ui.column().classes("w-full")

    def render_chips():
        chips_row.clear()
        with chips_row:
            for name in selected_heroes:
                color = _CHART_COLORS[selected_heroes.index(name) % len(_CHART_COLORS)]
                with ui.element("div").classes("hero-chip").style(
                    f"border-color: {color};"
                ):
                    ui.label(name).style(f"color: {color}; font-size: 13px;")
                    ui.button(
                        "×", on_click=lambda _, n=name: remove_hero(n)
                    ).props("flat dense").style(
                        "color: #ff6b6b; font-size: 14px; min-width: 20px; padding: 0; height: 20px;"
                    )

    def add_hero():
        name = sc_hero_pick.value
        if name and name not in selected_heroes:
            selected_heroes.append(name)
            render_chips()
            update()

    def remove_hero(name: str):
        if name in selected_heroes:
            selected_heroes.remove(name)
            render_chips()
            update()

    def update(_=None):
        max_b = int(sc_max.value or 35)
        dps_series = []
        hp_series = []

        for i, name in enumerate(selected_heroes):
            hero = _heroes.get(name)
            if not hero:
                continue
            color = _CHART_COLORS[i % len(_CHART_COLORS)]
            curve = ScalingCalculator.scaling_curve(hero, max_b)
            boons = [s.boon_level for s in curve]
            dps_vals = [s.dps for s in curve]
            hp_vals = [s.hp for s in curve]

            dps_series.append({
                "name": name, "type": "line",
                "data": list(zip(boons, dps_vals)),
                "smooth": True,
                "itemStyle": {"color": color},
                "lineStyle": {"color": color},
            })
            hp_series.append({
                "name": name, "type": "line",
                "data": list(zip(boons, hp_vals)),
                "smooth": True,
                "itemStyle": {"color": color},
                "lineStyle": {"color": color},
            })

        dps_chart.options["series"] = dps_series
        dps_chart.update()
        hp_chart.options["series"] = hp_series
        hp_chart.update()

        # Comparison table (only when multiple heroes)
        comparison_area.clear()
        if len(selected_heroes) >= 1:
            with comparison_area:
                ui.label(f"Stats at Boon {max_b}").classes("text-sky-400 font-bold")
                rows = []
                for name in selected_heroes:
                    hero = _heroes.get(name)
                    if not hero:
                        continue
                    curve = ScalingCalculator.scaling_curve(hero, max_b)
                    last = curve[-1] if curve else None
                    growth = ScalingCalculator.growth_percentage(hero, max_b)
                    if last:
                        rows.append({
                            "hero": name,
                            "dps": _fv(last.dps),
                            "hp": f"{last.hp:.0f}",
                            "dpm": _fv(last.dpm),
                            "dps_growth": f"{growth['dps_growth']:.1%}" if growth["dps_growth"] else "-",
                            "hp_growth": f"{growth['hp_growth']:.1%}" if growth["hp_growth"] else "-",
                        })

                columns = [
                    {"name": "hero", "label": "Hero", "field": "hero", "align": "left"},
                    {"name": "dps", "label": "DPS", "field": "dps", "align": "left"},
                    {"name": "hp", "label": "HP", "field": "hp", "align": "left"},
                    {"name": "dpm", "label": "DPM", "field": "dpm", "align": "left"},
                    {"name": "dps_growth", "label": "DPS Growth", "field": "dps_growth", "align": "left"},
                    {"name": "hp_growth", "label": "HP Growth", "field": "hp_growth", "align": "left"},
                ]
                ui.table(
                    columns=columns, rows=rows, row_key="hero"
                ).classes("w-full max-w-3xl").props("dense flat bordered")

    render_chips()
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
                ui.label("Bullet DPS").classes("text-green-400 font-bold mt-4")
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

            # Spirit DPS and combined DPS
            spirit_dps = DamageCalculator.hero_total_spirit_dps(
                hero,
                current_spirit=int(bs.spirit_power),
                cooldown_reduction=bs.cooldown_reduction,
                spirit_amp=bs.spirit_amp_pct,
            )
            bullet_dps = result.bullet_result.final_dps if result.bullet_result else 0.0
            combined_dps = bullet_dps + spirit_dps

            if spirit_dps > 0 or combined_dps > 0:
                ui.label("Spirit & Combined DPS").classes("text-purple-400 font-bold mt-4")
                combined_rows = [
                    {"metric": "Spirit DPS", "value": _fv(spirit_dps)},
                    {"metric": "Bullet DPS", "value": _fv(bullet_dps)},
                    {"metric": "Combined DPS", "value": _fv(combined_dps)},
                ]
                combined_cols = [
                    {"name": "metric", "label": "Metric", "field": "metric", "align": "left"},
                    {"name": "value", "label": "Value", "field": "value", "align": "left"},
                ]
                ui.table(
                    columns=combined_cols, rows=combined_rows, row_key="metric"
                ).classes("w-full").props("dense flat bordered")

    cat_filter.on_value_change(refresh_shop)
    tier_filter.on_value_change(refresh_shop)
    sort_select.on_value_change(refresh_shop)
    bld_search.on_value_change(refresh_shop)
    bld_hero.on_value_change(update_results)
    bld_boons.on_value_change(update_results)
    bld_acc.on_value_change(update_results)

    refresh_build_display()
    update_results()

    # Return refresh_shop so the caller can trigger it lazily on first tab activation
    return refresh_shop


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

    ensure_data_available()
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

        # Header row with title + refresh button
        with ui.row().classes("items-center gap-4 w-full"):
            ui.label("DEADLOCK COMBAT SIMULATOR").classes("text-2xl font-bold text-amber-400")

            async def do_refresh():
                notif = ui.notification(
                    "Refreshing API data...", spinner=True, timeout=None, type="ongoing"
                )
                try:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, refresh_all_data)
                    # Reload global data
                    global _heroes, _hero_names, _items, _item_names
                    _heroes = load_heroes()
                    _hero_names = sorted(_heroes.keys())
                    _items = load_items()
                    _item_names = sorted(_items.keys())
                    notif.message = (
                        f"Refreshed: {result.get('heroes', 0)} heroes, "
                        f"{result.get('items', 0)} items"
                    )
                    notif.type = "positive"
                    notif.spinner = False
                    await asyncio.sleep(3)
                except Exception as exc:
                    notif.message = f"Refresh failed: {exc}"
                    notif.type = "negative"
                    notif.spinner = False
                    await asyncio.sleep(4)
                finally:
                    notif.dismiss()

            ui.button("Refresh Data", icon="sync", on_click=do_refresh).props("flat").classes("text-sky-400")

        ui.label(f"{len(_heroes)} heroes, {len(_items)} items loaded").classes("text-gray-500")
        ui.separator()

        with ui.tabs().classes("w-full") as tabs:
            tab_heroes = ui.tab("Heroes")
            tab_scaling = ui.tab("Scaling")
            tab_ttk = ui.tab("TTK")
            tab_cmp = ui.tab("Comparison")
            tab_rank = ui.tab("Rankings")
            tab_build = ui.tab("Build")
            tab_opt = ui.tab("Optimizer")
            tab_hero = ui.tab("Hero Stats")

        with ui.tab_panels(tabs, value=tab_heroes).classes("w-full") as panels:
            with ui.tab_panel(tab_heroes):
                _build_heroes_tab()
            with ui.tab_panel(tab_scaling):
                _build_scaling_tab()
            with ui.tab_panel(tab_ttk):
                _build_ttk_tab()
            with ui.tab_panel(tab_cmp):
                _build_comparison_tab()
            with ui.tab_panel(tab_rank):
                _build_rankings_tab()
            with ui.tab_panel(tab_build):
                _build_refresh_shop = _build_eval_tab()
            with ui.tab_panel(tab_opt):
                _build_optimizer_tab()
            with ui.tab_panel(tab_hero):
                _build_hero_stats_tab()

        # Lazy-load the item shop only when the Build tab is first activated
        _shop_loaded = False

        def _on_tab_change(e):
            nonlocal _shop_loaded
            if e.value == "Build" and not _shop_loaded:
                _shop_loaded = True
                _build_refresh_shop()

        panels.on_value_change(_on_tab_change)

    ui.run(title="Deadlock Combat Simulator", port=8080, show=False, reconnect_timeout=30.0)


if __name__ in {"__main__", "__mp_main__"}:
    run_gui()
