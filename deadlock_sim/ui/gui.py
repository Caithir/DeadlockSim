"""NiceGUI web UI for the Deadlock combat simulator.

Browser-based UI with tabs for each simulator feature.
Item shop uses an icon grid with hover tooltips matching the in-game style.
All calculations delegated to deadlock_sim.engine.
"""

from __future__ import annotations

import asyncio
import math
import re
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

# Sort criteria available for items (static — no hero context needed)
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

# Impact sorts — computed per-hero/boon context; mapped to the score dict key
_IMPACT_SORT_KEYS: dict[str, str] = {
    "★ Gun DPS Δ":    "dps_delta",
    "★ EHP Δ":        "ehp_delta",
    "★ Spirit Power": "spirit_delta",
    "★ DPS / Soul":   "dps_per_soul",
    "★ EHP / Soul":   "ehp_per_soul",
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


def _prop_display(prop: dict) -> str:
    """Format a single property for display: prefix + value + postfix + label."""
    val = prop.get("value", "")
    if val in ("0", "-1", "-1.0", "0.0", ""):
        return ""
    label = prop.get("label", "")
    postfix = prop.get("postfix", "")
    prefix = prop.get("prefix", "")
    # Handle {s:sign} prefix
    if prefix == "{s:sign}":
        try:
            fv = float(str(val).rstrip("m"))
            prefix = "+" if fv >= 0 else ""
        except (ValueError, TypeError):
            prefix = "+"
    # Clean up value string
    val_str = str(val).rstrip("m") if postfix == "m" else str(val)
    postvalue = prop.get("postvalue_label", "")
    if postvalue:
        return f"{prefix}{val_str}{postfix} {postvalue}"
    elif label:
        return f"{prefix}{val_str}{postfix} {label}"
    return f"{prefix}{val_str}{postfix}"


def _build_tooltip_html(item: Item) -> str:
    """Build rich tooltip HTML matching the in-game item tooltip style."""
    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
    props = item.raw_properties or {}

    # Header: name + cost
    html = (
        f'<div style="min-width:220px;max-width:340px;">'
        f'<div style="font-size:16px;font-weight:bold;color:{colors["text"]};">'
        f'{item.name}</div>'
        f'<div style="font-size:12px;color:#4caf50;margin-bottom:6px;">'
        f'$ {item.cost:,}</div>'
    )

    sections = item.tooltip_sections or []
    if sections:
        for section in sections:
            sec_type = section.get("section_type", "")
            attrs_list = section.get("section_attributes", [])

            for attrs in attrs_list:
                # Innate stats (top section, before passive/active label)
                if sec_type == "innate":
                    all_props = (
                        attrs.get("properties", [])
                        + attrs.get("elevated_properties", [])
                    )
                    for prop_name in all_props:
                        p = props.get(prop_name)
                        if p:
                            txt = _prop_display(p)
                            if txt:
                                html += (
                                    f'<div style="color:#b0e8b0;font-size:12px;'
                                    f'line-height:1.6;">{txt}</div>'
                                )

                # Passive/Active section
                elif sec_type in ("passive", "active"):
                    label = sec_type.capitalize()
                    html += (
                        f'<div style="color:#888;font-size:11px;font-weight:bold;'
                        f'text-transform:uppercase;letter-spacing:0.08em;'
                        f'margin:6px 0 4px;padding:4px 0 2px;'
                        f'border-top:1px solid rgba(255,255,255,0.15);">'
                        f'{label}</div>'
                    )

                    # Description text
                    loc = attrs.get("loc_string", "")
                    if loc:
                        # Strip SVG icons from description
                        clean = re.sub(r'<svg[^>]*>.*?</svg>', '', loc, flags=re.DOTALL)
                        clean = clean.strip()
                        if clean:
                            html += (
                                f'<div style="color:#d0d0d0;font-size:12px;'
                                f'line-height:1.5;margin-bottom:6px;">'
                                f'{clean}</div>'
                            )

                    # Important properties (highlighted, like conditional bonuses)
                    for prop_name in attrs.get("important_properties", []):
                        p = props.get(prop_name)
                        if p:
                            txt = _prop_display(p)
                            cond = p.get("conditional", "")
                            is_cond = "ConditionallyApplied" in (
                                p.get("usage_flags", [])
                            )
                            if txt:
                                color = "#ffb347" if (cond or is_cond) else "#b0e8b0"
                                html += (
                                    f'<div style="color:{color};font-size:13px;'
                                    f'font-weight:bold;line-height:1.6;">{txt}'
                                )
                                if cond or is_cond:
                                    html += (
                                        '<div style="color:#888;font-size:10px;'
                                        'font-style:italic;">Conditional</div>'
                                    )
                                html += '</div>'

                    # Regular properties
                    for prop_name in attrs.get("properties", []):
                        p = props.get(prop_name)
                        if p:
                            txt = _prop_display(p)
                            if txt:
                                html += (
                                    f'<div style="color:#b0e8b0;font-size:12px;'
                                    f'line-height:1.6;">{txt}</div>'
                                )
    else:
        # Fallback: show raw properties if no tooltip_sections
        for key, p in props.items():
            if not isinstance(p, dict):
                continue
            txt = _prop_display(p)
            if txt:
                cond = p.get("conditional", "")
                is_cond = "ConditionallyApplied" in p.get("usage_flags", [])
                color = "#ffb347" if (cond or is_cond) else "#b0e8b0"
                html += (
                    f'<div style="color:{color};font-size:12px;'
                    f'line-height:1.6;">{txt}</div>'
                )

    # Upgrades to
    if item.upgrades_to:
        html += (
            f'<div style="margin-top:8px;padding-top:6px;'
            f'border-top:1px solid rgba(255,255,255,0.15);">'
            f'<span style="color:#888;font-size:10px;font-weight:bold;'
            f'text-transform:uppercase;letter-spacing:0.08em;">'
            f'UPGRADES TO:</span> '
            f'<span style="color:{colors["text"]};font-size:12px;'
            f'font-weight:bold;">{item.upgrades_to}</span>'
            f'</div>'
        )

    html += '</div>'
    return html


# ── Custom CSS ────────────────────────────────────────────────────

_CUSTOM_CSS = """
/* ── Item card (shop) ───────────────────────────────────────── */
.item-card {
    position: relative;
    width: 82px;
    display: flex; flex-direction: column; align-items: center;
    cursor: pointer;
    padding: 6px 4px 5px;
    border-radius: 8px;
    border: 2px solid transparent;
    transition: transform 0.1s, border-color 0.1s, box-shadow 0.1s;
    background: rgba(255,255,255,0.03);
    overflow: visible;
}
.item-card:hover {
    transform: translateY(-3px);
    border-color: rgba(255,255,255,0.25);
    box-shadow: 0 6px 16px rgba(0,0,0,0.5);
    z-index: 200;
}
.item-card img {
    width: 58px; height: 58px;
    object-fit: contain;
    filter: brightness(1.05);
}
.tooltip-name {
    font-weight: bold; font-size: 13px;
    margin-bottom: 4px;
}
.tooltip-cost { font-size: 11px; color: #e8c252; margin-bottom: 5px; }
.tooltip-stat { font-size: 11px; color: #b0e8b0; line-height: 1.5; }
.tooltip-condition {
    font-size: 10px; color: #ffb347;
    font-style: italic; margin-top: 4px;
}

/* ── Shop layout ─────────────────────────────────────────────── */
.shop-card-grid {
    display: flex; flex-wrap: wrap;
    gap: 4px; padding: 4px 0;
    align-items: flex-start;
}
/* keep old grid class for optimizer tab */
.shop-grid {
    display: flex; flex-wrap: wrap;
    gap: 2px; padding: 4px;
    align-items: flex-start;
}
.tier-section {
    margin: 6px 0; border-radius: 6px; overflow: visible;
}
.tier-label {
    font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
    padding: 4px 10px;
    border-radius: 4px 4px 0 0;
    display: inline-block;
}

/* ── Vertical category tabs ──────────────────────────────────── */
.cat-vtab-bar {
    display: flex; flex-direction: column;
    gap: 3px;
    padding: 8px 5px;
    background: #0c0c0c;
    border-right: 1px solid #1e1e1e;
    min-width: 50px; align-items: center;
}
.cat-vtab {
    width: 42px; height: 42px;
    border-radius: 8px;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px;
    border: 2px solid transparent;
    transition: all 0.15s;
    background: rgba(255,255,255,0.04);
    user-select: none;
}
.cat-vtab:hover { background: rgba(255,255,255,0.1); }

/* ── Build slot grid ─────────────────────────────────────────── */
.build-slots-grid {
    display: grid;
    grid-template-columns: repeat(4, 60px);
    gap: 5px;
    padding: 4px 0;
}
.build-slot-empty {
    width: 60px; height: 60px;
    border: 2px dashed #252525;
    border-radius: 7px;
    background: rgba(255,255,255,0.015);
}
.build-slot-filled {
    position: relative;
    width: 60px; height: 60px;
    border-radius: 7px;
    cursor: pointer;
    border: 2px solid;
    display: flex; align-items: center; justify-content: center;
    overflow: hidden;
    transition: filter 0.1s;
}
.build-slot-filled:hover { filter: brightness(1.35); }
.build-slot-cost {
    position: absolute; bottom: 0; left: 0; right: 0;
    background: rgba(0,0,0,0.75);
    font-size: 9px; text-align: center;
    padding: 1px 0; line-height: 1.25;
    border-radius: 0 0 5px 5px;
}

/* ── Stat rows in results panel ──────────────────────────────── */
.stat-row {
    display: flex; align-items: baseline;
    padding: 2px 0; gap: 6px;
    font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.04);
}
.stat-row-label { color: #888; flex: 1; }
.stat-row-val   { color: #e8e8e8; font-variant-numeric: tabular-nums; min-width: 52px; text-align: right; }
.stat-row-bonus { color: #7aff7a; font-size: 11px; min-width: 44px; text-align: right; }

/* ── Legacy chip (optimizer tab) ─────────────────────────────── */
.build-item-chip {
    display: flex; align-items: center;
    gap: 6px; padding: 4px 8px;
    border-radius: 6px; margin: 2px;
}
.build-item-chip img { width: 28px; height: 28px; object-fit: contain; }
.cat-tab { padding: 8px 20px; font-weight: bold; border-radius: 6px 6px 0 0; cursor: pointer; }
.cat-tab-active { border-bottom: 3px solid; }
.hero-chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 20px;
    background: #1a2a3d; border: 1px solid #4080c0;
    margin: 2px;
}

/* ── Build Lab: section headers ──────────────────────────────── */
.bl-section-header {
    font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
    color: #555; text-transform: uppercase;
    padding: 8px 0 5px; margin-bottom: 4px;
    border-bottom: 1px solid #1e1e1e;
}

/* ── Build Lab: hero summary ─────────────────────────────────── */
.bl-hero-summary {
    display: flex; align-items: center;
    gap: 8px; padding: 6px 0 4px; flex-wrap: wrap;
}
.bl-hero-icon {
    width: 48px; height: 48px; border-radius: 50%;
    object-fit: cover; border: 2px solid #3a3a3a; flex-shrink: 0;
}
.bl-ability-icon {
    width: 34px; height: 34px; border-radius: 6px;
    object-fit: contain; border: 1px solid #2a2a3a; background: #111;
}
.bl-ability-icons { display: flex; gap: 4px; }

/* ── Build Lab: ability progression grid ─────────────────────── */
.bl-prog-grid {
    display: flex; flex-direction: column; gap: 3px; padding: 4px 0;
}
.bl-prog-row { display: flex; gap: 2px; align-items: center; }
.bl-prog-label {
    width: 26px; font-size: 9px; color: #555;
    text-align: right; padding-right: 4px; flex-shrink: 0;
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}
.bl-prog-box {
    width: 13px; height: 13px; border-radius: 2px;
    border: 1px solid #252525; background: rgba(255,255,255,0.03); flex-shrink: 0;
}

/* ── Build Lab: item slots 6-wide ────────────────────────────── */
.bl-item-grid {
    display: grid;
    grid-template-columns: repeat(6, 48px);
    gap: 4px; padding: 4px 0;
}
.bl-slot-empty {
    width: 48px; height: 48px;
    border: 2px dashed #252525; border-radius: 6px;
    background: rgba(255,255,255,0.015);
}
.bl-slot-empty.bl-flex-slot {
    border-color: #333344; background: rgba(100,80,180,0.04);
}
.bl-slot-filled {
    position: relative; width: 48px; height: 48px;
    border-radius: 6px; cursor: pointer; border: 2px solid;
    display: flex; align-items: center; justify-content: center;
    overflow: hidden; transition: filter 0.1s;
}
.bl-slot-filled:hover { filter: brightness(1.4); }
.bl-slot-cost {
    position: absolute; bottom: 0; left: 0; right: 0;
    background: rgba(0,0,0,0.78);
    font-size: 8px; text-align: center;
    padding: 1px 0; line-height: 1.3;
    border-radius: 0 0 4px 4px;
}

/* ── Build Lab: shop bonus bars ──────────────────────────────── */
.bl-bars-row {
    display: flex; gap: 6px; align-items: flex-end; padding: 6px 0 2px;
}
.bl-bar-col {
    display: flex; flex-direction: column; align-items: center; gap: 3px; flex: 1;
}
.bl-bar-label { font-size: 9px; font-weight: 700; letter-spacing: 0.06em; }
.bl-bar-track {
    position: relative; width: 100%; height: 80px;
    background: rgba(255,255,255,0.05); border-radius: 3px; overflow: visible;
}
.bl-bar-fill { position: absolute; bottom: 0; left: 0; right: 0; border-radius: 3px; }
.bl-bar-tick {
    position: absolute; left: -3px; right: -3px;
    height: 1px; background: rgba(255,255,255,0.2); pointer-events: none;
}
.bl-bar-value { font-size: 10px; font-weight: 700; }

/* ── Build Lab: total souls bar ──────────────────────────────── */
.bl-souls-bar-wrap { padding: 4px 0 6px; }
.bl-souls-track {
    width: 100%; height: 14px; position: relative;
    background: rgba(255,255,255,0.05); border-radius: 7px; overflow: hidden;
}
.bl-souls-fill {
    position: absolute; top: 0; left: 0; bottom: 0;
    border-radius: 7px;
    background: linear-gradient(90deg, #d97e1f, #4caf50, #9c5dce);
}
.bl-souls-label {
    font-size: 10px; color: #888; font-weight: 600;
    text-align: center; margin-top: 3px;
}
"""


def _fmt_impact(val: float, sort_name: str, suffix: str) -> float | None:
    """Convert a raw impact score to a display float for item card badges."""
    if "Soul" in sort_name:
        val = val * 1000  # convert per-soul → per-1000-souls
    if abs(val) < 0.01:
        return None
    return val


def _render_item_card(
    item: Item,
    on_click_fn,
    score: float | None = None,
    score_suffix: str = "",
) -> None:
    """Render a shop item as a card: icon + name + optional score badge + tooltip."""
    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
    tooltip_inner = _build_tooltip_html(item)

    # Active badge overlay
    active_badge = ""
    if item.is_active or item.activation in ("press", "toggle", "innate_toggle"):
        active_badge = (
            '<div style="position:absolute;top:2px;right:2px;'
            'background:#1a8a1a;color:#fff;font-size:7px;font-weight:bold;'
            'padding:1px 3px;border-radius:2px;letter-spacing:0.05em;">ACTIVE</div>'
        )

    with ui.element("div").classes("item-card").style(
        f"border-color:{colors['border']}; background:{colors['bg']};"
    ).on("click", lambda _, it=item: on_click_fn(it)):
        ui.image(_item_image_url(item)).style("width: 48px; height: 48px; object-fit: contain;")
        if active_badge:
            ui.html(active_badge)
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

            # Stats section
            ui.separator()
            has_gun = hero.base_bullet_damage > 0 or hero.base_fire_rate > 0
            _hero_stat_cols = [
                {"name": "stat", "label": "Stat", "field": "stat", "align": "left"},
                {"name": "value", "label": "Value", "field": "value", "align": "left"},
            ]
            with ui.row().classes("gap-6 flex-wrap items-start"):
                # Weapon stats
                with ui.column().classes("gap-0"):
                    ui.label("Weapon").classes("text-sm font-bold text-orange-400 mb-1")
                    gun_rows = [
                        {"stat": "Bullet Damage", "value": f"{hero.base_bullet_damage:.2f}" if has_gun else "-"},
                        {"stat": "Fire Rate", "value": f"{hero.base_fire_rate:.2f} /s" if hero.base_fire_rate > 0 else "-"},
                        {"stat": "Base DPS", "value": _fv(hero.base_dps)},
                        {"stat": "Magazine", "value": _fv(hero.base_ammo, "d")},
                        {"stat": "DPM", "value": _fv(hero.base_dpm)},
                        {"stat": "Reload", "value": f"{hero.reload_duration:.2f}s" if hero.reload_duration > 0 else "-"},
                        {"stat": "Falloff", "value": f"{hero.falloff_range_min:.0f}m - {hero.falloff_range_max:.0f}m" if has_gun else "-"},
                    ]
                    ui.table(columns=_hero_stat_cols, rows=gun_rows, row_key="stat").classes("w-72").props("dense flat bordered")

                # Vitality stats
                with ui.column().classes("gap-0"):
                    ui.label("Vitality").classes("text-sm font-bold text-green-400 mb-1")
                    vit_rows = [
                        {"stat": "HP", "value": _fv(hero.base_hp, ".0f")},
                        {"stat": "Regen", "value": f"{hero.base_regen:.1f} /s"},
                        {"stat": "Move Speed", "value": _fv(hero.base_move_speed)},
                        {"stat": "Sprint", "value": f"{hero.base_sprint:.1f}"},
                        {"stat": "Stamina", "value": _fv(hero.base_stamina, "d")},
                        {"stat": "Light Melee", "value": _fv(hero.light_melee_damage, ".0f") if hero.light_melee_damage else "-"},
                        {"stat": "Heavy Melee", "value": _fv(hero.heavy_melee_damage, ".0f") if hero.heavy_melee_damage else "-"},
                    ]
                    ui.table(columns=_hero_stat_cols, rows=vit_rows, row_key="stat").classes("w-72").props("dense flat bordered")

                # Per-boon scaling
                with ui.column().classes("gap-0"):
                    ui.label("Per-Boon Scaling").classes("text-sm font-bold text-sky-400 mb-1")
                    scaling_rows = [
                        {"stat": "Dmg / Boon", "value": _fv(hero.damage_gain, "+.2%") if hero.damage_gain else "-"},
                        {"stat": "HP / Boon", "value": _fv(hero.hp_gain, "+.0f")},
                        {"stat": "Spirit / Boon", "value": _fv(hero.spirit_gain, "+.1f")},
                    ]
                    ui.table(columns=_hero_stat_cols, rows=scaling_rows, row_key="stat").classes("w-72").props("dense flat bordered")

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

    stat_columns = [
        {"name": "stat", "label": "Stat", "field": "stat", "align": "left"},
        {"name": "value", "label": "Value", "field": "value", "align": "left"},
    ]

    def update(_=None):
        hero = _heroes.get(hero_select.value)
        output.clear()
        if not hero:
            return
        with output:
            # Header with image
            with ui.row().classes("gap-4 items-start"):
                img_url = hero.hero_card_url or hero.icon_url
                if img_url:
                    ui.image(img_url).style(
                        "max-height: 120px; max-width: 90px; object-fit: contain; border-radius: 6px;"
                    )
                with ui.column().classes("gap-1"):
                    ui.label(hero.name).classes("text-lg font-bold text-amber-400")
                    if hero.hero_labs:
                        ui.label("[Hero Labs - stats may be incomplete]").classes("text-red-400 text-sm")
                    if hero.role:
                        ui.label(f"Role: {hero.role}").classes("text-gray-300 text-sm")
                    if hero.playstyle:
                        ui.label(hero.playstyle).classes("text-gray-400 text-xs")

            has_gun = hero.base_bullet_damage > 0 or hero.base_fire_rate > 0

            with ui.row().classes("gap-6 flex-wrap items-start"):
                # Gun stats
                with ui.column().classes("gap-0"):
                    ui.label("Weapon").classes("text-sm font-bold text-orange-400 mb-1")
                    gun_rows = [
                        {"stat": "Bullet Damage", "value": f"{hero.base_bullet_damage:.2f}" if has_gun else "-"},
                        {"stat": "Pellets", "value": f"{hero.pellets}" if has_gun else "-"},
                        {"stat": "Fire Rate", "value": f"{hero.base_fire_rate:.2f} /s" if hero.base_fire_rate > 0 else "-"},
                        {"stat": "Cycle Time", "value": f"{hero.cycle_time:.3f}s" if hero.cycle_time > 0 else "-"},
                        {"stat": "Base DPS", "value": _fv(hero.base_dps)},
                        {"stat": "Magazine", "value": _fv(hero.base_ammo, "d")},
                        {"stat": "DPM", "value": _fv(hero.base_dpm)},
                        {"stat": "Reload", "value": f"{hero.reload_duration:.2f}s" if hero.reload_duration > 0 else "-"},
                        {"stat": "Falloff Range", "value": f"{hero.falloff_range_min:.0f}m - {hero.falloff_range_max:.0f}m" if has_gun else "-"},
                    ]
                    if hero.alt_fire_type:
                        gun_rows.append({"stat": "Alt Fire", "value": hero.alt_fire_type.title()})
                    ui.table(columns=stat_columns, rows=gun_rows, row_key="stat").classes("w-80").props("dense flat bordered")

                # Vitality stats
                with ui.column().classes("gap-0"):
                    ui.label("Vitality").classes("text-sm font-bold text-green-400 mb-1")
                    vit_rows = [
                        {"stat": "HP", "value": _fv(hero.base_hp, ".0f")},
                        {"stat": "Regen", "value": f"{hero.base_regen:.1f} /s"},
                        {"stat": "Move Speed", "value": _fv(hero.base_move_speed)},
                        {"stat": "Sprint", "value": f"{hero.base_sprint:.1f}"},
                        {"stat": "Stamina", "value": _fv(hero.base_stamina, "d")},
                        {"stat": "Light Melee", "value": _fv(hero.light_melee_damage, ".0f") if hero.light_melee_damage else "-"},
                        {"stat": "Heavy Melee", "value": _fv(hero.heavy_melee_damage, ".0f") if hero.heavy_melee_damage else "-"},
                    ]
                    ui.table(columns=stat_columns, rows=vit_rows, row_key="stat").classes("w-80").props("dense flat bordered")

                # Scaling stats
                with ui.column().classes("gap-0"):
                    ui.label("Per-Boon Scaling").classes("text-sm font-bold text-sky-400 mb-1")
                    scaling_rows = [
                        {"stat": "Dmg Gain / Boon", "value": _fv(hero.damage_gain, "+.2%") if hero.damage_gain else "-"},
                        {"stat": "HP Gain / Boon", "value": _fv(hero.hp_gain, "+.0f")},
                        {"stat": "Spirit Gain / Boon", "value": _fv(hero.spirit_gain, "+.1f")},
                    ]
                    ui.table(columns=stat_columns, rows=scaling_rows, row_key="stat").classes("w-80").props("dense flat bordered")

                    # Max-level projections
                    if hero.max_level_hp > 0 or hero.max_gun_dps > 0:
                        ui.label("Max Level (48 boons)").classes("text-sm font-bold text-amber-400 mt-3 mb-1")
                        max_rows = [
                            {"stat": "Max HP", "value": _fv(hero.max_level_hp, ".0f")},
                            {"stat": "Max Gun Damage", "value": _fv(hero.max_gun_damage, ".2f") if hero.max_gun_damage > 0 else "-"},
                            {"stat": "Max Gun DPS", "value": _fv(hero.max_gun_dps, ".1f") if hero.max_gun_dps > 0 else "-"},
                        ]
                        ui.table(columns=stat_columns, rows=max_rows, row_key="stat").classes("w-80").props("dense flat bordered")

            # Abilities section
            if hero.abilities:
                ui.separator()
                ui.label("Abilities").classes("text-sm font-bold text-purple-400")

                for ability in hero.abilities:
                    if not ability.name:
                        continue
                    with ui.card().classes("w-full").style(
                        "background: #161625; border: 1px solid #2a2a4a; padding: 8px 12px;"
                    ):
                        with ui.row().classes("items-start gap-3 w-full"):
                            if ability.image_url:
                                ui.image(ability.image_url).style(
                                    "width: 40px; height: 40px; object-fit: contain; flex-shrink: 0; border-radius: 4px;"
                                )
                            with ui.column().classes("flex-grow gap-0"):
                                with ui.row().classes("items-center gap-2"):
                                    ui.label(ability.name).classes("font-bold text-amber-300 text-sm")
                                    if ability.ability_type:
                                        atype = ability.ability_type.replace("_", " ").title()
                                        badge_color = (
                                            "purple" if "spirit" in ability.ability_type.lower()
                                            else "orange" if "weapon" in ability.ability_type.lower()
                                            else "blue"
                                        )
                                        ui.badge(atype).props(f"color={badge_color}")

                                stat_parts = []
                                if ability.base_damage:
                                    stat_parts.append(f"Dmg: {ability.base_damage:.0f}")
                                if ability.spirit_scaling:
                                    stat_parts.append(f"Spirit: {ability.spirit_scaling:.2f}x")
                                if ability.cooldown:
                                    stat_parts.append(f"CD: {ability.cooldown:.1f}s")
                                if ability.duration:
                                    stat_parts.append(f"Dur: {ability.duration:.1f}s")
                                if stat_parts:
                                    ui.label(" | ".join(stat_parts)).classes("text-purple-300 text-xs font-mono")

                                if ability.upgrades:
                                    upgrade_html = "".join(
                                        f'<div style="margin-bottom:4px;">'
                                        f'<span style="color:#c084fc;font-weight:bold;">T{u.tier}:</span> '
                                        f'<span style="color:#e2d4f0;font-size:12px;">{u.description}</span>'
                                        f'</div>'
                                        for u in ability.upgrades
                                    )
                                    with ui.element("span").style("cursor:help; display:inline-block;"):
                                        ui.label("Upgrades ▸").classes("text-purple-400 text-xs underline")
                                        with ui.tooltip().style(
                                            "background:#2a1a3d; border:1px solid #9c5dce; "
                                            "padding:8px 12px; border-radius:6px; max-width:420px;"
                                        ):
                                            ui.html(upgrade_html)

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


# ── Tab: Build Lab ────────────────────────────────────────────────

_CAT_TAB_DEFS = [
    # (value, emoji, label, border_color, active_bg, text_color)
    ("all",      "✦", "All",      "#888888", "#444444", "#ffffff"),
    ("weapon",   "⚙", "Weapon",   "#e8a838", "#3a2200", "#e8a838"),
    ("vitality", "+", "Vitality", "#68b45c", "#0e2a08", "#68b45c"),
    ("spirit",   "✸", "Spirit",   "#9b74d4", "#1a0d38", "#c090f0"),
]

_TIER_COSTS_LABEL = {1: "500", 2: "1,250", 3: "3,000", 4: "6,200"}

# Shop bonus thresholds: (souls, weapon_bonus%, vitality_bonus%, spirit_bonus%)
_SHOP_BONUS_THRESHOLDS: list[tuple[int, int, int, int]] = [
    (800,    7,   8,   7),
    (1600,   9,  10,  11),
    (2400,  13,  13,  15),
    (3200,  20,  17,  19),
    (4800,  49,  34,  38),
    (7200,  60,  39,  48),
    (9600,  80,  44,  57),
    (16000, 95,  48,  66),
    (22400, 115, 52,  75),
]
_SHOP_BONUS_MAX_SOULS = 28800


# ── Build Lab HTML renderers (return pure HTML strings) ───────────


def _render_hero_summary_html(hero: "HeroStats | None") -> str:
    """Hero icon (circular) + hero name + 4 ability icons in a row."""
    if hero is None:
        return (
            '<div class="bl-hero-summary">'
            '<span style="color:#555;font-size:12px;">No hero selected</span>'
            '</div>'
        )
    icon = hero.icon_url or "/static/ui/all_stats.png"
    icon_tag = (
        f'<img class="bl-hero-icon" src="{icon}" alt="{hero.name}" '
        f'onerror="this.src=\'/static/ui/all_stats.png\'"/>'
    )
    name_tag = (
        f'<span style="font-size:12px;font-weight:700;color:#e8c252;">{hero.name}</span>'
    )
    ab_tags = ""
    for ab in [a for a in hero.abilities if a.name][:4]:
        src = ab.image_url or "/static/ui/all_stats.png"
        ab_tags += (
            f'<img class="bl-ability-icon" src="{src}" alt="{ab.name}" '
            f'title="{ab.name}" onerror="this.src=\'/static/ui/all_stats.png\'"/>'
        )
    return (
        f'<div class="bl-hero-summary">'
        f'{icon_tag}{name_tag}'
        f'<div class="bl-ability-icons">{ab_tags}</div>'
        f'</div>'
    )


def _render_hero_summary_with_tooltips(hero: "HeroStats | None") -> None:
    """Hero icon + name + ability icons with hover tooltips (NiceGUI elements)."""
    if hero is None:
        ui.label("No hero selected").style("color:#555; font-size:12px;")
        return

    with ui.element("div").classes("bl-hero-summary"):
        icon = hero.icon_url or "/static/ui/all_stats.png"
        ui.image(icon).classes("bl-hero-icon")
        ui.label(hero.name).style(
            "font-size:12px; font-weight:700; color:#e8c252;"
        )
        with ui.element("div").classes("bl-ability-icons"):
            for ab in [a for a in hero.abilities if a.name][:4]:
                src = ab.image_url or "/static/ui/all_stats.png"
                with ui.element("div").style(
                    "position:relative; display:inline-block;"
                ):
                    ui.image(src).classes("bl-ability-icon")
                    # Build ability tooltip content
                    tooltip_parts = []
                    tooltip_parts.append(
                        f'<div style="font-weight:bold;color:#e8c252;'
                        f'font-size:13px;margin-bottom:4px;">{ab.name}</div>'
                    )
                    if ab.ability_type:
                        atype = ab.ability_type.replace("_", " ").title()
                        tooltip_parts.append(
                            f'<div style="color:#9b74d4;font-size:10px;'
                            f'font-weight:bold;text-transform:uppercase;'
                            f'margin-bottom:4px;">{atype}</div>'
                        )
                    if ab.description:
                        import re
                        clean_desc = re.sub(
                            r'<svg[^>]*>.*?</svg>', '', ab.description,
                            flags=re.DOTALL
                        )
                        if clean_desc.strip():
                            tooltip_parts.append(
                                f'<div style="color:#d0d0d0;font-size:11px;'
                                f'line-height:1.4;margin-bottom:4px;">'
                                f'{clean_desc.strip()}</div>'
                            )
                    stat_parts = []
                    if ab.base_damage:
                        stat_parts.append(f"Damage: {ab.base_damage:.0f}")
                    if ab.cooldown:
                        stat_parts.append(f"CD: {ab.cooldown:.1f}s")
                    if ab.duration:
                        stat_parts.append(f"Dur: {ab.duration:.1f}s")
                    if ab.spirit_scaling:
                        stat_parts.append(f"Scale: {ab.spirit_scaling:.2f}x")
                    if stat_parts:
                        tooltip_parts.append(
                            f'<div style="color:#c084fc;font-size:11px;'
                            f'font-family:monospace;">'
                            f'{" | ".join(stat_parts)}</div>'
                        )
                    if ab.upgrades:
                        tooltip_parts.append(
                            '<div style="margin-top:6px;padding-top:4px;'
                            'border-top:1px solid rgba(255,255,255,0.15);">'
                        )
                        for u in ab.upgrades:
                            tooltip_parts.append(
                                f'<div style="margin-bottom:3px;">'
                                f'<span style="color:#c084fc;font-weight:bold;'
                                f'font-size:11px;">T{u.tier}:</span> '
                                f'<span style="color:#e2d4f0;font-size:11px;">'
                                f'{u.description}</span></div>'
                            )
                        tooltip_parts.append('</div>')

                    with ui.tooltip().style(
                        "background:#1a1030; border:1px solid #9c5dce; "
                        "padding:10px 14px; border-radius:8px; "
                        "max-width:360px; font-size:12px;"
                    ):
                        ui.html("".join(tooltip_parts))


def _render_ability_prog_html(hero: "HeroStats | None") -> str:
    """4 rows × 16 columns of empty ability-level boxes."""
    COLS = 16
    abilities = [a for a in (hero.abilities if hero else []) if a.name][:4]
    rows_html = ""
    for row_idx in range(4):
        ab = abilities[row_idx] if row_idx < len(abilities) else None
        label = (ab.name[:5] if ab else "—")
        title = (ab.name if ab else "")
        if ab:
            atype = (ab.ability_type or "").lower()
            box_color = "#d97e1f" if "weapon" in atype else "#9c5dce" if "spirit" in atype else "#2a2a3a"
        else:
            box_color = "#222"
        boxes = "".join(
            f'<div class="bl-prog-box" style="border-color:{box_color};"></div>'
            for _ in range(COLS)
        )
        rows_html += (
            f'<div class="bl-prog-row">'
            f'<span class="bl-prog-label" title="{title}">{label}</span>'
            f'{boxes}'
            f'</div>'
        )
    return f'<div class="bl-prog-grid">{rows_html}</div>'


def _render_bonus_bars_html(w_cost: int, v_cost: int, s_cost: int) -> str:
    """Three vertical shop-bonus bars (Weapon / Vitality / Spirit)."""
    MAX = _SHOP_BONUS_MAX_SOULS
    cat_defs = [
        ("weapon",   w_cost, _CAT_COLORS["weapon"]["border"],   _CAT_COLORS["weapon"]["text"],   "WPN", 1),
        ("vitality", v_cost, _CAT_COLORS["vitality"]["border"], _CAT_COLORS["vitality"]["text"], "VIT", 2),
        ("spirit",   s_cost, _CAT_COLORS["spirit"]["border"],   _CAT_COLORS["spirit"]["text"],   "SPI", 3),
    ]
    bars = ""
    for _cat, cost, fill_color, text_color, label, bonus_idx in cat_defs:
        fill_pct = min(100.0, cost / MAX * 100) if MAX > 0 else 0.0
        ticks = ""
        for (souls, *_bonuses) in _SHOP_BONUS_THRESHOLDS:
            tick_pct = min(100.0, souls / MAX * 100)
            earned = cost >= souls
            tick_color = "rgba(255,255,255,0.55)" if earned else "rgba(255,255,255,0.15)"
            ticks += (
                f'<div class="bl-bar-tick" '
                f'style="bottom:{tick_pct:.1f}%;background:{tick_color};"></div>'
            )
        cur_bonus = 0
        for thresh_tuple in reversed(_SHOP_BONUS_THRESHOLDS):
            if cost >= thresh_tuple[0]:
                cur_bonus = thresh_tuple[bonus_idx]
                break
        bonus_str = f"+{cur_bonus}" if cur_bonus else "—"
        bars += (
            f'<div class="bl-bar-col">'
            f'<div class="bl-bar-value" style="color:{text_color};">{bonus_str}</div>'
            f'<div class="bl-bar-track">'
            f'<div class="bl-bar-fill" style="height:{fill_pct:.1f}%;background:{fill_color};'
            f'opacity:0.75;"></div>'
            f'{ticks}'
            f'</div>'
            f'<div class="bl-bar-label" style="color:{text_color};">{label}</div>'
            f'</div>'
        )
    return f'<div class="bl-bars-row">{bars}</div>'


def _render_total_souls_html(total_cost: int) -> str:
    """Horizontal bar showing total souls spent vs cap."""
    MAX = _SHOP_BONUS_MAX_SOULS
    pct = min(100.0, total_cost / MAX * 100) if MAX > 0 else 0.0
    ticks = ""
    for (souls, *_) in _SHOP_BONUS_THRESHOLDS:
        t_pct = min(100.0, souls / MAX * 100)
        ticks += (
            f'<div style="position:absolute;top:0;bottom:0;left:{t_pct:.1f}%;'
            f'width:1px;background:rgba(255,255,255,0.2);"></div>'
        )
    return (
        f'<div class="bl-souls-bar-wrap">'
        f'<div class="bl-souls-track">'
        f'<div class="bl-souls-fill" style="width:{pct:.1f}%;"></div>'
        f'{ticks}'
        f'</div>'
        f'<div class="bl-souls-label">{total_cost:,} / {MAX:,} souls</div>'
        f'</div>'
    )


def _build_eval_tab() -> None:
    all_sort_options = list(_SORT_OPTIONS.keys()) + list(_IMPACT_SORT_KEYS.keys())
    cat_state = {"value": "all"}

    # ── Main two-column layout ────────────────────────────────────
    with ui.row().classes("w-full gap-0 items-start").style("min-height: 660px;"):

        # ══ LEFT: Build panel (three sections) ════════════════════
        with ui.column().style(
            "width:330px; min-width:300px; padding:0 12px 8px 0;"
            "border-right:1px solid #1e1e1e; gap:0;"
        ):

            # ── Section 1: HERO & ABILITY PROGRESSION ─────────────
            ui.element("div").classes("bl-section-header").text = "HERO & ABILITY PROGRESSION"

            with ui.row().classes("items-end gap-2 flex-wrap"):
                bld_hero = ui.select(
                    options=_hero_names,
                    value=_hero_names[0] if _hero_names else "",
                    label="Hero",
                ).classes("w-44")
            with ui.row().classes("items-end gap-2 flex-wrap mt-1"):
                bld_boons = ui.number(
                    label="Boons", value=0, min=0, max=50, step=1
                ).classes("w-24")
                bld_acc = ui.number(
                    label="Accuracy %", value=50, min=0, max=100
                ).classes("w-24")

            hero_summary_area  = ui.element("div").style("display:block; width:100%;")
            ability_prog_html  = ui.html("").style("display:block; width:100%;")

            ui.separator().style("margin:8px 0 4px;")

            # ── Section 2: PURCHASED ITEMS & BONUSES ──────────────
            ui.element("div").classes("bl-section-header").text = "PURCHASED ITEMS & BONUSES"

            build_grid       = ui.element("div").classes("bl-item-grid")
            bonus_bars_html  = ui.html("").style("display:block; width:100%;")
            total_souls_html = ui.html("").style("display:block; width:100%;")

            with ui.row().classes("w-full items-center gap-2 mt-1"):
                ui.button("Clear", on_click=lambda: clear_build()).props("dense flat").style(
                    "font-size:11px; color:#ccc;"
                )
                ui.element("div").style("flex:1")
                build_total_lbl = ui.label("0 Souls").style(
                    "color:#e8c252; font-size:12px; font-weight:700;"
                )

            ui.separator().style("margin:8px 0 4px;")

            # ── Section 3: CALCULATED HERO STATS ──────────────────
            ui.element("div").classes("bl-section-header").text = "CALCULATED HERO STATS"

            with ui.tabs().classes("w-full").style("min-height:32px;") as stat_tabs:
                stab_w = ui.tab("Weapon").style("color:#e8a838; font-size:12px; padding:4px 10px;")
                stab_v = ui.tab("Vitality").style("color:#68b45c; font-size:12px; padding:4px 10px;")
                stab_s = ui.tab("Spirit").style("color:#9b74d4; font-size:12px; padding:4px 10px;")

            with ui.tab_panels(stat_tabs, value=stab_w).classes("w-full"):
                with ui.tab_panel(stab_w):
                    stats_weapon   = ui.column().classes("w-full gap-0")
                with ui.tab_panel(stab_v):
                    stats_vitality = ui.column().classes("w-full gap-0")
                with ui.tab_panel(stab_s):
                    stats_spirit   = ui.column().classes("w-full gap-0")

        # ══ RIGHT: Filter bar + vertical cat tabs + shop ══════════
        with ui.column().classes("flex-grow gap-0").style("min-width:0;"):

            # Filter bar
            with ui.row().classes("w-full items-end gap-3 flex-wrap pb-1"):
                tier_filter = ui.select(
                    options=["All Tiers", "T1", "T2", "T3", "T4"],
                    value="All Tiers", label="Tier",
                ).classes("w-28")
                sort_select = ui.select(
                    options=all_sort_options,
                    value="Cost", label="Sort By",
                ).classes("w-48")
                bld_search = ui.input(
                    label="Search", placeholder="item name..."
                ).classes("w-36")

            ui.separator().style("margin:2px 0;")

            with ui.row().classes("flex-grow gap-0 items-start").style("min-width:0;"):

                # Vertical category tab strip
                with ui.column().classes("cat-vtab-bar"):
                    tab_els: dict[str, object] = {}

                    def make_cat_handler(cat_val: str):
                        def handler():
                            cat_state["value"] = cat_val
                            for cv, el in tab_els.items():
                                _, _, _, border, active_bg, text = next(
                                    d for d in _CAT_TAB_DEFS if d[0] == cv
                                )
                                if cv == cat_val:
                                    el.style(
                                        f"border-color:{border}; background:{active_bg};"
                                        f"color:{text};"
                                    )
                                else:
                                    el.style(
                                        f"border-color:transparent;"
                                        f"background:rgba(255,255,255,0.04);"
                                        f"color:{border};"
                                    )
                            refresh_shop()
                        return handler

                    for cv, emoji, label, border, active_bg, text in _CAT_TAB_DEFS:
                        init_border = border if cv == "all" else "transparent"
                        init_bg     = active_bg if cv == "all" else "rgba(255,255,255,0.04)"
                        el = (
                            ui.element("div")
                            .classes("cat-vtab")
                            .style(
                                f"border-color:{init_border}; background:{init_bg};"
                                f"color:{text};"
                            )
                            .on("click", make_cat_handler(cv))
                        )
                        with el:
                            ui.element("span").style(
                                "pointer-events:none; font-size:17px;"
                            ).text = emoji
                        tab_els[cv] = el
                        ui.tooltip(label).props("anchor='center right' self='center left'")

                # Shop scroll area
                shop_container = ui.scroll_area().classes("flex-grow border-l rounded-r").style(
                    "background:#0d0d16; height:620px; min-width:0;"
                )

    # ── Inner functions ───────────────────────────────────────────

    def _compute_impact_scores(filtered_items: list) -> dict:
        hero = _heroes.get(bld_hero.value)
        if not hero:
            return {}
        boons_val = int(bld_boons.value or 0)
        cur_build = Build(items=list(_build_items))
        cur_stats = BuildEngine.aggregate_stats(cur_build)
        cur_cfg   = BuildEngine.build_to_attacker_config(cur_stats, boons=boons_val)
        cur_dps   = DamageCalculator.calculate_bullet(hero, cur_cfg).raw_dps
        cur_ehp   = (hero.base_hp + hero.hp_gain * boons_val
                     + cur_stats.bonus_hp + cur_stats.bullet_shield)
        scores: dict = {}
        for item in filtered_items:
            t_stats = BuildEngine.aggregate_stats(Build(items=list(_build_items) + [item]))
            t_cfg   = BuildEngine.build_to_attacker_config(t_stats, boons=boons_val)
            dps_d   = DamageCalculator.calculate_bullet(hero, t_cfg).raw_dps - cur_dps
            ehp_d   = (hero.base_hp + hero.hp_gain * boons_val
                       + t_stats.bonus_hp + t_stats.bullet_shield) - cur_ehp
            cost    = item.cost or 1
            scores[item.name] = {
                "dps_delta":    dps_d,
                "ehp_delta":    ehp_d,
                "spirit_delta": item.spirit_power,
                "dps_per_soul": dps_d / cost,
                "ehp_per_soul": ehp_d / cost,
            }
        return scores

    def refresh_shop(_=None):
        cat       = cat_state["value"]
        tier_str  = tier_filter.value or "All Tiers"
        search    = (bld_search.value or "").lower().strip()
        sort_name = sort_select.value or "Cost"
        is_impact = sort_name in _IMPACT_SORT_KEYS

        filtered: list = []
        for item in _items.values():
            if cat != "all" and item.category != cat:
                continue
            if tier_str != "All Tiers" and f"T{item.tier}" != tier_str:
                continue
            if search and search not in item.name.lower():
                continue
            filtered.append(item)

        scores: dict = {}
        score_suffix = ""
        if is_impact:
            scores = _compute_impact_scores(filtered)
            score_key = _IMPACT_SORT_KEYS[sort_name]
            filtered.sort(key=lambda i: -scores.get(i.name, {}).get(score_key, 0))
            if "Soul" in sort_name:
                score_suffix = "/k"
        else:
            filtered.sort(key=_SORT_OPTIONS.get(sort_name, _SORT_OPTIONS["Cost"]))

        shop_container.clear()
        use_tier_groups = (sort_name == "Cost" and not search)

        with shop_container:
            with ui.element("div").style("padding:8px;"):
                if use_tier_groups:
                    for tier in [1, 2, 3, 4]:
                        tier_items = [i for i in filtered if i.tier == tier]
                        if not tier_items:
                            continue
                        cost_lbl = _TIER_COSTS_LABEL.get(tier, "?")
                        with ui.element("div").style(
                            "display:flex; align-items:center; gap:10px;"
                            "margin:10px 0 4px; border-bottom:1px solid #2a2a3a; padding-bottom:4px;"
                        ):
                            ui.element("span").style(
                                "font-size:11px; font-weight:700; letter-spacing:0.12em; color:#555;"
                            ).text = f"TIER {tier}"
                            ui.element("span").style(
                                "font-size:12px; font-weight:700; color:#e8c252;"
                            ).text = f"${cost_lbl}"

                        for cat_key in ["weapon", "vitality", "spirit"]:
                            cat_items = [i for i in tier_items if i.category == cat_key]
                            if not cat_items:
                                continue
                            colors = _CAT_COLORS[cat_key]
                            with ui.element("div").style(
                                f"border-left:3px solid {colors['border']};"
                                f"background:{colors['bg']}; border-radius:0 6px 6px 0;"
                                f"margin:3px 0; padding:4px 6px 6px;"
                            ):
                                ui.element("div").style(
                                    f"font-size:10px; font-weight:700; color:{colors['text']};"
                                    "letter-spacing:0.08em; margin-bottom:4px;"
                                ).text = colors["label"].upper()
                                with ui.element("div").classes("shop-card-grid"):
                                    for item in cat_items:
                                        sc = scores.get(item.name)
                                        sv = _fmt_impact(
                                            sc.get(_IMPACT_SORT_KEYS[sort_name], 0) if sc else 0,
                                            sort_name, score_suffix
                                        ) if (is_impact and sc) else None
                                        _render_item_card(item, add_item, score=sv, score_suffix=score_suffix)
                else:
                    with ui.element("div").classes("shop-card-grid"):
                        for item in filtered:
                            sc = scores.get(item.name)
                            sv = _fmt_impact(
                                sc.get(_IMPACT_SORT_KEYS[sort_name], 0) if sc else 0,
                                sort_name, score_suffix
                            ) if (is_impact and sc) else None
                            _render_item_card(item, add_item, score=sv, score_suffix=score_suffix)

    def add_item(item: Item):
        _build_items.append(item)
        refresh_build_display()
        update_results()
        if sort_select.value in _IMPACT_SORT_KEYS:
            refresh_shop()

    def remove_item(idx: int):
        if 0 <= idx < len(_build_items):
            _build_items.pop(idx)
            refresh_build_display()
            update_results()
            if sort_select.value in _IMPACT_SORT_KEYS:
                refresh_shop()

    def clear_build():
        _build_items.clear()
        refresh_build_display()
        update_results()
        if sort_select.value in _IMPACT_SORT_KEYS:
            refresh_shop()

    def refresh_build_display():
        total  = sum(i.cost for i in _build_items)
        w_cost = sum(i.cost for i in _build_items if i.category == "weapon")
        v_cost = sum(i.cost for i in _build_items if i.category == "vitality")
        s_cost = sum(i.cost for i in _build_items if i.category == "spirit")

        build_total_lbl.text = f"{total:,} Souls"

        # Update hero summary with NiceGUI elements (for ability tooltips)
        hero = _heroes.get(bld_hero.value)
        hero_summary_area.clear()
        with hero_summary_area:
            _render_hero_summary_with_tooltips(hero)
        ability_prog_html.content = _render_ability_prog_html(hero)

        # Update bonus bars + total souls bar HTML in-place
        bonus_bars_html.content  = _render_bonus_bars_html(w_cost, v_cost, s_cost)
        total_souls_html.content = _render_total_souls_html(total)

        # Rebuild item slot grid (needs NiceGUI elements for click handlers)
        build_grid.clear()
        with build_grid:
            for i, item in enumerate(_build_items):
                colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
                with ui.element("div").classes("bl-slot-filled").style(
                    f"border-color:{colors['border']}; background:{colors['bg']};"
                ).on("click", lambda _, idx=i: remove_item(idx)):
                    ui.image(_item_image_url(item)).style(
                        "width:40px; height:40px; object-fit:contain;"
                    )
                    ui.element("div").classes("bl-slot-cost").style(
                        f"color:{colors['text']};"
                    ).text = f"{item.cost:,}"
                    with ui.tooltip().style(
                        f"background:{colors['bg']}; border:1px solid {colors['border']};"
                        "padding:10px 14px; border-radius:8px; font-size:13px;"
                    ):
                        ui.html(
                            _build_tooltip_html(item)
                            + '<div style="color:#888;font-size:10px;margin-top:6px;'
                            'font-style:italic;">Click to remove</div>'
                        )

            # Empty slots — always show at least 2 full rows (12), round up to multiple of 6
            filled      = len(_build_items)
            min_slots   = max(12, filled + (6 - filled % 6) % 6)
            total_slots = ((min_slots + 5) // 6) * 6
            for slot_i in range(total_slots - filled):
                abs_pos  = filled + slot_i
                is_flex  = (abs_pos % 6) >= 4   # last 2 cols per row are flex
                cls = "bl-slot-empty bl-flex-slot" if is_flex else "bl-slot-empty"
                ui.element("div").classes(cls)

    def _stat_row(container, label: str, base_val: str, bonus_val: str = ""):
        with container:
            with ui.element("div").classes("stat-row"):
                ui.element("span").classes("stat-row-label").text = label
                ui.element("span").classes("stat-row-val").text   = base_val
                if bonus_val:
                    ui.element("span").classes("stat-row-bonus").text = bonus_val

    def update_results(_=None):
        hero = _heroes.get(bld_hero.value)
        for panel in [stats_weapon, stats_vitality, stats_spirit]:
            panel.clear()
        if not hero:
            return

        build   = Build(items=list(_build_items))
        boons   = int(bld_boons.value or 0)
        acc     = (bld_acc.value or 0) / 100.0
        result  = BuildEngine.evaluate_build(hero, build, boons=boons, accuracy=acc, headshot_rate=0.15)
        base_r  = BuildEngine.evaluate_build(hero, Build(), boons=boons, accuracy=acc, headshot_rate=0.15)
        bs      = result.build_stats
        br      = result.bullet_result
        bbr     = base_r.bullet_result

        def delta(val: float, base: float) -> str:
            d = val - base
            return f"+{d:.0f}" if d > 0.5 else ""

        def deltapct(val: float, base: float) -> str:
            d = val - base
            return f"+{d:.0%}" if abs(d) > 0.001 else ""

        # ── Weapon tab ───────────────────────────────────────────
        with stats_weapon:
            if br and br.raw_dps > 0:
                # Summary header: fire mode, DPS, Dmg/Mag
                fire_mode = "Single Shot"
                if hero.pellets > 1:
                    fire_mode = f"{hero.pellets} Pellets"
                with ui.element("div").style(
                    "background:#1a2a1a; border:1px solid #2a4a2a; border-radius:8px;"
                    "padding:8px 10px; margin-bottom:8px;"
                    "display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px; text-align:center;"
                ):
                    for lbl, val in [
                        (fire_mode,  f"{br.final_dps:.1f} DPS"),
                        ("Dmg/Mag",  f"{br.damage_per_magazine:.0f}"),
                        ("Mag",      f"{br.magazine_size}"),
                    ]:
                        with ui.element("div"):
                            ui.element("div").style("font-size:9px; color:#68b45c; font-weight:700;").text = lbl
                            ui.element("div").style("font-size:14px; color:#a0e890; font-weight:700;").text = val

                # All weapon stats - always shown
                _stat_row(stats_weapon, "Bullet Damage",
                    f"{br.damage_per_bullet:.1f}",
                    delta(br.damage_per_bullet, bbr.damage_per_bullet if bbr else 0))
                _stat_row(stats_weapon, "Weapon Damage",
                    f"{bs.weapon_damage_pct:.0%}" if bs.weapon_damage_pct else "0%",
                    f"+{bs.weapon_damage_pct:.0%}" if bs.weapon_damage_pct else "")
                _stat_row(stats_weapon, "Shots per Second",
                    f"{br.bullets_per_second:.2f}")
                _stat_row(stats_weapon, "Fire Rate",
                    f"{bs.fire_rate_pct:.0%}" if bs.fire_rate_pct else "0%",
                    f"+{bs.fire_rate_pct:.0%}" if bs.fire_rate_pct else "")
                _stat_row(stats_weapon, "Ammo",
                    f"{br.magazine_size}",
                    f"+{bs.ammo_flat}" if bs.ammo_flat else (f"+{bs.ammo_pct:.0%}" if bs.ammo_pct else ""))
                _stat_row(stats_weapon, "Clip Size Increase",
                    f"{bs.ammo_pct:.0%}" if bs.ammo_pct else "0%")
                _stat_row(stats_weapon, "Reload Time",
                    f"{hero.reload_duration:.1f}s" if hero.reload_duration > 0 else "-")
                _stat_row(stats_weapon, "Bullet Lifesteal",
                    f"{bs.bullet_lifesteal:.0%}" if bs.bullet_lifesteal else "0%")
                _stat_row(stats_weapon, "Crit Bonus Scale",
                    f"{bs.headshot_bonus:.0%}" if bs.headshot_bonus else "0%")

                ui.separator().style("margin:4px 0;")
                _stat_row(stats_weapon, "Raw DPS",   f"{br.raw_dps:.1f}")
                _stat_row(stats_weapon, "Final DPS", f"{br.final_dps:.1f}",
                    delta(br.final_dps, bbr.final_dps if bbr else 0))
                _stat_row(stats_weapon, "Dmg / Mag", f"{br.damage_per_magazine:.0f}")
                _stat_row(stats_weapon, "Mag Time",
                    f"{br.magdump_time:.2f}s" if br.magdump_time > 0 else "-")
                if bs.bullet_resist_shred:
                    _stat_row(stats_weapon, "Bullet Shred", "", f"{bs.bullet_resist_shred:.0%}")
            else:
                ui.label(f"No gun data for {hero.name}.").style("color:#f87171; font-size:12px;")

        # ── Vitality tab ─────────────────────────────────────────
        with stats_vitality:
            base_hp  = hero.base_hp + hero.hp_gain * boons
            total_hp = result.effective_hp
            with ui.element("div").style(
                "background:#1a1a2a; border:1px solid #2a2a4a; border-radius:8px;"
                "padding:8px 10px; margin-bottom:8px;"
                "display:grid; grid-template-columns:1fr 1fr; gap:4px; text-align:center;"
            ):
                for lbl, val in [
                    ("Eff HP",  f"{total_hp:.0f}"),
                    ("Base HP", f"{base_hp:.0f}"),
                ]:
                    with ui.element("div"):
                        ui.element("div").style("font-size:9px; color:#6888d4; font-weight:700;").text = lbl
                        ui.element("div").style("font-size:16px; color:#90a8f0; font-weight:700;").text = val

            _stat_row(stats_vitality, "Base HP",        f"{base_hp:.0f}")
            _stat_row(stats_vitality, "Bonus HP",       f"+{bs.bonus_hp:.0f}" if bs.bonus_hp else "0",
                delta(total_hp, base_r.effective_hp))
            _stat_row(stats_vitality, "Bullet Shield",  f"{bs.bullet_shield:.0f}" if bs.bullet_shield else "0")
            _stat_row(stats_vitality, "Spirit Shield",  f"{bs.spirit_shield:.0f}" if bs.spirit_shield else "0")
            _stat_row(stats_vitality, "HP Regen",       f"+{hero.base_regen + bs.hp_regen:.1f}/s",
                f"+{bs.hp_regen:.1f}" if bs.hp_regen else "")
            _stat_row(stats_vitality, "Bullet Resist",  f"{bs.bullet_resist_pct:.0%}" if bs.bullet_resist_pct else "0%",
                f"+{bs.bullet_resist_pct:.0%}" if bs.bullet_resist_pct else "")
            _stat_row(stats_vitality, "Spirit Resist",  f"{bs.spirit_resist_pct:.0%}" if bs.spirit_resist_pct else "0%",
                f"+{bs.spirit_resist_pct:.0%}" if bs.spirit_resist_pct else "")
            _stat_row(stats_vitality, "Move Speed",     f"{hero.base_move_speed:.1f}" if hero.base_move_speed else "-")
            _stat_row(stats_vitality, "Stamina",        f"{hero.base_stamina}")

        # ── Spirit tab ───────────────────────────────────────────
        with stats_spirit:
            spirit_dps = DamageCalculator.hero_total_spirit_dps(
                hero,
                current_spirit=int(bs.spirit_power),
                cooldown_reduction=bs.cooldown_reduction,
                spirit_amp=bs.spirit_amp_pct,
            )
            bullet_dps   = result.bullet_result.final_dps if result.bullet_result else 0.0
            combined_dps = bullet_dps + spirit_dps

            with ui.element("div").style(
                "background:#1a1228; border:1px solid #2a1848; border-radius:8px;"
                "padding:8px 10px; margin-bottom:8px; text-align:center;"
            ):
                ui.element("div").style("font-size:9px; color:#9b74d4; font-weight:700;").text = "SPIRIT POWER"
                ui.element("div").style("font-size:22px; color:#c090f0; font-weight:700;").text = (
                    f"+{bs.spirit_power:.0f}" if bs.spirit_power else "0"
                )
            _stat_row(stats_spirit, "Spirit Power",     f"+{bs.spirit_power:.0f}" if bs.spirit_power else "0")
            _stat_row(stats_spirit, "Spirit Amp",       f"+{bs.spirit_amp_pct:.0%}" if bs.spirit_amp_pct else "0%")
            _stat_row(stats_spirit, "Spirit Lifesteal", f"{bs.spirit_lifesteal:.0%}" if bs.spirit_lifesteal else "0%")
            _stat_row(stats_spirit, "CDR",              f"{bs.cooldown_reduction:.0%}" if bs.cooldown_reduction else "0%")
            _stat_row(stats_spirit, "Spirit Resist Shred",
                f"{bs.spirit_resist_shred:.0%}" if bs.spirit_resist_shred else "0%")

            ui.separator().style("margin:6px 0;")

            # DPS summary
            _stat_row(stats_spirit, "Spirit DPS",   f"{spirit_dps:.1f}" if spirit_dps > 0 else "-")
            _stat_row(stats_spirit, "Bullet DPS",   f"{bullet_dps:.1f}" if bullet_dps > 0 else "-")
            _stat_row(stats_spirit, "Combined DPS", f"{combined_dps:.1f}" if combined_dps > 0 else "-")

            ui.separator().style("margin:6px 0;")
            _stat_row(stats_spirit, "Total Cost", f"${bs.total_cost:,}")
            _stat_row(stats_spirit, "Items",      f"{len(_build_items)}")

    # ── Event wiring ──────────────────────────────────────────────
    def _on_hero_boons(_=None):
        refresh_build_display()   # updates hero summary + ability grid too
        update_results()
        if sort_select.value in _IMPACT_SORT_KEYS:
            refresh_shop()

    tier_filter.on_value_change(refresh_shop)
    sort_select.on_value_change(refresh_shop)
    bld_search.on_value_change(refresh_shop)
    bld_hero.on_value_change(_on_hero_boons)
    bld_boons.on_value_change(_on_hero_boons)
    bld_acc.on_value_change(update_results)

    refresh_build_display()
    update_results()
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
