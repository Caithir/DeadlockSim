"""Shared damage primitives used by both DamageCalculator and CombatSimulator.

Pure math functions with zero imports from models or other engine modules.
These form the lowest layer in the dependency chain.
"""

from __future__ import annotations


def resist_after_shred(base_resist: float, total_shred: float) -> float:
    """Compute effective resist after shred is applied.

    Formula: max(0, min(1, base_resist * (1 - min(1, total_shred))))
    Returns clamped resist value in [0, 1].
    """
    clamped_shred = min(1.0, max(0.0, total_shred))
    return max(0.0, min(1.0, base_resist * (1.0 - clamped_shred)))


def falloff_multiplier(
    distance: float,
    falloff_min: float,
    falloff_max: float,
    min_damage_frac: float = 0.1,
) -> float:
    """Compute damage falloff multiplier based on distance.

    Within falloff_min → 1.0 (full damage).
    Between falloff_min and falloff_max → linear interpolation to min_damage_frac.
    Beyond falloff_max → min_damage_frac.
    If falloff range is zero/invalid → 1.0 (no falloff).
    """
    if falloff_max <= falloff_min or falloff_max <= 0:
        return 1.0
    if distance <= falloff_min:
        return 1.0
    if distance >= falloff_max:
        return min_damage_frac
    # Linear interpolation
    t = (distance - falloff_min) / (falloff_max - falloff_min)
    return 1.0 - t * (1.0 - min_damage_frac)


def apply_amplifiers(
    base_damage: float,
    spirit_amp: float = 0.0,
    damage_amp: float = 0.0,
) -> float:
    """Apply multiplicative spirit amp and damage amp to base damage.

    Returns: base_damage * (1 + spirit_amp) * (1 + damage_amp)
    """
    return base_damage * (1.0 + spirit_amp) * (1.0 + damage_amp)


def extract_item_damage(
    props: dict,
) -> tuple[float, str, float, bool, float, float] | None:
    """Extract damage info from item raw_properties.

    Returns (base_damage, scale_type, stat_scale, is_dps, proc_cooldown, proc_chance)
    or None if the item has no damage properties.

    This is the canonical implementation used by both DamageCalculator
    and the simulation item classifier.
    """
    # Property keys that indicate damage output (ordered by priority)
    _DAMAGE_KEYS = [
        "DPS",
        "DPSMax",
        "ProcBonusMagicDamage",
        "DamagePerChain",
        "AbilityDamage",
        "TechDamage",
        "DotHealthPercent",
        "BulletDamage",
        "HeadShotBonusDamage",
        "BonusDamage",
        "Damage",
    ]

    base_damage = 0.0
    scale_type = ""
    stat_scale = 0.0
    is_dps = False
    damage_key_found = ""

    for key in _DAMAGE_KEYS:
        prop = props.get(key)
        if not isinstance(prop, dict):
            continue
        val = prop.get("value")
        if val is None:
            continue
        try:
            base_damage = float(val)
        except (ValueError, TypeError):
            continue

        damage_key_found = key
        is_dps = key in ("DPS", "DPSMax", "DotHealthPercent")

        scale_fn = prop.get("scale_function")
        if isinstance(scale_fn, dict):
            scale_type = scale_fn.get("specific_stat_scale_type", "")
            try:
                stat_scale = float(scale_fn.get("stat_scale", 0.0))
            except (ValueError, TypeError):
                stat_scale = 0.0
        break

    if not damage_key_found:
        return None

    # Extract proc timing
    proc_cooldown = 0.0
    proc_chance = 100.0

    cd_prop = props.get("ProcCooldown") or props.get("AbilityCooldown")
    if isinstance(cd_prop, dict):
        try:
            proc_cooldown = float(cd_prop.get("value", 0))
        except (ValueError, TypeError):
            pass

    chance_prop = props.get("ProcChance")
    if isinstance(chance_prop, dict):
        try:
            proc_chance = float(chance_prop.get("value", 100))
        except (ValueError, TypeError):
            proc_chance = 100.0

    return (base_damage, scale_type, stat_scale, is_dps, proc_cooldown, proc_chance)
