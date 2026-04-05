"""MCP server exposing the Deadlock Simulator engine as tools.

Run with:  python -m deadlock_sim.mcp_server
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from .data import load_heroes, load_items
from .engine.builds import BuildEngine, BuildOptimizer
from .engine.comparison import ComparisonEngine
from .engine.damage import DamageCalculator
from .engine.scaling import ScalingCalculator
from .engine.ttk import TTKCalculator
from .logging_config import setup_logging
from .models import Build, CombatConfig

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

setup_logging()
log = logging.getLogger(__name__)

mcp = FastMCP("Deadlock Simulator")

log.info("MCP server starting — loading data")
_heroes = load_heroes()
_items = load_items()
log.info("MCP server ready: %d heroes, %d items", len(_heroes), len(_items))


def _hero_names() -> list[str]:
    return sorted(_heroes.keys())


def _item_names() -> list[str]:
    return sorted(_items.keys())


def _d(obj: object) -> dict:
    """Convert a dataclass instance to a plain dict."""
    return asdict(obj)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Hero tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_heroes() -> list[str]:
    """List all available hero names."""
    return _hero_names()


@mcp.tool()
def get_hero(name: str) -> dict:
    """Get full stats for a hero by name (case-insensitive fuzzy match).

    Returns hero stats including gun data, survivability, scaling,
    abilities, images, and lore.
    """
    hero = _resolve_hero(name)
    if hero is None:
        return {"error": f"Hero '{name}' not found. Available: {_hero_names()}"}
    d = _d(hero)
    # Summarise abilities concisely
    d["abilities"] = [
        {
            "name": a.name,
            "type": a.ability_type,
            "description": a.description[:200] if a.description else "",
            "base_damage": a.base_damage,
            "cooldown": a.cooldown,
            "duration": a.duration,
            "spirit_scaling": a.spirit_scaling,
            "image_url": a.image_url,
            "upgrades": [{"tier": u.tier, "description": u.description} for u in a.upgrades],
        }
        for a in hero.abilities
    ]
    return d


@mcp.tool()
def get_hero_abilities(name: str) -> list[dict]:
    """Get detailed ability information for a hero."""
    hero = _resolve_hero(name)
    if hero is None:
        return [{"error": f"Hero '{name}' not found."}]
    return [
        {
            "name": a.name,
            "type": a.ability_type,
            "description": a.description,
            "base_damage": a.base_damage,
            "cooldown": a.cooldown,
            "duration": a.duration,
            "spirit_scaling": a.spirit_scaling,
            "image_url": a.image_url,
            "upgrades": [{"tier": u.tier, "description": u.description} for u in a.upgrades],
            "properties": a.properties,
        }
        for a in hero.abilities
    ]


# ---------------------------------------------------------------------------
# Item tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_items(category: str = "", tier: int = 0) -> list[dict]:
    """List items, optionally filtered by category (weapon/vitality/spirit) and tier (1-4).

    Returns name, category, tier, and cost for each matching item.
    """
    results = []
    for item in _items.values():
        if category and item.category != category.lower():
            continue
        if tier and item.tier != tier:
            continue
        results.append({
            "name": item.name,
            "category": item.category,
            "tier": item.tier,
            "cost": item.cost,
        })
    results.sort(key=lambda x: (x["category"], x["tier"], x["cost"]))
    return results


@mcp.tool()
def get_item(name: str) -> dict:
    """Get full details for an item by name (case-insensitive fuzzy match)."""
    item = _resolve_item(name)
    if item is None:
        return {"error": f"Item '{name}' not found."}
    return _d(item)


# ---------------------------------------------------------------------------
# Damage calculation tools
# ---------------------------------------------------------------------------


@mcp.tool()
def calculate_bullet_dps(
    hero_name: str,
    boons: int = 0,
    weapon_damage_bonus: float = 0.0,
    fire_rate_bonus: float = 0.0,
    enemy_bullet_resist: float = 0.0,
    shred: float = 0.0,
    accuracy: float = 1.0,
    headshot_rate: float = 0.0,
) -> dict:
    """Calculate bullet DPS for a hero with optional combat modifiers.

    Returns damage per bullet, fire rate, raw DPS, final DPS (after resist),
    magazine stats, and shred/resist breakdown.
    """
    hero = _resolve_hero(hero_name)
    if hero is None:
        return {"error": f"Hero '{hero_name}' not found."}

    config = CombatConfig(
        boons=boons,
        weapon_damage_bonus=weapon_damage_bonus,
        fire_rate_bonus=fire_rate_bonus,
        shred=[shred] if shred > 0 else [],
        accuracy=accuracy,
        headshot_rate=headshot_rate,
        enemy_bullet_resist=enemy_bullet_resist,
    )
    result = DamageCalculator.calculate_bullet(hero, config)
    d = _d(result)
    d["realistic_dps"] = DamageCalculator.dps_with_accuracy(hero, config)
    return d


@mcp.tool()
def calculate_spirit_dps(
    hero_name: str,
    current_spirit: int = 0,
    cooldown_reduction: float = 0.0,
    spirit_amp: float = 0.0,
    enemy_spirit_resist: float = 0.0,
    resist_shred: float = 0.0,
) -> dict:
    """Calculate total spirit DPS from all of a hero's damaging abilities.

    Also returns per-ability DPS breakdown.
    """
    hero = _resolve_hero(hero_name)
    if hero is None:
        return {"error": f"Hero '{hero_name}' not found."}

    total = DamageCalculator.hero_total_spirit_dps(
        hero,
        current_spirit=current_spirit,
        cooldown_reduction=cooldown_reduction,
        spirit_amp=spirit_amp,
        enemy_spirit_resist=enemy_spirit_resist,
        resist_shred=resist_shred,
    )

    per_ability = []
    for ability in hero.abilities:
        if ability.base_damage <= 0:
            continue
        r = DamageCalculator.calculate_ability_spirit_dps(
            ability,
            current_spirit=current_spirit,
            cooldown_reduction=cooldown_reduction,
            spirit_amp=spirit_amp,
            enemy_spirit_resist=enemy_spirit_resist,
            resist_shred=resist_shred,
        )
        per_ability.append({
            "ability": ability.name,
            "raw_damage": r.raw_damage,
            "modified_damage": r.modified_damage,
            "dps": r.dps,
        })

    return {
        "hero": hero.name,
        "total_spirit_dps": total,
        "abilities": per_ability,
    }


# ---------------------------------------------------------------------------
# TTK tool
# ---------------------------------------------------------------------------


@mcp.tool()
def calculate_ttk(
    attacker_name: str,
    defender_name: str,
    boons: int = 0,
    weapon_damage_bonus: float = 0.0,
    fire_rate_bonus: float = 0.0,
    accuracy: float = 0.7,
    headshot_rate: float = 0.15,
    enemy_bullet_resist: float = 0.0,
) -> dict:
    """Calculate time-to-kill for attacker vs defender.

    Returns ideal TTK, realistic TTK (with accuracy/headshots),
    magazines needed, and DPS figures.
    """
    attacker = _resolve_hero(attacker_name)
    defender = _resolve_hero(defender_name)
    if attacker is None:
        return {"error": f"Attacker '{attacker_name}' not found."}
    if defender is None:
        return {"error": f"Defender '{defender_name}' not found."}

    config = CombatConfig(
        boons=boons,
        weapon_damage_bonus=weapon_damage_bonus,
        fire_rate_bonus=fire_rate_bonus,
        accuracy=accuracy,
        headshot_rate=headshot_rate,
        enemy_bullet_resist=enemy_bullet_resist,
    )
    result = TTKCalculator.calculate(attacker, defender, config)
    return _d(result)


# ---------------------------------------------------------------------------
# Scaling tool
# ---------------------------------------------------------------------------


@mcp.tool()
def scaling_curve(
    hero_name: str,
    max_boons: int = 35,
) -> dict:
    """Get DPS and HP scaling curve for a hero across boon levels.

    Returns snapshots at each boon level with bullet damage, HP, DPS, and DPM.
    """
    hero = _resolve_hero(hero_name)
    if hero is None:
        return {"error": f"Hero '{hero_name}' not found."}

    curve = ScalingCalculator.scaling_curve(hero, max_boons)
    growth = ScalingCalculator.growth_percentage(hero, max_boons)
    return {
        "hero": hero.name,
        "growth": growth,
        "curve": [_d(s) for s in curve],
    }


# ---------------------------------------------------------------------------
# Comparison / ranking tools
# ---------------------------------------------------------------------------


@mcp.tool()
def compare_heroes(
    hero_a_name: str,
    hero_b_name: str,
    boon_level: int = 0,
) -> dict:
    """Compare two heroes side-by-side at a given boon level.

    Returns DPS, HP, DPM for each hero plus ratios.
    """
    a = _resolve_hero(hero_a_name)
    b = _resolve_hero(hero_b_name)
    if a is None:
        return {"error": f"Hero '{hero_a_name}' not found."}
    if b is None:
        return {"error": f"Hero '{hero_b_name}' not found."}

    result = ComparisonEngine.compare_two(a, b, boon_level)
    return _d(result)


@mcp.tool()
def rank_heroes(
    stat: str = "dps",
    boon_level: int = 0,
    top_n: int = 10,
) -> list[dict]:
    """Rank heroes by a stat. Stats: dps, hp, dpm, bullet_damage, fire_rate, dps_growth, hp_growth.

    Returns the top N heroes with their rank and value.
    """
    rankings = ComparisonEngine.rank_heroes(_heroes, stat, boon_level)
    return [_d(r) for r in rankings[:top_n]]


# ---------------------------------------------------------------------------
# Build tools
# ---------------------------------------------------------------------------


@mcp.tool()
def evaluate_build(
    hero_name: str,
    item_names: list[str],
    boons: int = 0,
    accuracy: float = 0.7,
    headshot_rate: float = 0.15,
    defender_name: str = "",
) -> dict:
    """Evaluate a set of items on a hero.

    Returns bullet DPS, effective HP, build cost, and TTK vs an
    optional defender.
    """
    hero = _resolve_hero(hero_name)
    if hero is None:
        return {"error": f"Hero '{hero_name}' not found."}

    items = []
    for iname in item_names:
        item = _resolve_item(iname)
        if item is None:
            return {"error": f"Item '{iname}' not found."}
        items.append(item)

    build = Build(items=items)
    defender = _resolve_hero(defender_name) if defender_name else None

    result = BuildEngine.evaluate_build(
        hero, build,
        boons=boons,
        accuracy=accuracy,
        headshot_rate=headshot_rate,
        defender=defender,
    )

    # Also compute spirit DPS (include boon-derived spirit)
    build_stats = BuildEngine.aggregate_stats(build)
    cfg = BuildEngine.build_to_attacker_config(build_stats, boons=boons, spirit_gain=hero.spirit_gain)
    spirit_dps = DamageCalculator.hero_total_spirit_dps(
        hero,
        current_spirit=cfg.current_spirit,
        cooldown_reduction=build_stats.cooldown_reduction,
        spirit_amp=build_stats.spirit_amp_pct,
    )

    bullet_dps = result.bullet_result.final_dps if result.bullet_result else 0.0

    return {
        "hero": hero.name,
        "items": [i.name for i in items],
        "total_cost": build.total_cost,
        "build_stats": _d(result.build_stats),
        "bullet_dps": bullet_dps,
        "spirit_dps": spirit_dps,
        "combined_dps": bullet_dps + spirit_dps,
        "effective_hp": result.effective_hp,
        "bullet_result": _d(result.bullet_result) if result.bullet_result else None,
        "ttk_result": _d(result.ttk_result) if result.ttk_result else None,
    }


@mcp.tool()
def optimize_build(
    hero_name: str,
    budget: int = 15000,
    boons: int = 0,
    goal: str = "dps",
    defender_name: str = "",
    max_items: int = 12,
) -> dict:
    """Find the optimal item build for a hero within a soul budget.

    goal: "dps" for raw DPS maximization, "ttk" for TTK minimization (requires defender).
    Returns the recommended items and their combined stats.
    """
    hero = _resolve_hero(hero_name)
    if hero is None:
        return {"error": f"Hero '{hero_name}' not found."}

    if goal == "ttk":
        defender = _resolve_hero(defender_name)
        if defender is None:
            return {"error": f"TTK optimization requires a defender. '{defender_name}' not found."}
        build = BuildOptimizer.best_ttk_items(
            _items, hero, defender, budget, boons=boons, max_items=max_items,
        )
    else:
        build = BuildOptimizer.best_dps_items(
            _items, hero, budget, boons=boons, max_items=max_items,
        )

    result = BuildEngine.evaluate_build(hero, build, boons=boons)
    bullet_dps = result.bullet_result.final_dps if result.bullet_result else 0.0
    build_stats = BuildEngine.aggregate_stats(build)
    cfg = BuildEngine.build_to_attacker_config(build_stats, boons=boons, spirit_gain=hero.spirit_gain)
    spirit_dps = DamageCalculator.hero_total_spirit_dps(
        hero,
        current_spirit=cfg.current_spirit,
        cooldown_reduction=build_stats.cooldown_reduction,
        spirit_amp=build_stats.spirit_amp_pct,
    )

    return {
        "hero": hero.name,
        "budget": budget,
        "total_cost": build.total_cost,
        "items": [{"name": i.name, "cost": i.cost, "category": i.category, "tier": i.tier} for i in build.items],
        "bullet_dps": bullet_dps,
        "spirit_dps": spirit_dps,
        "combined_dps": bullet_dps + spirit_dps,
        "effective_hp": result.effective_hp,
    }


@mcp.tool()
def reload_data() -> str:
    """Reload hero and item data from disk (API cache or YAML files)."""
    global _heroes, _items
    _heroes = load_heroes()
    _items = load_items()
    return f"Reloaded: {len(_heroes)} heroes, {len(_items)} items."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_hero(name: str):
    """Case-insensitive hero lookup with fuzzy matching."""
    if not name:
        return None
    # Exact match
    if name in _heroes:
        return _heroes[name]
    # Case-insensitive
    lower = name.lower()
    for k, v in _heroes.items():
        if k.lower() == lower:
            return v
    # Prefix match
    for k, v in _heroes.items():
        if k.lower().startswith(lower):
            return v
    # Substring match
    for k, v in _heroes.items():
        if lower in k.lower():
            return v
    return None


def _resolve_item(name: str):
    """Case-insensitive item lookup with fuzzy matching."""
    if not name:
        return None
    if name in _items:
        return _items[name]
    lower = name.lower()
    for k, v in _items.items():
        if k.lower() == lower:
            return v
    for k, v in _items.items():
        if k.lower().startswith(lower):
            return v
    for k, v in _items.items():
        if lower in k.lower():
            return v
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
