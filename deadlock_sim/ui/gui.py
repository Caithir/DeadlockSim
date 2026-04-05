"""NiceGUI web UI for the Deadlock combat simulator.

Browser-based UI with tabs for each simulator feature.
Item shop uses an icon grid with hover tooltips matching the in-game style.
All calculations delegated to deadlock_sim.engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

from nicegui import app, ui

from ..api_client import ensure_data_available, refresh_all_data
from ..data import load_heroes, load_items
from ..engine.builds import BuildEngine
from ..engine.damage import DamageCalculator
from ..engine.simulation import CombatSimulator, SimConfig, SimResult, SimSettings
from ..models import Build, HeroStats, Item

# ── Shared read-only data (loaded once, safe for all clients) ─────

_heroes: dict[str, HeroStats] = {}
_hero_names: list[str] = []
_items: dict[str, Item] = {}
_item_names: list[str] = []


class _PageState:
    """Per-client mutable state, created fresh for each browser session."""

    def __init__(self) -> None:
        self.build_items: list[Item] = []
        self.build_ability_upgrades: dict[str, dict[int, int]] = {}
        self.build_hero_name: str = ""
        self.build_boons: int = 0
        self.sim_settings: dict = {
            "duration": 15.0,
            "accuracy": 0.65,
            "headshot_rate": 0.10,
            "headshot_multiplier": 1.50,
            "weapon_uptime": 1.0,
            "ability_uptime": 1.0,
            "active_item_uptime": 1.0,
            "weave_melee": False,
            "melee_after_reload": True,
            "bidirectional": False,
            "cond_shred": True,
            "cond_weapon": False,
            "cond_spirit": False,
            "cond_defense": False,
            "cond_sustain": False,
            "disabled_abilities": {},
            "ability_priority": {},
            "custom_item_dps": {},
            "custom_item_ehp": {},
        }

    def enabled_conditionals(self) -> set[str]:
        """Return the set of stat field names whose conditionals are enabled."""
        enabled: set[str] = set()
        for stat_name, setting_key in _COND_CATEGORY_MAP.items():
            if self.sim_settings.get(setting_key, False):
                enabled.add(stat_name)
        return enabled

    def get_ability_upgrades_map(self) -> dict[int, list[int]]:
        """Return ability upgrades for current build hero as {idx: [tiers]}."""
        upgrades = self.build_ability_upgrades.get(self.build_hero_name, {})
        return {idx: list(range(1, max_tier + 1)) for idx, max_tier in upgrades.items()}

    def get_sim_settings(self, atk_boons: int = 0, def_boons: int = 0) -> SimSettings:
        """Build a SimSettings from per-client settings."""
        s = self.sim_settings
        return SimSettings(
            duration=s["duration"],
            accuracy=s["accuracy"],
            headshot_rate=s["headshot_rate"],
            headshot_multiplier=s["headshot_multiplier"],
            weapon_uptime=s["weapon_uptime"],
            ability_uptime=s["ability_uptime"],
            active_item_uptime=s["active_item_uptime"],
            weave_melee=s["weave_melee"],
            melee_after_reload=s["melee_after_reload"],
            attacker_boons=atk_boons,
            defender_boons=def_boons,
            bidirectional=s["bidirectional"],
        )

    def get_ability_schedule(self, hero_name: str, hero: "HeroStats") -> list:
        """Build ability schedule respecting disabled abilities and priority."""
        from ..engine.simulation import AbilityUse

        disabled = self.sim_settings["disabled_abilities"].get(hero_name, set())
        priority = self.sim_settings["ability_priority"].get(hero_name, [])

        schedulable = []
        for i, ability in enumerate(hero.abilities):
            if i in disabled:
                continue
            if ability.base_damage > 0 and ability.cooldown > 0:
                schedulable.append(i)

        if priority:
            ordered = [i for i in priority if i in schedulable]
            remaining = [i for i in schedulable if i not in ordered]
            schedulable = ordered + remaining

        schedule = []
        for rank, idx in enumerate(schedulable):
            schedule.append(AbilityUse(
                ability_index=idx,
                first_use=0.1 * (rank + 1),
                use_on_cooldown=True,
            ))
        return schedule

# Mapping from stat field name → conditional category key in state.sim_settings
_COND_CATEGORY_MAP: dict[str, str] = {
    "bullet_resist_shred": "cond_shred",
    "spirit_resist_shred": "cond_shred",
    "weapon_damage_pct": "cond_weapon",
    "fire_rate_pct": "cond_weapon",
    "ammo_flat": "cond_weapon",
    "ammo_pct": "cond_weapon",
    "headshot_bonus": "cond_weapon",
    "spirit_power": "cond_spirit",
    "spirit_power_pct": "cond_spirit",
    "spirit_amp_pct": "cond_spirit",
    "bullet_resist_pct": "cond_defense",
    "spirit_resist_pct": "cond_defense",
    "bonus_hp": "cond_defense",
    "bullet_shield": "cond_defense",
    "spirit_shield": "cond_defense",
    "bullet_lifesteal": "cond_sustain",
    "spirit_lifesteal": "cond_sustain",
    "hp_regen": "cond_sustain",
    "cooldown_reduction": "cond_spirit",
}



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
    "Spirit Lifesteal %": lambda item: -item.spirit_lifesteal,
    "Leech %": lambda item: -(item.bullet_lifesteal + item.spirit_lifesteal),
    "HP Regen": lambda item: -item.hp_regen,
    "Shields": lambda item: -(item.bullet_shield + item.spirit_shield),
    "Bullet Shred %": lambda item: -item.bullet_resist_shred,
    "Spirit Shred %": lambda item: -item.spirit_resist_shred,
    "Cooldown Reduction %": lambda item: -item.cooldown_reduction,
    "Spirit Amp %": lambda item: -item.spirit_amp_pct,
}

# Impact sorts — computed per-hero/boon context; mapped to the score dict key
_IMPACT_SORT_KEYS: dict[str, str] = {
    "★ Gun DPS Δ":      "dps_delta",
    "★ Spirit DPS Δ":   "spirit_delta",
    "★ EHP Δ":          "ehp_delta",
    "★ DPS / Soul":     "dps_per_soul",
    "★ EHP / Soul":     "ehp_per_soul",
}

# Simulation-based impact sorts
_SIM_SORT_KEYS: dict[str, tuple[str, str]] = {
    "⚔ Sim Gun DPS Δ":     ("sim_dps_delta", "gun"),
    "⚔ Sim Spirit DPS Δ":  ("sim_dps_delta", "spirit"),
    "⚔ Sim Hybrid DPS Δ":  ("sim_dps_delta", "hybrid"),
    "⚔ Sim EHP Δ":         ("sim_ehp_delta", "gun"),
    "⚔ Sim DPS/Soul":      ("sim_dps_per_soul", "gun"),
    "⚔ Sim EHP/Soul":      ("sim_ehp_per_soul", "gun"),
}

# Color palette for multi-hero scaling charts
_CHART_COLORS = [
    "#4080ff", "#ff6040", "#40c060", "#c0c040",
    "#a040c0", "#40c0c0", "#ff80a0", "#80ffa0",
]

# Items with utility effects (CC, mobility, stealth, etc.) that the simulator
# cannot automatically model.  Users assign DPS/EHP-equivalent values in the
# Simulation Settings tab so the Build tab scoring can account for them.
_UTILITY_ITEMS: list[tuple[str, str]] = [
    ("Knockdown", "Stun after channel"),
    ("Slowing Hex", "Movement slow"),
    ("Silence Wave", "AoE silence"),
    ("Disarming Hex", "Disarm + spirit resist reduction"),
    ("Cursed Relic", "Interrupt, silence, disarm"),
    ("Ethereal Shift", "Invulnerability"),
    ("Vortex Web", "Vacuum grenade"),
    ("Metal Skin", "Bullet immunity"),
    ("Majestic Leap", "Mobility leap"),
    ("Warp Stone", "Teleport + fire rate"),
    ("Phantom Strike", "Teleport to enemy + melee"),
    ("Shadow Weave", "Stealth + ambush"),
    ("Unstoppable", "CC immunity"),
    ("Divine Barrier", "Cleanse + barrier"),
    ("Magic Carpet", "Flight"),
    ("Refresher", "Reset all cooldowns"),
    ("Echo Shard", "Reset imbued ability cooldown"),
    ("Colossus", "Size + HP + CC resistance"),
]


# ── Helpers ───────────────────────────────────────────────────────


def _compute_ehp(
    hero: HeroStats,
    bs: BuildStats,
    boons: int = 0,
) -> float:
    """Compute effective HP including all shields, resistances, and lifesteal.

    EHP = (raw_hp + shields) / (1 - bullet_resist) blended with spirit resist,
    plus a sustain bonus from lifesteal.
    """
    raw_hp = hero.base_hp + hero.hp_gain * boons + bs.bonus_hp
    total_shields = bs.bullet_shield + bs.spirit_shield
    pool = raw_hp + total_shields

    # Effective HP vs bullet damage (reduced by bullet resist)
    bullet_resist = min(0.9, max(0.0, bs.bullet_resist_pct))
    ehp_vs_bullet = pool / (1.0 - bullet_resist) if bullet_resist < 1.0 else pool * 10

    # Effective HP vs spirit damage (reduced by spirit resist)
    spirit_resist = min(0.9, max(0.0, bs.spirit_resist_pct))
    ehp_vs_spirit = pool / (1.0 - spirit_resist) if spirit_resist < 1.0 else pool * 10

    # Blended EHP (weight bullet slightly more as it's more common)
    ehp = ehp_vs_bullet * 0.55 + ehp_vs_spirit * 0.45

    # Sustain bonus: lifesteal adds effective survivability
    # Model as a percentage boost proportional to lifesteal rates
    sustain_mult = 1.0 + (bs.bullet_lifesteal * 0.5 + bs.spirit_lifesteal * 0.3)
    ehp *= sustain_mult

    return ehp


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


# Map API css_class values to category colors for stat lines
_STAT_CSS_CLASS_COLORS = {
    # Weapon (orange)
    "bullet_damage": "#f5a623", "fire_rate": "#f5a623", "clipsize": "#f5a623",
    "reload_speed": "#f5a623", "bullet_armor_down": "#f5a623",
    # Vitality (green)
    "health": "#6dd56e", "combat_barrier": "#6dd56e", "healing": "#6dd56e",
    "move_speed": "#6dd56e", "movement_speed": "#6dd56e", "melee_damage": "#6dd56e",
    "slow": "#6dd56e", "bullet_armor_up": "#6dd56e", "tech_armor_up": "#6dd56e",
    # Spirit (purple)
    "tech_power": "#c084fc", "spirit": "#c084fc", "tech_damage": "#c084fc",
    "tech_armor_down": "#c084fc", "cooldown": "#c084fc", "cast": "#c084fc",
    "duration": "#c084fc", "charge_cooldown": "#c084fc",
}


def _stat_color_for_prop(prop: dict) -> str:
    """Return a hex color for a property based on its css_class."""
    css_class = prop.get("css_class", "")
    return _STAT_CSS_CLASS_COLORS.get(css_class, "#b0e8b0")


def _build_tooltip_html(item: Item) -> str:
    """Build rich tooltip HTML matching the in-game item tooltip style."""
    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
    props = item.raw_properties or {}

    # Header: name + cost
    html = (
        f'<div style="min-width:220px;max-width:340px;word-wrap:break-word;overflow-wrap:break-word;">'
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
                                sc = _stat_color_for_prop(p)
                                html += (
                                    f'<div style="color:{sc};font-size:12px;'
                                    f'line-height:1.6;">{txt}</div>'
                                )

                # Passive/Active section (or missing section_type)
                elif sec_type in ("passive", "active", ""):
                    label = sec_type.capitalize() if sec_type else "Passive"
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
                                color = "#ffb347" if (cond or is_cond) else _stat_color_for_prop(p)
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
                                sc = _stat_color_for_prop(p)
                                html += (
                                    f'<div style="color:{sc};font-size:12px;'
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
                color = "#ffb347" if (cond or is_cond) else _stat_color_for_prop(p)
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
    width: 88px;
    display: flex; flex-direction: column; align-items: center;
    cursor: pointer;
    padding: 4px 4px 2px;
    border-radius: 6px;
    border: 2px solid transparent;
    transition: transform 0.1s, border-color 0.1s, box-shadow 0.1s;
    background: rgba(255,255,255,0.03);
    overflow: visible;
    gap: 0;
}
.item-card:hover {
    transform: translateY(-2px);
    border-color: rgba(255,255,255,0.25);
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    z-index: 200;
}
.item-card img {
    width: 54px; height: 54px;
    object-fit: contain;
    filter: brightness(1.05);
}
.item-card-name {
    font-size: 8px; font-weight: 600;
    color: #ccc; text-align: center;
    line-height: 1.15; margin-top: 1px;
    max-width: 84px; overflow: hidden;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.item-card-tier {
    position: absolute; top: 2px; left: 3px;
    font-size: 9px; font-weight: 700;
    color: rgba(255,255,255,0.7);
    text-shadow: 0 1px 2px rgba(0,0,0,0.8);
    pointer-events: none;
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
    gap: 2px; padding: 4px 0 6px;
    align-items: flex-start;
    overflow: visible;
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
.stat-row-click {
    display: flex; align-items: baseline;
    padding: 2px 0; gap: 6px;
    font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.04);
    cursor: pointer; border-radius: 3px;
}
.stat-row-click:hover { background: rgba(255,255,255,0.06); }
.stat-row-label { color: #888; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stat-row-val   { color: #e8e8e8; font-variant-numeric: tabular-nums; min-width: 40px; text-align: right; white-space: nowrap; }
.stat-row-bonus { color: #7aff7a; font-size: 11px; min-width: 32px; text-align: right; white-space: nowrap; }
.stat-row-perk  { color: #555; font-size: 10px; min-width: 32px; text-align: right; white-space: nowrap; }

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

/* ── Saved Builds tab ────────────────────────────────────────── */
.sb-card {
    background: #111120; border: 1px solid #2a2a4a; border-radius: 10px;
    padding: 14px 16px; width: 320px;
    transition: border-color 0.15s, box-shadow 0.15s;
    display: flex; flex-direction: column; gap: 6px;
}
.sb-card:hover { border-color: #4a4a7a; box-shadow: 0 4px 16px rgba(0,0,0,0.4); }
.sb-card-header {
    display: flex; justify-content: space-between; align-items: center; gap: 8px;
}
.sb-card-name {
    font-size: 14px; font-weight: 700; color: #e8e8e8;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;
}
.sb-badge {
    font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
    padding: 2px 8px; border-radius: 10px;
    text-transform: uppercase; flex-shrink: 0;
}
.sb-badge-gun { background: #3d2a12; color: #f5a623; border: 1px solid #d97e1f; }
.sb-badge-spirit { background: #2a1a3d; color: #c084fc; border: 1px solid #9c5dce; }
.sb-badge-hybrid { background: #1a2a3d; color: #60a0e0; border: 1px solid #4080c0; }
.sb-stats-row {
    display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; text-align: center;
    background: rgba(255,255,255,0.03); border-radius: 6px; padding: 6px 4px;
}
.sb-stat-label { font-size: 9px; font-weight: 700; }
.sb-stat-value { font-size: 14px; font-weight: 700; }
.sb-items-row {
    display: flex; flex-wrap: wrap; gap: 3px; padding: 4px 0;
}
.sb-item-icon {
    width: 32px; height: 32px; border-radius: 4px; border: 1px solid;
    object-fit: contain; background: #0a0a14;
}
.sb-card-footer {
    display: flex; justify-content: space-between; align-items: center;
    padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.06);
}
.sb-card-meta { font-size: 10px; color: #555; }
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
    score_detail: dict | None = None,
) -> ui.element:
    """Render a shop item as a card: icon + name + optional score badge + tooltip.

    score_detail: optional dict of score metrics to append to the tooltip
                  (e.g. {"sim_dps_delta": 12.3, "sim_ehp_delta": 5.0}).
    Returns the card root element so callers can track / remove it.
    """
    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
    tooltip_inner = _build_tooltip_html(item)

    # Append DPS/EHP delta info to tooltip if available
    if score_detail:
        tooltip_inner += (
            '<div style="margin-top:8px;padding-top:6px;'
            'border-top:1px solid rgba(255,255,255,0.15);">'
            '<div style="color:#888;font-size:10px;font-weight:bold;'
            'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">'
            'IMPACT</div>'
        )
        _score_labels = {
            "sim_dps_delta": ("DPS", "#e8a838"),
            "sim_ehp_delta": ("EHP", "#90a8f0"),
            "sim_dps_per_soul": ("DPS/1k Souls", "#e8a838"),
            "sim_ehp_per_soul": ("EHP/1k Souls", "#90a8f0"),
            "dps_delta": ("Gun DPS", "#e8a838"),
            "ehp_delta": ("EHP", "#90a8f0"),
            "spirit_delta": ("Spirit DPS", "#c090f0"),
            "dps_per_soul": ("DPS/1k Souls", "#e8a838"),
            "ehp_per_soul": ("EHP/1k Souls", "#90a8f0"),
        }
        for key, val in score_detail.items():
            if abs(val) < 0.01:
                continue
            label, color = _score_labels.get(key, (key, "#ccc"))
            sign = "+" if val > 0 else ""
            if "soul" in key.lower():
                display = f"{sign}{val * 1000:.1f}"
            else:
                display = f"{sign}{val:.1f}"
            tooltip_inner += (
                f'<div style="color:{color};font-size:12px;line-height:1.6;">'
                f'{label}: <b>{display}</b></div>'
            )
        tooltip_inner += '</div>'

    _TIER_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}

    card = ui.element("div").classes("item-card").style(
        f"border-color:{colors['border']}; background:{colors['bg']};"
    ).on("click", lambda _, it=item: on_click_fn(it))
    with card:
        ui.image(_item_image_url(item)).style("width: 54px; height: 54px; object-fit: contain;")
        # Tier indicator
        tier_label = _TIER_ROMAN.get(item.tier, "")
        if tier_label:
            ui.element("div").classes("item-card-tier").text = tier_label
        # Score badge (shown when sorting by impact/sim metrics)
        if score is not None:
            sign = "+" if score > 0 else ""
            badge_color = "#4fc3f7" if score > 0 else "#ef5350"
            ui.element("div").style(
                f"font-size:9px; font-weight:700; color:{badge_color};"
                "text-align:center; line-height:1.2; margin-top:1px;"
            ).text = f"{sign}{score:.1f}{score_suffix}"
        # Item name
        ui.element("div").classes("item-card-name").text = item.name
        with ui.tooltip().style(
            f"background:{colors['bg']}; border:1px solid {colors['border']}; "
            "padding:10px 14px; border-radius:8px; font-size:13px;"
            "max-width:380px; white-space:normal; word-wrap:break-word;"
        ):
            ui.html(tooltip_inner)
    return card

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
                        {"stat": "Dmg Gain / Boon", "value": _fv(hero.damage_gain, "+.2f") if hero.damage_gain else "-"},
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

# ── Tab: Build Lab ────────────────────────────────────────────────

_CAT_TAB_DEFS = [
    # (value, emoji, label, border_color, active_bg, text_color)
    ("all",      "✦", "All",      "#888888", "#444444", "#ffffff"),
    ("weapon",   "⚙", "Weapon",   "#e8a838", "#3a2200", "#e8a838"),
    ("vitality", "+", "Vitality", "#68b45c", "#0e2a08", "#68b45c"),
    ("spirit",   "✸", "Spirit",   "#9b74d4", "#1a0d38", "#c090f0"),
]

_TIER_COSTS_LABEL = {1: "500", 2: "1,250", 3: "3,000", 4: "6,200"}

# Shop bonus thresholds: (souls, weapon_bonus%, vitality_bonus%, spirit_bonus)
# Must match _SHOP_TIER_DATA in data.py
_SHOP_BONUS_THRESHOLDS: list[tuple[int, int, int, int]] = [
    (800,    7,   8,   7),
    (1600,   9,  10,  11),
    (2400,  13,  13,  15),
    (3200,  20,  17,  19),
    (4800,  49,  22,  25),
    (7200,  60,  27,  32),
    (9600,  80,  32,  44),
    (16000, 95,  36,  56),
    (22400, 115, 40,  69),
    (28800, 135, 44,  81),
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


def _build_eval_tab(state: _PageState) -> None:
    all_sort_options = list(_SORT_OPTIONS.keys()) + list(_IMPACT_SORT_KEYS.keys()) + list(_SIM_SORT_KEYS.keys())
    cat_state = {"value": "all"}
    _card_refs: dict[str, ui.element] = {}  # item-name → card element for targeted removal

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
                bld_acc = ui.number(
                    label="Accuracy %", value=50, min=0, max=100
                ).classes("w-24")
                bld_extra_souls = ui.number(
                    label="Extra Souls", value=0, min=0, max=100000, step=100
                ).classes("w-28")

            # Auto-calculated boon/AP info bar
            boon_info_area = ui.element("div").style("display:block; width:100%;")

            hero_summary_area  = ui.element("div").style("display:block; width:100%;")

            # Ability upgrade allocation area (replaces old progression grid)
            ability_upgrade_area = ui.element("div").style("display:block; width:100%;")

            ui.separator().style("margin:8px 0 4px;")

            # ── Section 2: PURCHASED ITEMS & BONUSES ──────────────
            ui.element("div").classes("bl-section-header").text = "PURCHASED ITEMS & BONUSES"

            build_grid       = ui.element("div").classes("bl-item-grid")

            with ui.row().classes("w-full items-center gap-2 mt-1"):
                ui.button("Clear", on_click=lambda: clear_build()).props("dense flat").style(
                    "font-size:11px; color:#ccc;"
                )
                save_build_btn = ui.button("Save", icon="bookmark").props("dense flat").style(
                    "font-size:11px; color:#68d4a8;"
                )
                ui.element("div").style("flex:1")
                build_total_lbl = ui.label("0 Souls").style(
                    "color:#e8c252; font-size:12px; font-weight:700;"
                )

            ui.separator().style("margin:8px 0 4px;")

            # ── Section 3: CALCULATED HERO STATS ──────────────────
            ui.element("div").classes("bl-section-header").text = "CALCULATED HERO STATS"

            stats_all = ui.column().classes("w-full gap-0")

        # ══ RIGHT: Filter bar + vertical cat tabs + shop ══════════
        with ui.column().classes("flex-grow gap-0").style("min-width:0; overflow:hidden;"):

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
                show_legendary = ui.checkbox("Show Legendary", value=False).on(
                    "update:model-value", lambda: refresh_shop()
                )

            ui.separator().style("margin:2px 0;")

            with ui.row().classes("w-full gap-0 items-start").style("min-width:0; flex:1 1 0;"):

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
                            ui.tooltip(label).props("anchor='center right' self='center left'")
                        tab_els[cv] = el

                # Shop scroll area
                shop_container = ui.scroll_area().classes("border-l rounded-r").style(
                    "background:#0d0d16; height:620px; min-width:0; flex:1 1 0;"
                )

    # ── Inner functions ───────────────────────────────────────────

    def _ehp(hero, boons, stats):
        """Compute EHP with resistances, shields, and vitality investment."""
        base_hp = (hero.base_hp + hero.hp_gain * boons) * (1.0 + stats.base_hp_pct)
        ehp = base_hp + stats.bonus_hp + stats.bullet_shield + stats.spirit_shield
        if stats.bullet_resist_pct > 0:
            ehp /= (1.0 - min(0.9, stats.bullet_resist_pct))
        if stats.spirit_resist_pct > 0:
            spirit_mult = 1.0 / (1.0 - min(0.9, stats.spirit_resist_pct))
            ehp = ehp * (0.5 + 0.5 * spirit_mult)
        return ehp

    def _current_boons():
        """Auto-calculate boon count from total souls (items + extra)."""
        from ..data import souls_to_boons
        total = sum(i.cost for i in state.build_items) + int(bld_extra_souls.value or 0)
        return souls_to_boons(total)

    def _current_ability_upgrades_map():
        """Return ability upgrades for current hero as {idx: [tiers]}."""
        hero = _heroes.get(bld_hero.value)
        if not hero:
            return {}
        upgrades = state.build_ability_upgrades.get(hero.name, {})
        return {idx: list(range(1, max_tier + 1)) for idx, max_tier in upgrades.items()}

    def _compute_impact_scores(filtered_items: list) -> dict:
        hero = _heroes.get(bld_hero.value)
        if not hero:
            return {}
        boons_val = _current_boons()
        ab_upgrades = _current_ability_upgrades_map()
        cur_build = Build(items=list(state.build_items))
        ec = state.enabled_conditionals()
        cur_stats = BuildEngine.aggregate_stats(cur_build, enabled_conditionals=ec)
        cur_cfg   = BuildEngine.build_to_attacker_config(cur_stats, boons=boons_val, spirit_gain=hero.spirit_gain)
        cur_gun   = DamageCalculator.calculate_bullet(hero, cur_cfg).sustained_dps
        cur_spirit = DamageCalculator.hero_total_spirit_dps(
            hero,
            current_spirit=cur_cfg.current_spirit,
            cooldown_reduction=cur_stats.cooldown_reduction,
            spirit_amp=cur_stats.spirit_amp_pct,
            resist_shred=cur_stats.spirit_resist_shred,
            ability_upgrades=ab_upgrades,
        )
        cur_ehp   = _ehp(hero, boons_val, cur_stats)
        scores: dict = {}
        for item in filtered_items:
            # Recalculate boons with the trial item added
            from ..data import souls_to_boons as _s2b
            trial_total = sum(i.cost for i in state.build_items) + item.cost + int(bld_extra_souls.value or 0)
            trial_boons = _s2b(trial_total)
            t_stats = BuildEngine.aggregate_stats(Build(items=list(state.build_items) + [item]), enabled_conditionals=ec)
            t_cfg   = BuildEngine.build_to_attacker_config(t_stats, boons=trial_boons, spirit_gain=hero.spirit_gain)
            gun_d   = DamageCalculator.calculate_bullet(hero, t_cfg).sustained_dps - cur_gun
            spirit_d = DamageCalculator.hero_total_spirit_dps(
                hero,
                current_spirit=t_cfg.current_spirit,
                cooldown_reduction=t_stats.cooldown_reduction,
                spirit_amp=t_stats.spirit_amp_pct,
                resist_shred=t_stats.spirit_resist_shred,
                ability_upgrades=ab_upgrades,
            ) - cur_spirit
            ehp_d   = _ehp(hero, trial_boons, t_stats) - cur_ehp
            cost    = item.cost or 1
            scores[item.name] = {
                "dps_delta":    gun_d,
                "ehp_delta":    ehp_d,
                "spirit_delta": spirit_d,
                "dps_per_soul": (gun_d + spirit_d) / cost,
                "ehp_per_soul": ehp_d / cost,
            }
        return scores

    def refresh_shop(_=None):
        cat       = cat_state["value"]
        tier_str  = tier_filter.value or "All Tiers"
        search    = (bld_search.value or "").lower().strip()
        sort_name = sort_select.value or "Cost"
        is_impact = sort_name in _IMPACT_SORT_KEYS
        is_sim    = sort_name in _SIM_SORT_KEYS

        # Collect names of already-purchased items
        owned_names = {i.name for i in state.build_items}

        filtered: list = []
        for item in _items.values():
            if item.name in owned_names:
                continue
            if cat != "all" and item.category != cat:
                continue
            if tier_str != "All Tiers" and f"T{item.tier}" != tier_str:
                continue
            if not show_legendary.value and item.tier == 5:
                continue
            if search and search not in item.name.lower():
                continue
            filtered.append(item)

        scores: dict = {}
        score_suffix = ""
        active_score_key = ""

        # Always compute impact scores for tooltips when a hero is selected
        impact_scores: dict = {}
        if _heroes.get(bld_hero.value):
            impact_scores = _compute_impact_scores(filtered)

        if is_sim:
            hero = _heroes.get(bld_hero.value)
            if hero:
                score_key, sim_mode = _SIM_SORT_KEYS[sort_name]
                boons_val = _current_boons()
                scores = _sim_item_scores(state, hero, list(state.build_items), filtered, boons_val, sim_mode)
                active_score_key = score_key
                filtered.sort(key=lambda i: -scores.get(i.name, {}).get(score_key, 0))
                if "Soul" in sort_name:
                    score_suffix = "/k"
        elif is_impact:
            scores = impact_scores
            active_score_key = _IMPACT_SORT_KEYS[sort_name]
            filtered.sort(key=lambda i: -scores.get(i.name, {}).get(active_score_key, 0))
            if "Soul" in sort_name:
                score_suffix = "/k"
        else:
            filtered.sort(key=_SORT_OPTIONS.get(sort_name, _SORT_OPTIONS["Cost"]))

        is_scored = is_impact or is_sim

        # Filter out items with zero change for the active sort metric
        if is_scored and active_score_key:
            filtered = [
                i for i in filtered
                if abs(scores.get(i.name, {}).get(active_score_key, 0)) >= 0.01
            ]

        shop_container.clear()
        _card_refs.clear()
        use_tier_groups = (sort_name == "Cost" and not search)

        with shop_container:
            with ui.element("div").style("padding:8px;"):
                if is_sim:
                    ui.element("div").style(
                        "font-size:10px; color:#e8c252; font-weight:700; margin-bottom:6px;"
                        "padding:4px 8px; background:#1a1a0a; border-radius:4px;"
                    ).text = f"Simulation scoring: {sort_name} (may take a moment)"

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
                                f"margin:3px 0; padding:4px 6px 8px; overflow:visible;"
                            ):
                                ui.element("div").style(
                                    f"font-size:10px; font-weight:700; color:{colors['text']};"
                                    "letter-spacing:0.08em; margin-bottom:4px;"
                                ).text = colors["label"].upper()
                                with ui.element("div").classes("shop-card-grid"):
                                    for item in cat_items:
                                        sc = scores.get(item.name)
                                        sv = _fmt_impact(
                                            sc.get(active_score_key, 0) if sc else 0,
                                            sort_name, score_suffix
                                        ) if (is_scored and sc) else None
                                        # Use sim scores when available, otherwise impact scores
                                        detail = sc if is_sim else impact_scores.get(item.name)
                                        _card_refs[item.name] = _render_item_card(item, add_item, score=sv, score_suffix=score_suffix,
                                                         score_detail=detail)
                else:
                    with ui.element("div").classes("shop-card-grid"):
                        for item in filtered:
                            sc = scores.get(item.name)
                            sv = _fmt_impact(
                                sc.get(active_score_key, 0) if sc else 0,
                                sort_name, score_suffix
                            ) if (is_scored and sc) else None
                            detail = sc if is_sim else impact_scores.get(item.name)
                            _card_refs[item.name] = _render_item_card(item, add_item, score=sv, score_suffix=score_suffix,
                                             score_detail=detail)

    def _is_dynamic_sort():
        return sort_select.value in _IMPACT_SORT_KEYS or sort_select.value in _SIM_SORT_KEYS

    def add_item(item: Item):
        if any(i.name == item.name for i in state.build_items):
            return
        state.build_items.append(item)
        state.build_boons = _current_boons()
        refresh_build_display()
        update_results()
        # When using dynamic scoring, item scores all change — full refresh needed.
        # Otherwise just remove the purchased card to avoid icon flash.
        if _is_dynamic_sort():
            refresh_shop()
        elif item.name in _card_refs:
            _card_refs.pop(item.name).delete()
        else:
            refresh_shop()

    def remove_item(idx: int):
        if 0 <= idx < len(state.build_items):
            state.build_items.pop(idx)
            state.build_boons = _current_boons()
            refresh_build_display()
            update_results()
            refresh_shop()

    def clear_build():
        state.build_items.clear()
        state.build_boons = _current_boons()
        refresh_build_display()
        update_results()
        refresh_shop()

    async def save_current_build():
        """Save the current build to browser localStorage via a name dialog."""
        hero = _heroes.get(bld_hero.value)
        if not hero or not state.build_items:
            ui.notify("Add a hero and items before saving.", type="warning")
            return

        # Compute stats for the save snapshot
        build = Build(items=list(state.build_items))
        boons = _current_boons()
        ab_upgrades = _current_ability_upgrades_map()
        acc = (bld_acc.value or 0) / 100.0
        ec = state.enabled_conditionals()
        result = BuildEngine.evaluate_build(hero, build, boons=boons, accuracy=acc, headshot_rate=0.15, enabled_conditionals=ec)
        bs = result.build_stats
        br = result.bullet_result

        boon_spirit = hero.spirit_gain * boons
        total_spirit = int((bs.spirit_power + boon_spirit) * (1.0 + bs.spirit_power_pct))
        spirit_dps = DamageCalculator.hero_total_spirit_dps(
            hero, current_spirit=total_spirit,
            cooldown_reduction=bs.cooldown_reduction,
            spirit_amp=bs.spirit_amp_pct,
            resist_shred=bs.spirit_resist_shred,
            ability_upgrades=ab_upgrades,
        )
        gun_dps = br.sustained_dps if br and br.raw_dps > 0 else 0.0
        build_type = _classify_build_type(gun_dps, spirit_dps)

        # Show a dialog to name the build
        with ui.dialog() as dlg, ui.card().style("min-width:340px;"):
            ui.label("Save Build").classes("text-lg font-bold text-amber-400")
            name_input = ui.input(
                label="Build Name",
                value=f"{hero.name} {build_type}",
            ).classes("w-full")

            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button("Cancel", on_click=dlg.close).props("flat")

                async def _do_save():
                    from datetime import datetime
                    import uuid
                    build_name = (name_input.value or "").strip()
                    if not build_name:
                        ui.notify("Enter a build name.", type="warning")
                        return
                    entry = {
                        "id": str(uuid.uuid4()),
                        "hero_name": hero.name,
                        "build_name": build_name,
                        "build_type": build_type,
                        "items": [i.name for i in state.build_items],
                        "extra_souls": int(bld_extra_souls.value or 0),
                        "ability_upgrades": {
                            h: {str(k): v for k, v in m.items()}
                            for h, m in state.build_ability_upgrades.items()
                        },
                        "gun_dps": round(gun_dps, 1),
                        "spirit_dps": round(spirit_dps, 1),
                        "ehp": round(result.effective_hp, 0),
                        "total_cost": bs.total_cost,
                        "accuracy": acc,
                        "saved_at": datetime.now().isoformat(),
                    }
                    # Read existing, append, write back
                    raw = await ui.run_javascript(
                        f"localStorage.getItem('{_LOCALSTORAGE_KEY}')"
                    )
                    builds = []
                    if raw:
                        try:
                            builds = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            builds = []
                    builds.append(entry)
                    payload = json.dumps(builds)
                    await ui.run_javascript(
                        f"localStorage.setItem('{_LOCALSTORAGE_KEY}', {json.dumps(payload)})"
                    )
                    dlg.close()
                    ui.notify(f"Build '{build_name}' saved!", type="positive")

                ui.button("Save", on_click=_do_save).props("color=primary")

        dlg.open()

    save_build_btn.on_click(save_current_build)

    def refresh_build_display():
        from ..data import souls_to_boons, souls_to_ability_points, ABILITY_TIER_COSTS

        total  = sum(i.cost for i in state.build_items)
        extra  = int(bld_extra_souls.value or 0)
        total_souls = total + extra

        build_total_lbl.text = f"{total:,} Souls"

        boons_val = souls_to_boons(total_souls)
        ap_total  = souls_to_ability_points(total_souls)

        # Compute spent AP for current hero
        hero = _heroes.get(bld_hero.value)
        hero_name = hero.name if hero else ""
        ap_spent = 0
        upgrades_map = state.build_ability_upgrades.get(hero_name, {})
        for _idx, max_tier in upgrades_map.items():
            for t in range(max_tier):
                if t < len(ABILITY_TIER_COSTS):
                    ap_spent += ABILITY_TIER_COSTS[t]
        ap_remaining = max(0, ap_total - ap_spent)

        # Update boon/AP info bar
        boon_info_area.clear()
        with boon_info_area:
            with ui.element("div").style(
                "display:flex;gap:10px;align-items:center;margin:4px 0 2px;"
                "padding:4px 8px;background:#111120;border-radius:6px;border:1px solid #2a2a4a;"
            ):
                ui.label(f"{total_souls:,} Souls").style(
                    "color:#e8c252;font-size:12px;font-weight:700;"
                )
                ui.label(f"⬥ {boons_val} Boons").style(
                    "color:#c090f0;font-size:11px;"
                )
                ui.label(f"⬥ AP: {ap_remaining}/{ap_total}").style(
                    "color:#68d4a8;font-size:11px;"
                )

        # Update hero summary with NiceGUI elements (for ability tooltips)
        hero_summary_area.clear()
        with hero_summary_area:
            _render_hero_summary_with_tooltips(hero)

        # ── Ability upgrade allocation ────────────────────────────
        ability_upgrade_area.clear()
        with ability_upgrade_area:
            if hero and hero.abilities:
                abilities = [a for a in hero.abilities if a.name][:4]
                num_abilities = len(abilities)

                # Pre-compute current stats for delta comparison
                build = Build(items=list(state.build_items))
                cur_stats = BuildEngine.aggregate_stats(build, enabled_conditionals=state.enabled_conditionals())
                cur_boons = boons_val
                cur_ab_map = {idx: list(range(1, mt + 1)) for idx, mt in upgrades_map.items()}
                boon_sp = hero.spirit_gain * cur_boons
                cur_total_spirit = int(
                    (cur_stats.spirit_power + boon_sp) * (1.0 + cur_stats.spirit_power_pct)
                )
                cur_spirit_dps = DamageCalculator.hero_total_spirit_dps(
                    hero, current_spirit=cur_total_spirit,
                    cooldown_reduction=cur_stats.cooldown_reduction,
                    spirit_amp=cur_stats.spirit_amp_pct,
                    resist_shred=cur_stats.spirit_resist_shred,
                    ability_upgrades=cur_ab_map,
                )

                for ab_idx in range(num_abilities):
                    ab = abilities[ab_idx]
                    atype = (ab.ability_type or "").lower()
                    border_col = "#d97e1f" if "weapon" in atype else "#9c5dce" if "ultimate" in atype else "#6888d4"
                    max_purchased = upgrades_map.get(ab_idx, 0)

                    with ui.element("div").style(
                        "display:flex;align-items:center;gap:6px;padding:4px 6px;"
                        "margin:2px 0;min-height:36px;"
                        f"background:#1a2040;border-radius:4px;border-left:3px solid {border_col};"
                    ):
                        # Ability icon
                        if ab.image_url:
                            ui.image(ab.image_url).style(
                                "width:26px;height:26px;object-fit:contain;"
                                "flex-shrink:0;border-radius:3px;"
                            )

                        # Ability name (truncated)
                        ui.label(ab.name).style(
                            "flex:1;font-size:10px;color:#ccc;overflow:hidden;"
                            "text-overflow:ellipsis;white-space:nowrap;min-width:0;"
                        )

                        # Tier upgrade buttons: T1 (1AP), T2 (2AP), T3 (5AP)
                        for tier_num in (1, 2, 3):
                            tier_cost = ABILITY_TIER_COSTS[tier_num - 1]
                            is_active = tier_num <= max_purchased
                            can_buy = (
                                not is_active
                                and tier_num == max_purchased + 1
                                and ap_remaining >= tier_cost
                            )

                            if is_active:
                                btn_bg = border_col
                                btn_text = "#fff"
                                btn_border = border_col
                            elif can_buy:
                                btn_bg = "rgba(255,255,255,0.08)"
                                btn_text = border_col
                                btn_border = border_col
                            else:
                                btn_bg = "rgba(255,255,255,0.03)"
                                btn_text = "#555"
                                btn_border = "#333"

                            def make_toggle(aidx=ab_idx, tn=tier_num, act=is_active, hname=hero_name):
                                def handler(_):
                                    if act:
                                        state.build_ability_upgrades.setdefault(hname, {})[aidx] = tn - 1
                                        if tn - 1 <= 0:
                                            state.build_ability_upgrades.get(hname, {}).pop(aidx, None)
                                    else:
                                        state.build_ability_upgrades.setdefault(hname, {})[aidx] = tn
                                    refresh_build_display()
                                    update_results()
                                return handler

                            with ui.element("div").style(
                                f"display:flex;align-items:center;justify-content:center;"
                                f"cursor:{'pointer' if is_active or can_buy else 'default'};"
                                f"padding:3px 7px;border-radius:4px;min-width:34px;height:24px;"
                                f"background:{btn_bg};border:1px solid {btn_border};"
                                f"transition:all 0.15s;"
                            ).on("click", make_toggle()):
                                ui.label(f"T{tier_num}").style(
                                    f"color:{btn_text};font-size:10px;font-weight:700;"
                                    "pointer-events:none;line-height:1;"
                                )
                                # Tooltip with upgrade description and DPS delta
                                with ui.tooltip().style(
                                    "background:#1a1030;border:1px solid #444;padding:6px 10px;"
                                    "border-radius:6px;font-size:11px;max-width:280px;"
                                    "word-wrap:break-word;"
                                ):
                                    upg = next((u for u in ab.upgrades if u.tier == tier_num), None)
                                    desc_text = upg.description if upg else "No data"

                                    tip_map = dict(cur_ab_map)
                                    tip_map[ab_idx] = list(range(1, tier_num + 1))
                                    tip_spirit_dps = DamageCalculator.hero_total_spirit_dps(
                                        hero, current_spirit=cur_total_spirit,
                                        cooldown_reduction=cur_stats.cooldown_reduction,
                                        spirit_amp=cur_stats.spirit_amp_pct,
                                        resist_shred=cur_stats.spirit_resist_shred,
                                        ability_upgrades=tip_map,
                                    )
                                    td_spirit = tip_spirit_dps - cur_spirit_dps
                                    impact_html = ""
                                    if abs(td_spirit) >= 0.1:
                                        s = "+" if td_spirit > 0 else ""
                                        impact_html = (
                                            f'<div style="margin-top:4px;padding-top:4px;'
                                            f'border-top:1px solid rgba(255,255,255,0.15);'
                                            f'font-size:11px;color:#c090f0;">'
                                            f'{s}{td_spirit:.1f} Spirit DPS</div>'
                                        )
                                    status = "Active" if is_active else f"{tier_cost} AP" if can_buy else f"Locked ({tier_cost} AP)"
                                    ui.html(
                                        f'<div style="color:#e8c252;font-weight:bold;margin-bottom:2px;">'
                                        f'{ab.name} — T{tier_num} ({status})</div>'
                                        f'<div style="color:#d0d0d0;">{desc_text}</div>'
                                        f'{impact_html}'
                                    )

        # Rebuild item slot grid (needs NiceGUI elements for click handlers)
        build_grid.clear()
        with build_grid:
            # Compute grid dimensions: 6 columns, fill top-down then left-to-right
            filled      = len(state.build_items)
            min_slots   = max(12, filled + (6 - filled % 6) % 6)
            total_slots = ((min_slots + 5) // 6) * 6
            num_rows    = total_slots // 6

            # Set column-major flow with explicit row count
            build_grid.style(
                f"grid-template-rows: repeat({num_rows}, 48px); "
                f"grid-auto-flow: column;"
            )

            for i, item in enumerate(state.build_items):
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

            # Empty slots
            for slot_i in range(total_slots - filled):
                abs_pos  = filled + slot_i
                col      = abs_pos // num_rows  # column-major: column = pos // rows
                is_flex  = col >= 4             # last 2 cols are flex
                cls = "bl-slot-empty bl-flex-slot" if is_flex else "bl-slot-empty"
                ui.element("div").classes(cls)

    def _show_breakdown(stat_label: str, entries: list[tuple[str, float]], fmt: str):
        """Open a dialog showing the per-source breakdown for a stat."""
        with ui.dialog() as dlg, ui.card().style(
            "background:#181828; border:1px solid #3a3a5a; min-width:280px; max-width:400px;"
        ):
            ui.label(stat_label).style(
                "font-size:14px; font-weight:700; color:#e8e8e8; margin-bottom:6px;"
            )
            total = 0.0
            for source, val in entries:
                total += val
                if fmt == "pct":
                    val_str = f"+{val:.0%}" if val > 0 else f"{val:.0%}"
                elif fmt == "int":
                    val_str = f"+{int(val)}" if val > 0 else f"{int(val)}"
                else:
                    val_str = f"+{val:.1f}" if val > 0 else f"{val:.1f}"
                with ui.element("div").style(
                    "display:flex; justify-content:space-between; padding:3px 0;"
                    "border-bottom:1px solid rgba(255,255,255,0.06); font-size:12px;"
                ):
                    ui.label(source).style("color:#aaa;")
                    ui.label(val_str).style("color:#e8e8e8; font-variant-numeric:tabular-nums;")
            # Total line
            if len(entries) > 1:
                if fmt == "pct":
                    total_str = f"{total:.0%}"
                elif fmt == "int":
                    total_str = f"{int(total)}"
                else:
                    total_str = f"{total:.1f}"
                with ui.element("div").style(
                    "display:flex; justify-content:space-between; padding:5px 0 2px;"
                    "font-size:12px; font-weight:700;"
                ):
                    ui.label("Total").style("color:#ccc;")
                    ui.label(total_str).style("color:#fff; font-variant-numeric:tabular-nums;")
            ui.button("Close", on_click=dlg.close).props("flat dense").style(
                "margin-top:8px; color:#888;"
            )
        dlg.open()

    def _stat_row(container, label: str, base_val: str, bonus_val: str = "",
                  breakdown: list[tuple[str, float]] | None = None,
                  fmt: str = "f", per_k: float | None = None):
        """Render a stat row. If *breakdown* is provided the row is clickable
        and opens a dialog showing each source.

        *fmt*: ``"f"`` for plain float, ``"pct"`` for percentage formatting.
        *per_k*: value-per-1000-souls to display inline (muted).
        """
        with container:
            cls = "stat-row-click" if breakdown else "stat-row"
            row = ui.element("div").classes(cls)
            with row:
                ui.label(label).classes("stat-row-label")
                ui.label(base_val).classes("stat-row-val")
                if bonus_val:
                    ui.label(bonus_val).classes("stat-row-bonus")
                if per_k is not None:
                    if fmt == "pct" and abs(per_k) >= 0.0005:
                        ui.label(f"{per_k:.1%}/k").classes("stat-row-perk")
                    elif fmt != "pct" and abs(per_k) >= 0.05:
                        ui.label(f"{per_k:.1f}/k").classes("stat-row-perk")
            if breakdown:
                row.on("click", lambda _, lbl=label, bd=breakdown, f=fmt: _show_breakdown(lbl, bd, f))

    def update_results(_=None):
        hero = _heroes.get(bld_hero.value)
        stats_all.clear()
        if not hero:
            return

        build   = Build(items=list(state.build_items))
        boons   = _current_boons()
        ab_upgrades = _current_ability_upgrades_map()
        acc     = (bld_acc.value or 0) / 100.0
        ec = state.enabled_conditionals()
        result  = BuildEngine.evaluate_build(hero, build, boons=boons, accuracy=acc, headshot_rate=0.15, enabled_conditionals=ec)
        base_r  = BuildEngine.evaluate_build(hero, Build(), boons=boons, accuracy=acc, headshot_rate=0.15, enabled_conditionals=ec)
        bs      = result.build_stats
        br      = result.bullet_result
        bbr     = base_r.bullet_result

        # Per-item breakdown for clickable stats
        bd = BuildEngine.stat_breakdown(build, enabled_conditionals=ec)

        def _bd(field: str) -> list[tuple[str, float]] | None:
            """Return breakdown entries for a stat field, or None if empty."""
            return bd.get(field) or None

        def delta(val: float, base: float) -> str:
            d = val - base
            return f"+{d:.0f}" if d > 0.5 else ""

        def deltapct(val: float, base: float) -> str:
            d = val - base
            return f"+{d:.0%}" if abs(d) > 0.001 else ""

        # Compute spirit stats needed for the summary
        boon_spirit = hero.spirit_gain * boons
        total_spirit = int(
            (bs.spirit_power + boon_spirit) * (1.0 + bs.spirit_power_pct)
        )
        spirit_dps = DamageCalculator.hero_total_spirit_dps(
            hero,
            current_spirit=total_spirit,
            cooldown_reduction=bs.cooldown_reduction,
            spirit_amp=bs.spirit_amp_pct,
            resist_shred=bs.spirit_resist_shred,
            ability_upgrades=ab_upgrades,
        )
        bullet_dps   = br.sustained_dps if br and br.raw_dps > 0 else 0.0
        combined_dps = bullet_dps + spirit_dps
        base_hp  = hero.base_hp + hero.hp_gain * boons
        total_hp = result.effective_hp
        total_regen = hero.base_regen + bs.hp_regen

        # Per-1k-soul efficiency
        total_souls = bs.total_cost + int(bld_extra_souls.value or 0)
        base_bullet_dps = bbr.sustained_dps if bbr else 0.0
        base_spirit_dps = DamageCalculator.hero_total_spirit_dps(
            hero, current_spirit=int(boon_spirit),
            cooldown_reduction=0, spirit_amp=0, resist_shred=0,
            ability_upgrades=ab_upgrades,
        )

        def pk(delta: float) -> float | None:
            """Per-1000-souls value, or None if no souls."""
            if total_souls <= 0 or abs(delta) < 0.01:
                return None
            return delta / total_souls * 1000

        with stats_all:
            # ── Summary header ───────────────────────────────────
            with ui.element("div").style(
                "background:#111120; border:1px solid #2a2a4a; border-radius:8px;"
                "padding:8px 10px; margin-bottom:6px;"
                "display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:4px; text-align:center;"
            ):
                for lbl, val, color, delta_val in [
                    ("Gun DPS",    f"{bullet_dps:.1f}",    "#e8a838", bullet_dps - base_bullet_dps),
                    ("Spirit DPS", f"{spirit_dps:.1f}",    "#c090f0", spirit_dps - base_spirit_dps),
                    ("EHP",        f"{total_hp:.0f}",      "#90a8f0", total_hp - base_r.effective_hp),
                    ("Regen",      f"{total_regen:.1f}/s", "#6dd56e", bs.hp_regen),
                ]:
                    pk_val = pk(delta_val)
                    with ui.element("div"):
                        ui.label(lbl).style(f"font-size:9px; color:{color}; font-weight:700;")
                        with ui.element("div").style(
                            "display:flex;align-items:baseline;justify-content:center;gap:4px;"
                        ):
                            ui.label(val).style(f"font-size:14px; color:{color}; font-weight:700;")
                            if pk_val is not None and abs(pk_val) >= 0.05:
                                ui.label(f"{pk_val:.1f}/k").style("font-size:9px; color:#555;")

            # ── Horizontal stat columns ──────────────────────────
            with ui.row().classes("w-full").style(
                "align-items:flex-start; gap:8px;"
            ):
                # ── Weapon column ────────────────────────────────
                weapon_col = ui.column().classes("gap-0").style(
                    "flex:1; min-width:0; overflow:hidden;"
                    "border-right:1px solid rgba(255,255,255,0.06); padding-right:8px;"
                )
                with weapon_col:
                    with ui.element("div").style(
                        "margin-bottom:2px; padding:2px 6px;"
                        "border-left:3px solid #d97e1f; background:rgba(217,126,31,0.08);"
                    ):
                        ui.label("WEAPON").style(
                            "font-size:9px; font-weight:700; color:#e8a838; letter-spacing:0.1em;"
                        )
                if br and br.raw_dps > 0:
                    dps_bd: list[tuple[str, float]] = [("Hero Base DPS", bbr.sustained_dps if bbr else 0)]
                    if bs.weapon_damage_pct or bs.fire_rate_pct:
                        dps_bd.append(("Item Bonus", br.sustained_dps - (bbr.sustained_dps if bbr else 0)))
                    dps_delta = br.sustained_dps - (bbr.sustained_dps if bbr else 0)
                    _stat_row(weapon_col, "Sustained DPS", f"{br.sustained_dps:.1f}",
                        delta(br.sustained_dps, bbr.sustained_dps if bbr else 0),
                        breakdown=dps_bd if len(dps_bd) > 1 else None,
                        per_k=pk(dps_delta))
                    dmg_bd: list[tuple[str, float]] = [("Hero Base", bbr.damage_per_bullet if bbr else 0)]
                    for src, val in (bd.get("weapon_damage_pct") or []):
                        dmg_bd.append((src, val * (bbr.damage_per_bullet if bbr else 0)))
                    dmg_delta = br.damage_per_bullet - (bbr.damage_per_bullet if bbr else 0)
                    _stat_row(weapon_col, "Bullet Damage",
                        f"{br.damage_per_bullet:.1f}",
                        delta(br.damage_per_bullet, bbr.damage_per_bullet if bbr else 0),
                        breakdown=dmg_bd if len(dmg_bd) > 1 else None,
                        per_k=pk(dmg_delta))
                    shots_delta = br.bullets_per_second - (bbr.bullets_per_second if bbr else 0)
                    _stat_row(weapon_col, "Shots/s",
                        f"{br.bullets_per_second:.2f}",
                        breakdown=_bd("fire_rate_pct"),
                        per_k=pk(shots_delta))
                    ammo_bd = []
                    for src, val in (bd.get("ammo_flat") or []):
                        ammo_bd.append((src, val))
                    for src, val in (bd.get("ammo_pct") or []):
                        ammo_bd.append((f"{src} (%)", val))
                    ammo_delta = br.magazine_size - (bbr.magazine_size if bbr else 0)
                    _stat_row(weapon_col, "Ammo",
                        f"{br.magazine_size}",
                        f"+{bs.ammo_flat}" if bs.ammo_flat else (f"+{bs.ammo_pct:.0%}" if bs.ammo_pct else ""),
                        breakdown=ammo_bd or None, fmt="int",
                        per_k=pk(ammo_delta))
                    if bs.bullet_lifesteal:
                        _stat_row(weapon_col, "Bullet Lifesteal", f"{bs.bullet_lifesteal:.0%}",
                                  breakdown=_bd("bullet_lifesteal"), fmt="pct",
                                  per_k=pk(bs.bullet_lifesteal))
                    if bs.bullet_resist_shred:
                        _stat_row(weapon_col, "Bullet Shred", f"{bs.bullet_resist_shred:.0%}",
                                  breakdown=_bd("bullet_resist_shred"), fmt="pct",
                                  per_k=pk(bs.bullet_resist_shred))
                else:
                    with weapon_col:
                        ui.label("No gun data").style("color:#555; font-size:10px; padding:2px 8px;")

                # ── Vitality column ──────────────────────────────
                vitality_col = ui.column().classes("gap-0").style(
                    "flex:1; min-width:0; overflow:hidden;"
                    "border-right:1px solid rgba(255,255,255,0.06); padding-right:8px;"
                )
                with vitality_col:
                    with ui.element("div").style(
                        "margin-bottom:2px; padding:2px 6px;"
                        "border-left:3px solid #4caf50; background:rgba(76,175,80,0.08);"
                    ):
                        ui.label("VITALITY").style(
                            "font-size:9px; font-weight:700; color:#68b45c; letter-spacing:0.1em;"
                        )
                ehp_bd: list[tuple[str, float]] = [("Base HP", hero.base_hp)]
                if boons and hero.hp_gain:
                    ehp_bd.append(("Boon Scaling", hero.hp_gain * boons))
                if bs.base_hp_pct:
                    ehp_bd.append(("Vitality Shop Bonus", base_hp * bs.base_hp_pct))
                for src, val in (bd.get("bonus_hp") or []):
                    ehp_bd.append((src, val))
                for src, val in (bd.get("bullet_shield") or []):
                    ehp_bd.append((f"{src} (B Shield)", val))
                for src, val in (bd.get("spirit_shield") or []):
                    ehp_bd.append((f"{src} (S Shield)", val))
                _stat_row(vitality_col, "Eff HP", f"{total_hp:.0f}",
                    delta(total_hp, base_r.effective_hp),
                    breakdown=ehp_bd,
                    per_k=pk(total_hp - base_r.effective_hp))
                basehp_bd: list[tuple[str, float]] = [("Hero Base", hero.base_hp)]
                if boons and hero.hp_gain:
                    basehp_bd.append(("Boon Scaling", hero.hp_gain * boons))
                _stat_row(vitality_col, "Base HP", f"{base_hp:.0f}",
                    breakdown=basehp_bd if boons else None)
                if bs.bonus_hp:
                    _stat_row(vitality_col, "Bonus HP", f"+{bs.bonus_hp:.0f}",
                              breakdown=_bd("bonus_hp"),
                              per_k=pk(bs.bonus_hp))
                if bs.bullet_shield or bs.spirit_shield:
                    shield_bd = []
                    for src, val in (bd.get("bullet_shield") or []):
                        shield_bd.append((f"{src} (Bullet)", val))
                    for src, val in (bd.get("spirit_shield") or []):
                        shield_bd.append((f"{src} (Spirit)", val))
                    _stat_row(vitality_col, "Shields",
                        f"B:{bs.bullet_shield:.0f} S:{bs.spirit_shield:.0f}",
                        breakdown=shield_bd or None,
                        per_k=pk(bs.bullet_shield + bs.spirit_shield))
                regen_bd: list[tuple[str, float]] = [("Hero Base", hero.base_regen)]
                for src, val in (bd.get("hp_regen") or []):
                    regen_bd.append((src, val))
                _stat_row(vitality_col, "HP Regen", f"+{total_regen:.1f}/s",
                    f"+{bs.hp_regen:.1f}" if bs.hp_regen else "",
                    breakdown=regen_bd if bs.hp_regen else None,
                    per_k=pk(bs.hp_regen))
                if bs.bullet_resist_pct:
                    _stat_row(vitality_col, "Bullet Resist", f"{bs.bullet_resist_pct:.0%}",
                              breakdown=_bd("bullet_resist_pct"), fmt="pct",
                              per_k=pk(bs.bullet_resist_pct))
                if bs.spirit_resist_pct:
                    _stat_row(vitality_col, "Spirit Resist", f"{bs.spirit_resist_pct:.0%}",
                              breakdown=_bd("spirit_resist_pct"), fmt="pct",
                              per_k=pk(bs.spirit_resist_pct))

                # ── Spirit column ────────────────────────────────
                spirit_col = ui.column().classes("gap-0").style(
                    "flex:1; min-width:0; overflow:hidden;"
                )
                with spirit_col:
                    with ui.element("div").style(
                        "margin-bottom:2px; padding:2px 6px;"
                        "border-left:3px solid #9c5dce; background:rgba(156,93,206,0.08);"
                    ):
                        ui.label("SPIRIT").style(
                            "font-size:9px; font-weight:700; color:#c084fc; letter-spacing:0.1em;"
                        )
                sp_bd: list[tuple[str, float]] = []
                for src, val in (bd.get("spirit_power") or []):
                    sp_bd.append((src, val))
                if boons and hero.spirit_gain:
                    sp_bd.append(("Boon Scaling", hero.spirit_gain * boons))
                if bs.spirit_power_pct:
                    pre_mult = bs.spirit_power + boon_spirit
                    sp_bd.append((f"Spirit Power % (+{bs.spirit_power_pct:.0%})", pre_mult * bs.spirit_power_pct))
                sp_delta = total_spirit - int(boon_spirit) if boon_spirit else total_spirit
                _stat_row(spirit_col, "Spirit Power", f"+{total_spirit}" if total_spirit else "0",
                    f"(+{bs.spirit_power:.0f} items)" if bs.spirit_power else "",
                    breakdown=sp_bd or None,
                    per_k=pk(sp_delta))
                if bs.spirit_power_pct:
                    _stat_row(spirit_col, "Spirit Power %", f"+{bs.spirit_power_pct:.0%}",
                              breakdown=_bd("spirit_power_pct"), fmt="pct",
                              per_k=pk(bs.spirit_power_pct))
                if bs.spirit_amp_pct:
                    _stat_row(spirit_col, "Spirit Amp", f"+{bs.spirit_amp_pct:.0%}",
                              breakdown=_bd("spirit_amp_pct"), fmt="pct",
                              per_k=pk(bs.spirit_amp_pct))
                if bs.spirit_lifesteal:
                    _stat_row(spirit_col, "Spirit Lifesteal", f"{bs.spirit_lifesteal:.0%}",
                              breakdown=_bd("spirit_lifesteal"), fmt="pct",
                              per_k=pk(bs.spirit_lifesteal))
                if bs.cooldown_reduction:
                    _stat_row(spirit_col, "CDR", f"{bs.cooldown_reduction:.0%}",
                              breakdown=_bd("cooldown_reduction"), fmt="pct",
                              per_k=pk(bs.cooldown_reduction))
                if bs.spirit_resist_shred:
                    _stat_row(spirit_col, "Spirit Shred", f"{bs.spirit_resist_shred:.0%}",
                              breakdown=_bd("spirit_resist_shred"), fmt="pct",
                              per_k=pk(bs.spirit_resist_shred))
                spirit_dps_delta = spirit_dps - base_spirit_dps
                _stat_row(spirit_col, "Spirit DPS",
                    f"{spirit_dps:.1f}" if spirit_dps > 0 else "-",
                    per_k=pk(spirit_dps_delta))

            # ── Footer: Combined DPS + Total Cost ────────────────
            ui.separator().style("margin:4px 0;")
            combo_bd: list[tuple[str, float]] = []
            if bullet_dps > 0:
                combo_bd.append(("Gun DPS", bullet_dps))
            if spirit_dps > 0:
                combo_bd.append(("Spirit DPS", spirit_dps))
            combined_delta = combined_dps - base_bullet_dps - base_spirit_dps
            _stat_row(stats_all, "Combined DPS", f"{combined_dps:.1f}",
                      breakdown=combo_bd if len(combo_bd) > 1 else None,
                      per_k=pk(combined_delta))
            cost_bd: list[tuple[str, float]] = [(i.name, i.cost) for i in build.items]
            _stat_row(stats_all, "Total Cost", f"${bs.total_cost:,}",
                      breakdown=cost_bd or None, fmt="int")

    # ── Event wiring ──────────────────────────────────────────────
    def _on_hero_boons(_=None):
        state.build_hero_name = bld_hero.value or ""
        state.build_boons = _current_boons()
        refresh_build_display()   # updates hero summary + ability grid too
        update_results()
        if _is_dynamic_sort():
            refresh_shop()

    tier_filter.on_value_change(refresh_shop)
    sort_select.on_value_change(refresh_shop)
    bld_search.on_value_change(refresh_shop)
    bld_hero.on_value_change(_on_hero_boons)
    bld_extra_souls.on_value_change(_on_hero_boons)
    bld_acc.on_value_change(update_results)

    # Initialize shared build state
    state.build_hero_name = bld_hero.value or ""
    state.build_boons = _current_boons()

    refresh_build_display()
    update_results()

    def load_build_from_saved(data: dict):
        """Populate the Build Lab from a saved build dict."""
        hero_name = data.get("hero_name", "")
        item_names = data.get("items", [])
        extra_souls = data.get("extra_souls", 0)
        ability_upg = data.get("ability_upgrades", {})

        # Set hero
        if hero_name in _heroes:
            bld_hero.set_value(hero_name)

        # Clear and load items
        state.build_items.clear()
        for iname in item_names:
            itm = _items.get(iname)
            if itm:
                state.build_items.append(itm)

        # Set extra souls
        bld_extra_souls.set_value(extra_souls)

        # Restore ability upgrades
        state.build_ability_upgrades.clear()
        for h, upgs in ability_upg.items():
            state.build_ability_upgrades[h] = {int(k): v for k, v in upgs.items()}

        state.build_hero_name = hero_name
        state.build_boons = _current_boons()

        refresh_build_display()
        update_results()
        refresh_shop()

        ui.notify(f"Loaded build: {data.get('build_name', 'Unnamed')}", type="positive")

    return refresh_shop, load_build_from_saved


# ── Tab: Saved Builds ────────────────────────────────────────────

_LOCALSTORAGE_KEY = "deadlocksim_saved_builds"


def _classify_build_type(gun_dps: float, spirit_dps: float) -> str:
    """Classify a build as Gun, Spirit, or Hybrid based on DPS split."""
    total = gun_dps + spirit_dps
    if total < 0.01:
        return "Hybrid"
    gun_ratio = gun_dps / total
    if gun_ratio > 0.70:
        return "Gun"
    if gun_ratio < 0.30:
        return "Spirit"
    return "Hybrid"


def _build_saved_builds_tab(state: _PageState, load_build_callback) -> callable:
    """Build the Saved Builds tab. Returns a refresh function."""

    hero_filter = ui.select(
        options=["All Heroes"] + _hero_names,
        value="All Heroes",
        label="Filter by Hero",
    ).classes("w-52")

    builds_container = ui.column().classes("w-full")

    async def _load_saved_builds() -> list[dict]:
        """Read saved builds from browser localStorage."""
        raw = await ui.run_javascript(
            f"localStorage.getItem('{_LOCALSTORAGE_KEY}')"
        )
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    async def _save_builds_to_storage(builds: list[dict]):
        """Write saved builds list to browser localStorage."""
        payload = json.dumps(builds)
        await ui.run_javascript(
            f"localStorage.setItem('{_LOCALSTORAGE_KEY}', {json.dumps(payload)})"
        )

    async def _delete_build(build_id: str):
        """Delete a saved build by its id."""
        builds = await _load_saved_builds()
        builds = [b for b in builds if b.get("id") != build_id]
        await _save_builds_to_storage(builds)
        await refresh_saved_builds()

    async def _load_build_into_editor(build_data: dict):
        """Load a saved build back into the Build Lab tab."""
        load_build_callback(build_data)

    async def refresh_saved_builds(_=None):
        """Refresh the saved builds display."""
        builds = await _load_saved_builds()

        # Apply hero filter
        hero_val = hero_filter.value
        if hero_val and hero_val != "All Heroes":
            builds = [b for b in builds if b.get("hero_name") == hero_val]

        # Sort by saved_at descending (newest first)
        builds.sort(key=lambda b: b.get("saved_at", ""), reverse=True)

        builds_container.clear()
        with builds_container:
            if not builds:
                ui.label("No saved builds yet. Use the Save button in the Build Lab tab.").style(
                    "color:#555; font-size:13px; padding:20px;"
                )
                return

            with ui.element("div").style(
                "display:flex; flex-wrap:wrap; gap:12px; padding:8px 0;"
            ):
                for bld in builds:
                    hero_name = bld.get("hero_name", "Unknown")
                    build_name = bld.get("build_name", "Unnamed Build")
                    build_type = bld.get("build_type", "Hybrid")
                    gun_dps = bld.get("gun_dps", 0)
                    spirit_dps = bld.get("spirit_dps", 0)
                    ehp = bld.get("ehp", 0)
                    total_cost = bld.get("total_cost", 0)
                    item_names = bld.get("items", [])
                    saved_at = bld.get("saved_at", "")
                    build_id = bld.get("id", "")

                    badge_cls = {
                        "Gun": "sb-badge-gun",
                        "Spirit": "sb-badge-spirit",
                        "Hybrid": "sb-badge-hybrid",
                    }.get(build_type, "sb-badge-hybrid")

                    with ui.element("div").classes("sb-card"):
                        # Header: name + type badge
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.label(build_name).style(
                                "font-size:14px;font-weight:700;color:#e8e8e8;"
                                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;"
                            )
                            badge_colors = {
                                "Gun": ("background:#3d2a12;color:#f5a623;border:1px solid #d97e1f;"),
                                "Spirit": ("background:#2a1a3d;color:#c084fc;border:1px solid #9c5dce;"),
                                "Hybrid": ("background:#1a2a3d;color:#60a0e0;border:1px solid #4080c0;"),
                            }
                            ui.label(build_type).style(
                                f"font-size:10px;font-weight:700;letter-spacing:0.06em;"
                                f"padding:2px 8px;border-radius:10px;text-transform:uppercase;"
                                f"{badge_colors.get(build_type, badge_colors['Hybrid'])}"
                            )

                        # Hero name
                        hero = _heroes.get(hero_name)
                        with ui.row().classes("items-center gap-2"):
                            if hero and (hero.icon_url or hero.hero_card_url):
                                icon = hero.icon_url or hero.hero_card_url
                                ui.image(icon).style(
                                    "width:24px;height:24px;border-radius:50%;object-fit:cover;"
                                    "border:1px solid #3a3a3a;"
                                )
                            ui.label(hero_name).style(
                                "font-size:12px;font-weight:600;color:#e8c252;"
                            )
                            ui.label(f"{total_cost:,} souls").style(
                                "font-size:11px;color:#888;"
                            )

                        # Stats row
                        with ui.element("div").style(
                            "display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;text-align:center;"
                            "background:rgba(255,255,255,0.03);border-radius:6px;padding:6px 4px;"
                        ):
                            for s_label, s_val, s_color in [
                                ("GUN DPS", f"{gun_dps:.1f}", "#e8a838"),
                                ("SPIRIT DPS", f"{spirit_dps:.1f}", "#c090f0"),
                                ("EHP", f"{ehp:.0f}", "#90a8f0"),
                            ]:
                                with ui.element("div"):
                                    ui.label(s_label).style(
                                        f"font-size:9px;font-weight:700;color:{s_color};"
                                    )
                                    ui.label(s_val).style(
                                        f"font-size:14px;font-weight:700;color:{s_color};"
                                    )

                        # Item icons
                        if item_names:
                            with ui.element("div").classes("sb-items-row"):
                                for iname in item_names:
                                    itm = _items.get(iname)
                                    if itm:
                                        img = _item_image_url(itm)
                                        colors = _CAT_COLORS.get(itm.category, _CAT_COLORS["weapon"])
                                        ui.image(img).style(
                                            f"width:32px;height:32px;border-radius:4px;"
                                            f"border:1px solid {colors['border']};"
                                            f"object-fit:contain;background:#0a0a14;"
                                        ).tooltip(iname)

                        # Footer: date + actions
                        with ui.element("div").classes("sb-card-footer"):
                            # Format date
                            date_str = ""
                            if saved_at:
                                try:
                                    from datetime import datetime
                                    dt = datetime.fromisoformat(saved_at)
                                    date_str = dt.strftime("%b %d, %Y %H:%M")
                                except (ValueError, TypeError):
                                    date_str = saved_at[:16]
                            ui.label(date_str).style(
                                "font-size:10px;color:#555;"
                            )

                            with ui.row().classes("gap-1"):
                                _bid = build_id
                                _bdata = dict(bld)
                                ui.button(
                                    icon="download",
                                    on_click=lambda _, d=_bdata: _load_build_into_editor(d),
                                ).props("flat dense size=sm").tooltip("Load into Build Lab")
                                ui.button(
                                    icon="delete",
                                    on_click=lambda _, bid=_bid: _delete_build(bid),
                                ).props("flat dense size=sm color=red").tooltip("Delete build")

    hero_filter.on_value_change(refresh_saved_builds)

    return refresh_saved_builds


def _build_settings_tab(state: _PageState) -> None:
    """Settings tab for configuring simulation parameters.

    All settings are stored in the per-client state.sim_settings dict, which is
    read by the Simulation tab and Build tab simulation scoring.
    """
    with ui.row().classes("w-full gap-8 items-start").style("min-height: 600px;"):

        # ══ Column 1: Combat Settings ════════════════════════════
        with ui.column().classes("gap-0").style("width:320px;"):
            ui.element("div").classes("bl-section-header").text = "COMBAT SETTINGS"

            with ui.column().classes("gap-2 mt-2"):
                set_duration = ui.number(
                    label="Sim Duration (s)", value=state.sim_settings["duration"],
                    min=1, max=60, step=1,
                ).classes("w-44")
                ui.separator().style("margin:4px 0;")

                ui.label("Accuracy Model").style("color:#e8a838; font-size:11px; font-weight:700;")
                set_accuracy = ui.number(
                    label="Accuracy %", value=state.sim_settings["accuracy"] * 100,
                    min=0, max=100, step=1,
                ).classes("w-36")
                set_headshot = ui.number(
                    label="Headshot %", value=state.sim_settings["headshot_rate"] * 100,
                    min=0, max=100, step=1,
                ).classes("w-36")
                set_hs_mult = ui.number(
                    label="Headshot Multiplier", value=state.sim_settings["headshot_multiplier"],
                    min=1.0, max=3.0, step=0.05,
                ).classes("w-36")

                ui.separator().style("margin:4px 0;")
                ui.label("Uptime").style("color:#68b45c; font-size:11px; font-weight:700;")
                set_wpn_up = ui.number(
                    label="Weapon Uptime %", value=state.sim_settings["weapon_uptime"] * 100,
                    min=0, max=100, step=5,
                ).classes("w-36")
                set_ability_up = ui.number(
                    label="Ability Uptime %", value=state.sim_settings["ability_uptime"] * 100,
                    min=0, max=200, step=10,
                ).classes("w-36")
                set_active_up = ui.number(
                    label="Active Item Uptime %", value=state.sim_settings["active_item_uptime"] * 100,
                    min=0, max=200, step=10,
                ).classes("w-36")

                ui.separator().style("margin:4px 0;")
                ui.label("Melee").style("color:#c084fc; font-size:11px; font-weight:700;")
                set_melee_weave = ui.checkbox(
                    "Weave light melee between reloads",
                    value=state.sim_settings["weave_melee"],
                )
                set_heavy_reload = ui.checkbox(
                    "Heavy melee during reload",
                    value=state.sim_settings["melee_after_reload"],
                )

                ui.separator().style("margin:4px 0;")
                ui.label("Combat Mode").style("color:#c084fc; font-size:11px; font-weight:700;")
                set_bidirectional = ui.checkbox(
                    "Bidirectional (defender fights back)",
                    value=state.sim_settings["bidirectional"],
                )

                ui.separator().style("margin:8px 0;")
                ui.label("Conditional Item Stats").style(
                    "color:#e8a838; font-size:11px; font-weight:700;"
                )
                ui.label(
                    "Include item stats that require a trigger (on-hit, active use, etc.)"
                ).style("color:#888; font-size:10px; margin-bottom:4px;")
                set_cond_shred = ui.checkbox(
                    "On-hit Shred (resist reduction)",
                    value=state.sim_settings["cond_shred"],
                )
                set_cond_weapon = ui.checkbox(
                    "Weapon bonuses (damage, fire rate, ammo)",
                    value=state.sim_settings["cond_weapon"],
                )
                set_cond_spirit = ui.checkbox(
                    "Spirit bonuses (spirit power, CDR)",
                    value=state.sim_settings["cond_spirit"],
                )
                set_cond_defense = ui.checkbox(
                    "Defensive bonuses (resist, shields, HP)",
                    value=state.sim_settings["cond_defense"],
                )
                set_cond_sustain = ui.checkbox(
                    "Sustain bonuses (lifesteal, regen)",
                    value=state.sim_settings["cond_sustain"],
                )

        # ══ Column 2: Ability Configuration ══════════════════════
        with ui.column().classes("gap-0").style("width:320px;"):
            ui.element("div").classes("bl-section-header").text = "ABILITY CONFIGURATION"

            ui.label(
                "Configure which abilities are used in simulations and their priority order."
            ).style("color:#888; font-size:11px; margin:4px 0 8px;")

            ability_hero_select = ui.select(
                options=_hero_names,
                value=state.build_hero_name or (_hero_names[0] if _hero_names else ""),
                label="Hero",
            ).classes("w-52")

            ability_config_area = ui.column().classes("w-full gap-1 mt-2")

            def _refresh_ability_config(_=None):
                hero = _heroes.get(ability_hero_select.value)
                ability_config_area.clear()
                if not hero or not hero.abilities:
                    return
                hero_name = hero.name
                disabled = state.sim_settings["disabled_abilities"].get(hero_name, set())
                priority = state.sim_settings["ability_priority"].get(hero_name, [])

                with ability_config_area:
                    for i, ability in enumerate(hero.abilities):
                        if not ability.name:
                            continue
                        is_enabled = i not in disabled
                        has_damage = ability.base_damage > 0 and ability.cooldown > 0

                        with ui.card().classes("w-full").style(
                            "background:#161625; border:1px solid #2a2a4a; padding:6px 10px;"
                        ):
                            with ui.row().classes("items-center gap-3 w-full"):
                                if ability.image_url:
                                    ui.image(ability.image_url).style(
                                        "width:32px; height:32px; object-fit:contain; border-radius:4px;"
                                    )

                                with ui.column().classes("flex-grow gap-0"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(ability.name).style(
                                            "color:#e8c252; font-size:12px; font-weight:600;"
                                        )
                                        if ability.ability_type:
                                            atype = ability.ability_type.replace("_", " ").title()
                                            badge_color = (
                                                "purple" if "spirit" in ability.ability_type.lower()
                                                else "orange" if "weapon" in ability.ability_type.lower()
                                                else "blue"
                                            )
                                            ui.badge(atype).props(f"color={badge_color} dense")

                                    stat_parts = []
                                    if ability.base_damage:
                                        stat_parts.append(f"Dmg: {ability.base_damage:.0f}")
                                    if ability.cooldown:
                                        stat_parts.append(f"CD: {ability.cooldown:.1f}s")
                                    if ability.spirit_scaling:
                                        stat_parts.append(f"Scale: {ability.spirit_scaling:.2f}x")
                                    if stat_parts:
                                        ui.label(" | ".join(stat_parts)).style(
                                            "color:#9b74d4; font-size:10px; font-family:monospace;"
                                        )

                                    if not has_damage:
                                        ui.label("(no damage / no cooldown)").style(
                                            "color:#555; font-size:10px; font-style:italic;"
                                        )

                                # Enable/disable toggle
                                def make_toggle(idx: int, hname: str):
                                    def on_toggle(e):
                                        if hname not in state.sim_settings["disabled_abilities"]:
                                            state.sim_settings["disabled_abilities"][hname] = set()
                                        if e.value:
                                            state.sim_settings["disabled_abilities"][hname].discard(idx)
                                        else:
                                            state.sim_settings["disabled_abilities"][hname].add(idx)
                                    return on_toggle

                                ui.switch(
                                    "", value=is_enabled,
                                    on_change=make_toggle(i, hero_name),
                                ).props("dense").style("margin-left:auto;")

                    # Priority order
                    ui.separator().style("margin:8px 0 4px;")
                    ui.label("Ability Cast Order").style(
                        "color:#888; font-size:10px; font-weight:700; text-transform:uppercase;"
                    )
                    ui.label(
                        "Enter ability indices (1-4) in desired cast priority, comma-separated."
                    ).style("color:#555; font-size:10px;")

                    current_order = priority or list(range(len([a for a in hero.abilities if a.name])))
                    order_str = ", ".join(str(x + 1) for x in current_order)

                    def make_order_handler(hname: str):
                        def on_order(e):
                            try:
                                indices = [int(x.strip()) - 1 for x in e.value.split(",") if x.strip()]
                                state.sim_settings["ability_priority"][hname] = indices
                            except ValueError:
                                pass
                        return on_order

                    ui.input(
                        label="Priority (e.g., 1, 3, 2, 4)", value=order_str,
                        on_change=make_order_handler(hero_name),
                    ).classes("w-52")

            ability_hero_select.on_value_change(_refresh_ability_config)
            _refresh_ability_config()

        # ══ Column 3: Custom Item Values ═════════════════════════
        with ui.column().classes("gap-0").style("width:380px;"):
            ui.element("div").classes("bl-section-header").text = "CUSTOM ITEM VALUES"

            ui.label(
                "Assign DPS-equivalent or EHP-equivalent values to utility items. "
                "These values are added when scoring items in the Build tab's "
                "simulation-based sorts."
            ).style("color:#888; font-size:11px; margin:4px 0 8px; line-height:1.5;")

            for item_name, desc in _UTILITY_ITEMS:
                item = _items.get(item_name)
                if not item:
                    continue

                colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
                cur_dps = state.sim_settings["custom_item_dps"].get(item_name, 0.0)
                cur_ehp = state.sim_settings["custom_item_ehp"].get(item_name, 0.0)

                with ui.element("div").style(
                    f"display:flex; align-items:center; gap:8px; padding:4px 6px;"
                    f"border-left:3px solid {colors['border']}; margin:2px 0;"
                    f"background:rgba(255,255,255,0.02); border-radius:0 4px 4px 0;"
                ):
                    # Item icon
                    ui.image(_item_image_url(item)).style(
                        "width:28px; height:28px; object-fit:contain; flex-shrink:0;"
                    )

                    # Name + description
                    with ui.column().classes("gap-0").style("flex:1; min-width:0;"):
                        ui.label(item_name).style(
                            f"color:{colors['text']}; font-size:11px; font-weight:600;"
                            "white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"
                        )
                        ui.label(desc).style(
                            "color:#888; font-size:9px;"
                        )

                    # DPS value input
                    def make_dps_handler(iname: str):
                        def on_change(e):
                            state.sim_settings["custom_item_dps"][iname] = float(e.value or 0)
                        return on_change

                    ui.number(
                        label="DPS", value=cur_dps, min=0, max=500, step=1,
                        on_change=make_dps_handler(item_name),
                    ).classes("w-16").props("dense")

                    # EHP value input
                    def make_ehp_handler(iname: str):
                        def on_change(e):
                            state.sim_settings["custom_item_ehp"][iname] = float(e.value or 0)
                        return on_change

                    ui.number(
                        label="EHP", value=cur_ehp, min=0, max=2000, step=10,
                        on_change=make_ehp_handler(item_name),
                    ).classes("w-16").props("dense")

    # ── Save settings to global state on any change ──────────────
    def _save_setting(key: str, divisor: float = 1.0):
        def handler(e):
            state.sim_settings[key] = (float(e.value or 0)) / divisor
        return handler

    def _save_bool(key: str):
        def handler(e):
            state.sim_settings[key] = bool(e.value)
        return handler

    set_duration.on_value_change(lambda e: state.sim_settings.__setitem__("duration", float(e.value or 15)))
    set_accuracy.on_value_change(_save_setting("accuracy", 100.0))
    set_headshot.on_value_change(_save_setting("headshot_rate", 100.0))
    set_hs_mult.on_value_change(lambda e: state.sim_settings.__setitem__("headshot_multiplier", float(e.value or 1.5)))
    set_wpn_up.on_value_change(_save_setting("weapon_uptime", 100.0))
    set_ability_up.on_value_change(_save_setting("ability_uptime", 100.0))
    set_active_up.on_value_change(_save_setting("active_item_uptime", 100.0))
    set_melee_weave.on_value_change(_save_bool("weave_melee"))
    set_heavy_reload.on_value_change(_save_bool("melee_after_reload"))
    set_bidirectional.on_value_change(_save_bool("bidirectional"))
    set_cond_shred.on_value_change(_save_bool("cond_shred"))
    set_cond_weapon.on_value_change(_save_bool("cond_weapon"))
    set_cond_spirit.on_value_change(_save_bool("cond_spirit"))
    set_cond_defense.on_value_change(_save_bool("cond_defense"))
    set_cond_sustain.on_value_change(_save_bool("cond_sustain"))





# ── Tab: Simulation ─────────────────────────────────────────────


def _build_simulation_tab(state: _PageState) -> None:
    """Simulation tab that uses the Build tab's attacker build.

    The attacker hero + items come from the Build tab (per-client state).
    This tab only configures the defender and simulation settings.
    """
    sim_def_items: list[Item] = []

    with ui.row().classes("w-full gap-6 items-start").style("min-height: 660px;"):

        # ══ LEFT: Configuration panel ════════════════════════════
        with ui.column().style(
            "width:360px; min-width:320px; padding:0 12px 8px 0;"
            "border-right:1px solid #1e1e1e; gap:0;"
        ):
            # ── Attacker (from Build tab) ────────────────────────
            ui.element("div").classes("bl-section-header").text = "ATTACKER (FROM BUILD TAB)"
            sim_atk_summary = ui.column().classes("w-full gap-1")

            def _refresh_atk_summary():
                sim_atk_summary.clear()
                hero = _heroes.get(state.build_hero_name)
                with sim_atk_summary:
                    if hero:
                        _render_hero_summary_with_tooltips(hero)
                        n = len(state.build_items)
                        cost = sum(i.cost for i in state.build_items)
                        ui.label(
                            f"{n} items | {cost:,} souls | {state.build_boons} boons"
                        ).style("color:#888; font-size:11px;")
                        if state.build_items:
                            with ui.element("div").classes("bl-item-grid"):
                                for item in state.build_items:
                                    colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
                                    with ui.element("div").classes("bl-slot-filled").style(
                                        f"border-color:{colors['border']}; background:{colors['bg']};"
                                    ):
                                        ui.image(_item_image_url(item)).style(
                                            "width:36px; height:36px; object-fit:contain;"
                                        )
                                        with ui.tooltip().style(
                                            f"background:{colors['bg']}; border:1px solid {colors['border']};"
                                            "padding:8px 12px; border-radius:6px;"
                                        ):
                                            ui.html(_build_tooltip_html(item))
                    else:
                        ui.label("No hero selected in Build tab").style(
                            "color:#ff6b6b; font-size:12px;"
                        )
                        ui.label("Go to the Build tab to select a hero and items.").style(
                            "color:#888; font-size:11px;"
                        )

            ui.separator().style("margin:8px 0;")

            # ── Defender config ──────────────────────────────────
            ui.element("div").classes("bl-section-header").text = "DEFENDER"
            with ui.row().classes("items-end gap-2 flex-wrap"):
                sim_def_hero = ui.select(
                    options=_hero_names,
                    value=_hero_names[1] if len(_hero_names) > 1 else (_hero_names[0] if _hero_names else ""),
                    label="Hero",
                ).classes("w-44")
                sim_def_boons = ui.number(
                    label="Boons", value=10, min=0, max=50, step=1,
                ).classes("w-20")

            sim_def_grid = ui.element("div").classes("bl-item-grid")
            sim_def_label = ui.label("0 items").style(
                "color:#888; font-size:10px; margin-top:2px;"
            )

            with ui.row().classes("items-end gap-2 flex-wrap mt-1"):
                sim_def_item_pick = ui.select(
                    options=_item_names, label="Add Item",
                    with_input=True,
                ).classes("w-52")
                ui.button("+", on_click=lambda: _add_def_item()).props("dense").classes("mt-auto")
                ui.button("Clear", on_click=lambda: _clear_def()).props("dense flat").style(
                    "font-size:10px; color:#888;"
                )

            ui.separator().style("margin:8px 0;")

            # ── Settings reference ───────────────────────────────
            with ui.element("div").style(
                "background:#111820; border:1px solid #2a3a4a; border-radius:6px;"
                "padding:8px 10px;"
            ):
                ui.label("Settings from Settings tab").style(
                    "color:#e8c252; font-size:10px; font-weight:700;"
                )
                sim_settings_summary = ui.label("").style(
                    "color:#888; font-size:10px; line-height:1.5;"
                )

                def _refresh_settings_summary():
                    s = state.sim_settings
                    bidir_tag = " | Bidirectional: ON" if s['bidirectional'] else ""
                    sim_settings_summary.text = (
                        f"Duration: {s['duration']:.0f}s | "
                        f"Accuracy: {s['accuracy']:.0%} | "
                        f"Headshot: {s['headshot_rate']:.0%} | "
                        f"Wpn Up: {s['weapon_uptime']:.0%}\n"
                        f"Ability Up: {s['ability_uptime']:.0%} | "
                        f"Melee weave: {'on' if s['weave_melee'] else 'off'} | "
                        f"Heavy reload: {'on' if s['melee_after_reload'] else 'off'}"
                        f"{bidir_tag}"
                    )

            ui.separator().style("margin:8px 0;")
            sim_run_btn = ui.button("Run Simulation", icon="play_arrow").classes(
                "w-full"
            ).style("background:#1a5a1a; color:#fff;")

        # ══ RIGHT: Results panel ═════════════════════════════════
        with ui.column().classes("flex-grow gap-0").style("min-width:0; overflow:hidden;"):
            ui.element("div").classes("bl-section-header").text = "SIMULATION RESULTS"
            sim_results_area = ui.column().classes("w-full gap-4")

    # ── Helper functions ─────────────────────────────────────────

    def _render_def_grid():
        sim_def_grid.clear()
        with sim_def_grid:
            for i, item in enumerate(sim_def_items):
                colors = _CAT_COLORS.get(item.category, _CAT_COLORS["weapon"])
                with ui.element("div").classes("bl-slot-filled").style(
                    f"border-color:{colors['border']}; background:{colors['bg']};"
                ).on("click", lambda _, idx=i: _remove_def_item(idx)):
                    ui.image(_item_image_url(item)).style(
                        "width:40px; height:40px; object-fit:contain;"
                    )
                    ui.element("div").classes("bl-slot-cost").style(
                        f"color:{colors['text']};"
                    ).text = f"{item.cost:,}"
                    with ui.tooltip().style(
                        f"background:{colors['bg']}; border:1px solid {colors['border']};"
                        "padding:8px 12px; border-radius:6px;"
                    ):
                        ui.html(_build_tooltip_html(item))
            filled = len(sim_def_items)
            for _ in range(max(0, 6 - filled)):
                ui.element("div").classes("bl-slot-empty")

    def _add_def_item():
        name = sim_def_item_pick.value
        item = _items.get(name)
        if item and not any(i.name == name for i in sim_def_items):
            sim_def_items.append(item)
            _render_def_grid()
            sim_def_label.text = f"{len(sim_def_items)} items ({sum(i.cost for i in sim_def_items):,} souls)"

    def _remove_def_item(idx: int):
        if 0 <= idx < len(sim_def_items):
            sim_def_items.pop(idx)
            _render_def_grid()
            sim_def_label.text = f"{len(sim_def_items)} items ({sum(i.cost for i in sim_def_items):,} souls)"

    def _clear_def():
        sim_def_items.clear()
        _render_def_grid()
        sim_def_label.text = "0 items"

    def _run_sim():
        atk_hero = _heroes.get(state.build_hero_name)
        def_hero = _heroes.get(sim_def_hero.value)
        if not atk_hero:
            sim_results_area.clear()
            with sim_results_area:
                ui.label("No attacker hero selected.").style("color:#ff6b6b;")
                ui.label("Go to the Build tab to select a hero and items first.").style(
                    "color:#888; font-size:12px;"
                )
            return
        if not def_hero:
            return

        settings = state.get_sim_settings(
            atk_boons=state.build_boons,
            def_boons=int(sim_def_boons.value or 0),
        )
        ability_schedule = state.get_ability_schedule(atk_hero.name, atk_hero)
        ability_upgrades_map = state.get_ability_upgrades_map()

        config = SimConfig(
            attacker=atk_hero,
            attacker_build=Build(items=list(state.build_items)),
            defender=def_hero,
            defender_build=Build(items=list(sim_def_items)),
            settings=settings,
            ability_schedule=ability_schedule,
            attacker_ability_upgrades=ability_upgrades_map,
        )

        result = CombatSimulator.run(config)
        _render_results(result, atk_hero, def_hero)

    def _render_results(result: SimResult, atk_hero: HeroStats, def_hero: HeroStats):
        sim_results_area.clear()
        with sim_results_area:
            is_bidir = result.winner is not None or result.defender_dps is not None

            # ── Matchup header ───────────────────────────────────
            mode_tag = " [BIDIRECTIONAL]" if is_bidir else ""
            ui.label(
                f"{atk_hero.name} ({len(state.build_items)} items, {state.build_boons} boons) vs "
                f"{def_hero.name} ({len(sim_def_items)} items){mode_tag}"
            ).style("color:#e8c252; font-size:12px; font-weight:600; margin-bottom:4px;")

            # ── Winner banner (bidirectional only) ───────────────
            if is_bidir:
                if result.winner == "a":
                    w_text = f"{atk_hero.name} WINS at {result.kill_time:.2f}s"
                    w_color = "#7aff7a"
                elif result.winner == "b":
                    w_text = f"{def_hero.name} WINS at {result.defender_kill_time:.2f}s"
                    w_color = "#ff6b6b"
                else:
                    w_text = f"DRAW — neither died in {result.total_duration:.1f}s"
                    w_color = "#e8c252"

                with ui.element("div").style(
                    f"background:#111820; border:2px solid {w_color}; border-radius:10px;"
                    "padding:10px 16px; margin-bottom:8px; text-align:center;"
                ):
                    ui.element("div").style(
                        f"font-size:18px; color:{w_color}; font-weight:700;"
                    ).text = w_text
                    hp_parts = []
                    if result.attacker_hp_remaining is not None:
                        hp_parts.append(f"{atk_hero.name}: {result.attacker_hp_remaining:.0f} HP left")
                    hp_parts.append(f"{def_hero.name}: {result.target_hp_remaining:.0f} HP left")
                    ui.element("div").style(
                        "font-size:11px; color:#888; margin-top:2px;"
                    ).text = " | ".join(hp_parts)

            # ── Side-by-side or single view ──────────────────────
            if is_bidir:
                with ui.row().classes("w-full gap-6 items-start"):
                    with ui.column().classes("flex-grow gap-0").style("flex:1; min-width:0;"):
                        _render_side_stats(
                            result, atk_hero.name,
                            result.overall_dps, result.total_damage,
                            result.bullet_damage, result.spirit_damage, result.melee_damage,
                            result.damage_by_source, result.dps_by_source,
                            result.bullets_fired, result.headshots, result.reloads,
                            result.procs_triggered, result.kill_time,
                            result.total_duration, "a",
                        )
                    with ui.column().classes("flex-grow gap-0").style("flex:1; min-width:0;"):
                        _render_side_stats(
                            result, def_hero.name,
                            result.defender_dps or 0, result.defender_total_damage or 0,
                            result.defender_bullet_damage or 0, result.defender_spirit_damage or 0,
                            result.defender_melee_damage or 0,
                            result.defender_damage_by_source or {}, result.defender_dps_by_source or {},
                            result.defender_bullets_fired or 0, result.defender_headshots or 0,
                            result.defender_reloads or 0,
                            result.defender_procs_triggered or {}, result.defender_kill_time,
                            result.total_duration, "b",
                        )
            else:
                # ── Unidirectional (original layout) ──────────────
                kill_text = (
                    f"Target killed at {result.kill_time:.2f}s"
                    if result.kill_time is not None
                    else f"Target survived ({result.target_hp_remaining:.0f} HP left)"
                )
                kill_color = "#7aff7a" if result.kill_time is not None else "#ff6b6b"

                with ui.element("div").style(
                    "background:#111820; border:1px solid #2a3a4a; border-radius:10px;"
                    "padding:12px 16px; margin-bottom:8px;"
                    "display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; text-align:center;"
                ):
                    for lbl, val, color in [
                        ("OVERALL DPS", f"{result.overall_dps:.1f}", "#90e890"),
                        ("TOTAL DAMAGE", f"{result.total_damage:.0f}", "#90a8f0"),
                        ("DURATION", f"{result.total_duration:.1f}s", "#e8c252"),
                    ]:
                        with ui.element("div"):
                            ui.element("div").style("font-size:9px; color:#888; font-weight:700;").text = lbl
                            ui.element("div").style(f"font-size:18px; color:{color}; font-weight:700;").text = val

                ui.label(kill_text).style(f"color:{kill_color}; font-size:13px; font-weight:600;")

                _render_side_stats(
                    result, atk_hero.name,
                    result.overall_dps, result.total_damage,
                    result.bullet_damage, result.spirit_damage, result.melee_damage,
                    result.damage_by_source, result.dps_by_source,
                    result.bullets_fired, result.headshots, result.reloads,
                    result.procs_triggered, result.kill_time,
                    result.total_duration, "a",
                )

            # ── DPS Timeline chart ───────────────────────────────
            ui.separator()
            ui.label("DPS Over Time").classes("text-sm font-bold text-sky-400")

            bucket_size = 0.5
            max_t = result.total_duration
            n_buckets = max(1, int(max_t / bucket_size) + 1)
            time_labels = [round(i * bucket_size, 1) for i in range(n_buckets)]

            source_buckets: dict[str, list[float]] = {}
            source_dtype: dict[str, str] = {}
            source_cid: dict[str, str] = {}
            for entry in result.timeline:
                lbl = f"{entry.source} ({entry.combatant.upper()})" if is_bidir else entry.source
                idx = min(int(entry.time / bucket_size), n_buckets - 1)
                if lbl not in source_buckets:
                    source_buckets[lbl] = [0.0] * n_buckets
                    source_dtype[lbl] = entry.damage_type
                    source_cid[lbl] = entry.combatant
                source_buckets[lbl][idx] += entry.damage

            _dtype_colors_a = {
                "bullet": "#f59e0b", "spirit": "#a855f7", "melee": "#22c55e",
            }
            _dtype_colors_b = {
                "bullet": "#e07020", "spirit": "#7040c0", "melee": "#108040",
            }

            chart_series = []
            for source in sorted(source_buckets, key=lambda s: (source_cid.get(s, "a"), source_dtype.get(s, ""), s)):
                cid = source_cid.get(source, "a")
                dtype = source_dtype.get(source, "spirit")
                colors = _dtype_colors_a if cid == "a" else _dtype_colors_b
                color = colors.get(dtype, "#4080ff")
                stack = "dps_a" if cid == "a" else "dps_b"
                dps_vals = [round(v / bucket_size, 1) for v in source_buckets[source]]
                chart_series.append({
                    "name": source,
                    "type": "bar",
                    "stack": stack,
                    "data": dps_vals,
                    "itemStyle": {"color": color},
                    "emphasis": {"focus": "series"},
                })

            ui.echart({
                "tooltip": {
                    "trigger": "axis",
                    "axisPointer": {"type": "shadow"},
                },
                "legend": {
                    "data": [s["name"] for s in chart_series],
                    "textStyle": {"color": "#ccc"},
                    "type": "scroll",
                    "bottom": 0,
                },
                "grid": {"bottom": 60},
                "xAxis": {
                    "type": "category", "name": "Time (s)",
                    "data": time_labels,
                    "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"},
                },
                "yAxis": {
                    "type": "value", "name": "DPS",
                    "nameTextStyle": {"color": "#ccc"}, "axisLabel": {"color": "#ccc"},
                },
                "series": chart_series,
                "backgroundColor": "transparent",
            }).classes("w-full h-72")

    def _render_side_stats(
        result: SimResult, hero_name: str,
        dps: float, total_dmg: float,
        bullet_dmg: float, spirit_dmg: float, melee_dmg: float,
        dmg_by_source: dict, dps_by_source: dict,
        bullets: int, headshots: int, reloads: int,
        procs: dict, kill_time: float | None,
        duration: float, cid: str,
    ):
        """Render one combatant's stats (used by both uni and bidirectional)."""
        side_color = "#90e890" if cid == "a" else "#e09050"
        ui.label(hero_name).style(
            f"color:{side_color}; font-size:14px; font-weight:700; margin-bottom:4px;"
        )

        with ui.element("div").style(
            "background:#111820; border:1px solid #2a3a4a; border-radius:8px;"
            "padding:8px 12px; margin-bottom:6px;"
            "display:grid; grid-template-columns:1fr 1fr; gap:4px; text-align:center;"
        ):
            for lbl, val, color in [
                ("DPS", f"{dps:.1f}", side_color),
                ("TOTAL", f"{total_dmg:.0f}", "#90a8f0"),
            ]:
                with ui.element("div"):
                    ui.element("div").style("font-size:9px; color:#888; font-weight:700;").text = lbl
                    ui.element("div").style(f"font-size:16px; color:{color}; font-weight:700;").text = val

        if kill_time is not None:
            ui.label(f"Killed target at {kill_time:.2f}s").style(
                "color:#7aff7a; font-size:11px; font-weight:600;"
            )

        # Damage by type pie
        type_data = []
        if bullet_dmg > 0:
            type_data.append({"name": "Bullet", "value": round(bullet_dmg, 1)})
        if spirit_dmg > 0:
            type_data.append({"name": "Spirit", "value": round(spirit_dmg, 1)})
        if melee_dmg > 0:
            type_data.append({"name": "Melee", "value": round(melee_dmg, 1)})
        if type_data:
            ui.echart({
                "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
                "series": [{
                    "type": "pie", "radius": ["30%", "60%"],
                    "data": type_data,
                    "label": {"color": "#ccc", "fontSize": 10},
                    "itemStyle": {"borderRadius": 4, "borderColor": "#111", "borderWidth": 2},
                }],
                "color": ["#e8a838", "#c084fc", "#68b45c"],
                "backgroundColor": "transparent",
            }).classes("w-full h-36")

        # Damage by source table
        src_rows = []
        for src, dmg in sorted(dmg_by_source.items(), key=lambda x: -x[1]):
            s_dps = dps_by_source.get(src, 0)
            pct = (dmg / total_dmg * 100) if total_dmg > 0 else 0
            src_rows.append({
                "source": src, "damage": f"{dmg:.0f}",
                "dps": f"{s_dps:.1f}", "pct": f"{pct:.1f}%",
            })
        src_cols = [
            {"name": "source", "label": "Source", "field": "source", "align": "left"},
            {"name": "damage", "label": "Damage", "field": "damage", "align": "right"},
            {"name": "dps", "label": "DPS", "field": "dps", "align": "right"},
            {"name": "pct", "label": "%", "field": "pct", "align": "right"},
        ]
        ui.table(columns=src_cols, rows=src_rows, row_key="source").classes(
            "w-full"
        ).props("dense flat bordered")

        # Combat stats
        ui.separator().style("margin:4px 0;")
        stat_rows = [
            {"stat": "Bullets", "value": str(bullets)},
            {"stat": "Headshots", "value": str(headshots)},
            {"stat": "Reloads", "value": str(reloads)},
        ]
        for pname, count in sorted(procs.items()):
            stat_rows.append({"stat": f"{pname} procs", "value": str(count)})
        stat_cols = [
            {"name": "stat", "label": "Stat", "field": "stat", "align": "left"},
            {"name": "value", "label": "Value", "field": "value", "align": "right"},
        ]
        ui.table(columns=stat_cols, rows=stat_rows, row_key="stat").classes(
            "w-full"
        ).props("dense flat bordered")

    sim_run_btn.on("click", lambda: (_refresh_atk_summary(), _refresh_settings_summary(), _run_sim()))
    _render_def_grid()
    _refresh_atk_summary()
    _refresh_settings_summary()


# ── Simulation-based item scoring for Build tab ────────────────


def _sim_item_scores(
    state: _PageState,
    hero: HeroStats,
    current_items: list[Item],
    candidates: list[Item],
    boons: int,
    mode: str = "gun",
) -> dict[str, dict[str, float]]:
    """Score each candidate item by running a quick simulation.

    Modes: "gun" (weapon-only), "spirit" (abilities on CD), "hybrid" (combined).
    """
    dummy = HeroStats(name="Dummy Target", base_hp=2500, base_regen=0)

    # Build settings from global config, override uptime per mode
    base_settings = state.get_sim_settings(atk_boons=boons, def_boons=0)
    if mode == "gun":
        base_settings.ability_uptime = 0.0
    elif mode == "spirit":
        base_settings.weapon_uptime = 0.0
        base_settings.ability_uptime = 1.0
    # Use shorter duration for scoring (performance)
    base_settings.duration = min(base_settings.duration, 10.0)

    ability_schedule = state.get_ability_schedule(hero.name, hero)
    ability_upgrades_map = state.get_ability_upgrades_map()

    base_config = SimConfig(
        attacker=hero,
        attacker_build=Build(items=list(current_items)),
        defender=dummy,
        settings=base_settings,
        ability_schedule=list(ability_schedule),
        attacker_ability_upgrades=ability_upgrades_map,
    )
    base_result = CombatSimulator.run(base_config)
    base_dps = base_result.overall_dps

    # EHP baseline (defender perspective)
    base_build_stats = BuildEngine.aggregate_stats(Build(items=list(current_items)), enabled_conditionals=state.enabled_conditionals())
    base_hp = (hero.base_hp + hero.hp_gain * boons) * (1.0 + base_build_stats.base_hp_pct)
    base_ehp = base_hp + base_build_stats.bonus_hp + base_build_stats.bullet_shield + base_build_stats.spirit_shield
    if base_build_stats.bullet_resist_pct > 0:
        base_ehp /= (1.0 - min(0.9, base_build_stats.bullet_resist_pct))
    if base_build_stats.spirit_resist_pct > 0:
        spirit_ehp_mult = 1.0 / (1.0 - min(0.9, base_build_stats.spirit_resist_pct))
        base_ehp = base_ehp * (0.5 + 0.5 * spirit_ehp_mult)

    custom_dps_values = state.sim_settings.get("custom_item_dps", {})
    custom_ehp_values = state.sim_settings.get("custom_item_ehp", {})

    scores: dict[str, dict[str, float]] = {}

    for item in candidates:
        test_items = list(current_items) + [item]

        # Sim DPS
        test_config = SimConfig(
            attacker=hero,
            attacker_build=Build(items=test_items),
            defender=dummy,
            settings=base_settings,
            ability_schedule=list(ability_schedule),
            attacker_ability_upgrades=ability_upgrades_map,
        )
        test_result = CombatSimulator.run(test_config)
        test_dps = test_result.overall_dps

        # EHP
        test_stats = BuildEngine.aggregate_stats(Build(items=test_items), enabled_conditionals=state.enabled_conditionals())
        test_hp = (hero.base_hp + hero.hp_gain * boons) * (1.0 + test_stats.base_hp_pct)
        test_ehp = test_hp + test_stats.bonus_hp + test_stats.bullet_shield + test_stats.spirit_shield
        if test_stats.bullet_resist_pct > 0:
            test_ehp /= (1.0 - min(0.9, test_stats.bullet_resist_pct))
        if test_stats.spirit_resist_pct > 0:
            spirit_ehp_mult = 1.0 / (1.0 - min(0.9, test_stats.spirit_resist_pct))
            test_ehp = test_ehp * (0.5 + 0.5 * spirit_ehp_mult)

        cost = item.cost or 1
        dps_delta = test_dps - base_dps
        ehp_delta = test_ehp - base_ehp

        # Add custom DPS/EHP values from Settings tab
        dps_delta += custom_dps_values.get(item.name, 0.0)
        ehp_delta += custom_ehp_values.get(item.name, 0.0)

        scores[item.name] = {
            "sim_dps_delta": dps_delta,
            "sim_ehp_delta": ehp_delta,
            "sim_dps": test_dps,
            "sim_ehp": test_ehp,
            "sim_dps_per_soul": dps_delta / cost,
            "sim_ehp_per_soul": ehp_delta / cost,
        }

    return scores


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
        state = _PageState()
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

            # ── Bug Report / Suggestion button ────────────────────
            def _open_feedback_dialog():
                feedback_category = {"value": "Bug"}
                feedback_text = {"value": ""}

                with ui.dialog() as dlg, ui.card().classes("w-96"):
                    ui.label("Bug Report / Suggestion").classes("text-lg font-bold text-amber-400")
                    cat_select = ui.select(
                        ["Bug", "Suggestion", "Other"],
                        value="Bug",
                        label="Category",
                        on_change=lambda e: feedback_category.update(value=e.value),
                    ).classes("w-full")
                    text_area = ui.textarea(
                        label="Describe the issue or suggestion",
                        placeholder="What happened? What did you expect?",
                        on_change=lambda e: feedback_text.update(value=e.value),
                    ).classes("w-full").props("rows=5")

                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("Cancel", on_click=dlg.close).props("flat")

                        def _submit():
                            body = feedback_text["value"].strip()
                            cat = feedback_category["value"]
                            if not body:
                                ui.notification("Please enter a description.", type="warning")
                                return
                            # Log with [USER_FEEDBACK] tag for easy searching in Azure
                            log.warning(
                                "[USER_FEEDBACK] category=%s | %s",
                                cat, body,
                            )
                            dlg.close()
                            ui.notification(
                                "Thank you! Your feedback has been recorded.",
                                type="positive",
                                timeout=4,
                            )

                        ui.button("Submit", icon="send", on_click=_submit).props("color=amber")

                dlg.open()

            ui.button("Bug Report", icon="bug_report", on_click=_open_feedback_dialog).props("flat").classes("text-orange-400")

        ui.label(f"{len(_heroes)} heroes, {len(_items)} items loaded").classes("text-gray-500")
        ui.separator()

        with ui.tabs().classes("w-full") as tabs:
            tab_build = ui.tab("Build")
            tab_saved = ui.tab("Saved Builds")
            tab_sim = ui.tab("Simulation")
            tab_settings = ui.tab("Settings")
            tab_hero = ui.tab("Hero Stats")

        with ui.tab_panels(tabs, value=tab_build).classes("w-full") as panels:
            with ui.tab_panel(tab_build):
                _build_refresh_shop, _load_build_fn = _build_eval_tab(state)
            with ui.tab_panel(tab_saved):
                _refresh_saved = _build_saved_builds_tab(state, 
                    load_build_callback=lambda data: (
                        _load_build_fn(data),
                        tabs.set_value("Build"),
                    ),
                )
            with ui.tab_panel(tab_sim):
                _build_simulation_tab(state)
            with ui.tab_panel(tab_settings):
                _build_settings_tab(state)
            with ui.tab_panel(tab_hero):
                _build_hero_stats_tab()

        async def _on_tab_change(e):
            log.debug("Tab changed to: %s", e.value)
            if e.value == "Saved Builds":
                await _refresh_saved()

        tabs.on_value_change(_on_tab_change)

        # Load the item shop on startup since Build is the default tab
        _build_refresh_shop()

    port = int(os.environ.get("PORT", 8080))
    log.info("Starting NiceGUI server on 0.0.0.0:%d", port)
    ui.run(title="Deadlock Combat Simulator", host="0.0.0.0", port=port, show=False, reconnect_timeout=30.0)


if __name__ in {"__main__", "__mp_main__"}:
    run_gui()
