"""Fetch, parse, and apply Deadlock patch notes from the official forum.

Workflow:
    1. fetch_latest_patch_url()   — scrape changelog index for newest thread
    2. fetch_patch_text(url)      — scrape thread for the patch note body
    3. parse_patch_notes(text)    — regex-parse lines into PatchChange objects
    4. diff_patch(changes, heroes, items) — compare changes vs current data
    5. apply_patch(changes, heroes, items) — mutate loaded data in-place
"""

from __future__ import annotations

import html as _html
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_CHANGELOG_URL = "https://forums.playdeadlock.com/forums/changelog.10/"
_FORUM_BASE = "https://forums.playdeadlock.com"
_TIMEOUT = 30
_PATCH_DIR = Path(__file__).parent.parent / "data" / "patches"

# Hero name aliases: patch notes may use short names the API doesn't
_HERO_ALIASES: dict[str, str] = {
    "Doorman": "The Doorman",
}


# ── Data structures ────────────────────────────────────────────────


@dataclass
class PatchChange:
    """A single parsed change from patch notes."""

    raw_line: str
    hero: str = ""          # hero name, empty for item/general changes
    item: str = ""          # item name, empty for hero/general changes
    ability: str = ""       # ability name if ability-specific
    upgrade_tier: int = 0   # T1=1, T2=2, T3=3, 0=base
    stat: str = ""          # human-readable stat description
    old_value: str = ""     # previous value (string, may be complex)
    new_value: str = ""     # new value
    change_type: str = ""   # "numeric", "description", "mechanical", "unknown"

    # Parsed numeric values (None if non-numeric)
    old_numeric: float | None = None
    new_numeric: float | None = None


@dataclass
class PatchDiffEntry:
    """Comparison of a patch change against current simulator data."""

    change: PatchChange
    current_value: str = ""
    status: str = ""  # "already_applied", "needs_update", "not_modeled", "manual_review"
    notes: str = ""


@dataclass
class PatchReport:
    """Full report from diffing patch notes against current data."""

    patch_date: str = ""
    patch_url: str = ""
    total_changes: int = 0
    entries: list[PatchDiffEntry] = field(default_factory=list)

    @property
    def already_applied(self) -> list[PatchDiffEntry]:
        return [e for e in self.entries if e.status == "already_applied"]

    @property
    def needs_update(self) -> list[PatchDiffEntry]:
        return [e for e in self.entries if e.status == "needs_update"]

    @property
    def manual_review(self) -> list[PatchDiffEntry]:
        return [e for e in self.entries if e.status in ("manual_review", "not_modeled")]


# ── Fetching ───────────────────────────────────────────────────────


def fetch_latest_patch_url() -> tuple[str, str]:
    """Scrape the changelog index to find the latest patch thread.

    Returns (url, date_string) for the most recent non-sticky thread.
    """
    resp = requests.get(_CHANGELOG_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    html = resp.text

    # Find thread links matching the date-update pattern
    # e.g. /threads/03-25-2026-update.121766/
    pattern = re.compile(
        r'href="(/threads/(\d{2}-\d{2}-\d{4})-update\.\d+/)"',
        re.IGNORECASE,
    )
    matches = pattern.findall(html)
    if not matches:
        raise RuntimeError("Could not find any patch note threads on the changelog page.")

    # First match is the most recent (forum lists newest first)
    path, date_str = matches[0]
    url = _FORUM_BASE + path
    return url, date_str


def fetch_patch_text(url: str) -> str:
    """Fetch a patch thread and extract the patch note lines.

    Returns the raw text content of the first post.
    """
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    html = resp.text

    # Extract text between the first post content markers
    # The forum uses bbWrapper divs; we'll extract bullet lines
    seen: set[str] = set()
    lines: list[str] = []
    for line in html.split("\n"):
        stripped = line.strip()
        # Look for the changelog bullet lines (start with "- " in rendered text)
        # In the HTML they appear as list items or raw text with dash prefix
        if stripped.startswith("- ") or stripped.startswith("\u2011 "):
            # Clean HTML tags and decode HTML entities
            clean = re.sub(r"<[^>]+>", "", stripped)
            # Remove partial HTML artifacts like ..." />
            clean = re.sub(r'\.\.\."?\s*/?\s*>', '', clean)
            clean = _html.unescape(clean)
            clean = clean.strip("- ").strip("\u2011 ").strip()
            # Skip lines that are just truncated fragments
            if clean and clean not in seen and ":" in clean and not clean.endswith("..."):
                seen.add(clean)
                lines.append(clean)

    if not lines:
        # Fallback: try to find lines matching "Hero: change" pattern
        all_text = re.sub(r"<[^>]+>", " ", html)
        all_text = _html.unescape(all_text)
        all_text = re.sub(r"\s+", " ", all_text)
        for segment in re.split(r"(?:^|\s)-\s", all_text):
            segment = segment.strip()
            if segment not in seen and ":" in segment and any(
                kw in segment.lower()
                for kw in ("increased", "reduced", "changed", "now ", "reworked")
            ):
                seen.add(segment)
                lines.append(segment)

    return "\n".join(lines)


def fetch_latest_patch() -> tuple[str, str, str]:
    """Convenience: fetch the latest patch URL, date, and text.

    Returns (url, date_string, patch_text).
    """
    url, date_str = fetch_latest_patch_url()
    text = fetch_patch_text(url)
    return url, date_str, text


# ── Parsing ────────────────────────────────────────────────────────

# Regex for "from X to Y" with numeric values
_FROM_TO = re.compile(
    r"(?:increased|reduced|changed|went|rescaled)\s+from\s+(.+?)\s+to\s+(.+?)$",
    re.IGNORECASE,
)

# Regex for tier prefix: "T1 ", "T2 ", "T3 "
_TIER_PREFIX = re.compile(r"^T([123])\s+", re.IGNORECASE)

# Regex to extract a leading numeric value (possibly with sign/%)
_NUMERIC = re.compile(r"^[+\-]?([\d.]+)")


def _try_parse_numeric(s: str) -> float | None:
    """Try to extract a numeric value from a patch note value string."""
    s = s.strip()
    # Strip trailing units: s (seconds), m (meters), %
    s = re.sub(r'[sm%]+$', '', s).strip()
    # Handle "+X" or "-X" prefix
    s = s.lstrip('+')
    m = _NUMERIC.match(s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def parse_patch_notes(text: str) -> list[PatchChange]:
    """Parse raw patch note text into structured PatchChange objects.

    Each line should be one change, formatted like:
        "Hero: Ability T2 stat increased from X to Y"
        "Hero: Base stat reduced from X to Y"
        "Item: stat changed from X to Y"
    """
    changes: list[PatchChange] = []

    for raw_line in text.strip().split("\n"):
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        change = PatchChange(raw_line=raw_line)

        # Split on first ": " to get entity and description
        colon_idx = raw_line.find(": ")
        if colon_idx < 0:
            change.change_type = "unknown"
            changes.append(change)
            continue

        entity = raw_line[:colon_idx].strip()
        description = raw_line[colon_idx + 2:].strip()

        # Determine if this is a hero or item change
        # (We'll set hero by default; the caller can cross-reference item names)
        # Resolve hero name aliases (e.g. "Doorman" -> "The Doorman")
        change.hero = _HERO_ALIASES.get(entity, entity)

        # Check for upgrade tier in the description
        tier_match = _TIER_PREFIX.search(description)
        if tier_match:
            change.upgrade_tier = int(tier_match.group(1))
            # The ability name is everything before the T# marker
            # But first we need to find where the ability name ends
            # The description format is: "Ability Name T# stat changed from X to Y"

        # Try to extract "from X to Y"
        from_to = _FROM_TO.search(description)
        if from_to:
            change.old_value = from_to.group(1).strip()
            change.new_value = from_to.group(2).strip()
            change.old_numeric = _try_parse_numeric(change.old_value)
            change.new_numeric = _try_parse_numeric(change.new_value)

            # The stat description is everything before "increased/reduced/changed"
            stat_part = description[:from_to.start()].strip()

            # Extract ability name if present (before T# or before the stat keyword)
            if tier_match:
                before_tier = description[:tier_match.start()].strip()
                change.ability = before_tier
                after_tier = description[tier_match.end():from_to.start()].strip()
                change.stat = after_tier
            else:
                change.stat = stat_part
                # Try to identify the ability name from the stat description
                # Pattern: "AbilityName statdescription" — ability names are typically
                # multi-word capitalized phrases before the stat keyword
                _extract_ability_from_stat(change)

            if change.old_numeric is not None and change.new_numeric is not None:
                change.change_type = "numeric"
            else:
                change.change_type = "description"
        elif "now " in description.lower() or "reworked" in description.lower():
            change.change_type = "mechanical"
            change.stat = description
            _extract_ability_from_stat(change)
        elif "changed from" in description.lower():
            change.change_type = "description"
            change.stat = description
            _extract_ability_from_stat(change)
        else:
            change.change_type = "unknown"
            change.stat = description

        changes.append(change)

    return changes


def _extract_ability_from_stat(change: PatchChange) -> None:
    """Try to split an ability name from the stat description.

    Many patch lines look like "Afterburn DPS increased from 12 to 14"
    where "Afterburn" is the ability and "DPS" is the stat.
    Uses known stat keywords to find the split point.
    """
    stat = change.stat
    if not stat:
        return

    stat_lower = stat.lower()

    # These are hero base stats, not abilities — don't split them
    if stat_lower.startswith("base "):
        change.ability = ""
        return
    if stat_lower.startswith("gun "):
        change.ability = ""
        return
    if stat_lower.startswith("bullet damage"):
        change.ability = ""
        return

    # Known stat keywords that indicate where the ability name ends
    # Ordered longest-first so "spirit damage scaling" matches before "damage"
    _STAT_KEYWORDS = [
        "spirit damage scaling", "damage spirit scaling",
        "base damage", "base health", "base regen", "base hp",
        "impact damage scaling", "damage scaling",
        "spirit scaling", "spirit damage",
        "wall stun", "stun duration", "silence duration",
        "damage", "dps", "duration", "cooldown", "radius",
        "health steal per sec", "health",
        "slow", "speed", "range", "distance", "width",
        "lifesteal", "scaling", "hp", "fire rate", "ammo",
        "falloff", "bonus damage", "heal", "shield",
    ]

    for kw in _STAT_KEYWORDS:
        idx = stat_lower.find(kw)
        if idx > 0:
            potential_ability = stat[:idx].strip()
            if potential_ability and potential_ability[0].isupper():
                change.ability = potential_ability
                change.stat = stat[idx:].strip()
                return


# ── Diffing against current data ──────────────────────────────────


def diff_patch(
    changes: list[PatchChange],
    heroes: dict,
    items: dict | None = None,
) -> PatchReport:
    """Compare parsed patch changes against currently loaded data.

    Returns a PatchReport with status for each change.
    """
    report = PatchReport(total_changes=len(changes))

    # Build lookup for hero abilities by name
    hero_abilities: dict[str, dict[str, object]] = {}
    for hname, hero in heroes.items():
        ab_map = {}
        for ab in hero.abilities:
            ab_map[ab.name.lower()] = ab
        hero_abilities[hname] = ab_map

    for change in changes:
        entry = PatchDiffEntry(change=change)

        # Check if this is an item change (entity matches an item name)
        if items and change.hero in items:
            change.item = change.hero
            change.hero = ""

        if change.change_type == "mechanical":
            entry.status = "manual_review"
            entry.notes = "Mechanical change requires manual implementation"
            report.entries.append(entry)
            continue

        if change.change_type == "unknown":
            entry.status = "manual_review"
            entry.notes = "Could not parse this change"
            report.entries.append(entry)
            continue

        # Try to find the current value in loaded data
        if change.hero and change.hero in heroes:
            hero = heroes[change.hero]
            current = _find_hero_current_value(hero, change)
            if current is not None:
                entry.current_value = str(current)
                if change.new_numeric is not None:
                    try:
                        if abs(float(current) - change.new_numeric) < 0.01:
                            entry.status = "already_applied"
                        else:
                            entry.status = "needs_update"
                            entry.notes = f"Current={current}, Patch wants={change.new_value}"
                    except (ValueError, TypeError):
                        entry.status = "manual_review"
                else:
                    entry.status = "manual_review"
                    entry.notes = "Non-numeric change"
            else:
                entry.status = "not_modeled"
                entry.notes = "Stat not tracked in simulator"
        elif change.hero:
            entry.status = "manual_review"
            entry.notes = f"Hero '{change.hero}' not found in loaded data"
        elif change.item:
            entry.status = "not_modeled"
            entry.notes = "Item changes not yet auto-applied"
        else:
            entry.status = "manual_review"

        report.entries.append(entry)

    return report


# Mapping of patch note stat keywords to HeroStats fields
_HERO_STAT_MAP: dict[str, str] = {
    "base health regen": "base_regen",
    "base regen": "base_regen",
    "base health": "base_hp",
    "base hp": "base_hp",
    "base bullet damage": "base_bullet_damage",
    "bullet damage": "base_bullet_damage",
    "base ammo": "base_ammo",
    "light melee damage": "light_melee_damage",
    "heavy melee damage": "heavy_melee_damage",
    "base move speed": "base_move_speed",
    "base sprint": "base_sprint",
}


def _find_hero_current_value(hero, change: PatchChange) -> float | str | None:
    """Look up the current value of a stat for diffing."""
    stat_lower = change.stat.lower().strip()

    # Hero base stats
    if not change.ability:
        mapped = _HERO_STAT_MAP.get(stat_lower)
        if mapped:
            return getattr(hero, mapped, None)
        # Check for falloff (both "Gun Falloff" and ability stat lines)
        if "falloff" in stat_lower:
            return f"{hero.falloff_range_min}->{hero.falloff_range_max}"
        # "Bullet damage rescaled from X+Y to X+Y" — base + per-boon gain
        if "rescaled" in stat_lower or ("bullet" in stat_lower and "damage" in stat_lower):
            return f"{hero.base_bullet_damage}+{hero.damage_gain}"
        return None

    # Ability stats
    for ab in hero.abilities:
        if ab.name.lower() == change.ability.lower():
            if change.upgrade_tier > 0:
                # Tier upgrade — check upgrade descriptions
                for upg in ab.upgrades:
                    if upg.tier == change.upgrade_tier:
                        return upg.description
                return None

            # Base ability stats — check scaling first since "damage scaling"
            # contains "damage" but refers to the spirit_scaling field
            if "scaling" in stat_lower:
                return ab.spirit_scaling
            if "damage" in stat_lower or "dps" in stat_lower:
                return ab.base_damage
            if "cooldown" in stat_lower:
                return ab.cooldown
            if "duration" in stat_lower:
                return ab.duration
            if "radius" in stat_lower or "range" in stat_lower or "distance" in stat_lower:
                # Check raw properties
                for key, prop in ab.properties.items():
                    if isinstance(prop, dict) and any(
                        kw in key.lower() for kw in ("radius", "range", "distance")
                    ):
                        return prop.get("value")
            # Generic property search
            for key, prop in ab.properties.items():
                if isinstance(prop, dict) and stat_lower.replace(" ", "") in key.lower():
                    return prop.get("value")
            return None

    return None


# ── Applying changes ───────────────────────────────────────────────


def apply_patch(
    changes: list[PatchChange],
    heroes: dict,
    items: dict | None = None,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Apply parsed patch changes to loaded hero/item data in-place.

    Only applies numeric changes where the mapping is clear.
    Returns a list of log messages describing what was applied.

    If dry_run=True, returns what *would* be applied without mutating.
    """
    applied: list[str] = []

    for change in changes:
        if change.change_type != "numeric":
            continue
        if change.new_numeric is None:
            continue

        # Hero base stat changes
        if change.hero and change.hero in heroes and not change.ability:
            hero = heroes[change.hero]
            stat_lower = change.stat.lower().strip()
            mapped = _HERO_STAT_MAP.get(stat_lower)
            if mapped:
                old = getattr(hero, mapped, None)
                msg = f"{change.hero}: {mapped} {old} -> {change.new_numeric}"
                if not dry_run:
                    setattr(hero, mapped, change.new_numeric)
                applied.append(msg)
                continue

            # Falloff special case
            if "falloff" in stat_lower and "->" in change.new_value:
                parts = change.new_value.split("->")
                if len(parts) == 2:
                    try:
                        new_min = float(parts[0])
                        new_max = float(parts[1])
                        msg = (
                            f"{change.hero}: falloff "
                            f"{hero.falloff_range_min}->{hero.falloff_range_max} "
                            f"-> {new_min}->{new_max}"
                        )
                        if not dry_run:
                            hero.falloff_range_min = new_min
                            hero.falloff_range_max = new_max
                        applied.append(msg)
                    except ValueError:
                        pass
                continue

        # Ability stat changes
        if change.hero and change.hero in heroes and change.ability:
            hero = heroes[change.hero]
            for ab in hero.abilities:
                if ab.name.lower() != change.ability.lower():
                    continue

                stat_lower = change.stat.lower().strip()

                if change.upgrade_tier > 0:
                    # Tier upgrade numeric change — update property_upgrades
                    # This is complex; log for manual review
                    applied.append(
                        f"{change.hero}: {ab.name} T{change.upgrade_tier} "
                        f"{change.stat} -> {change.new_value} (upgrade, logged only)"
                    )
                    break

                # Base ability stats — check scaling first
                if "scaling" in stat_lower:
                    msg = f"{change.hero}: {ab.name} spirit_scaling {ab.spirit_scaling} -> {change.new_numeric}"
                    if not dry_run:
                        ab.spirit_scaling = change.new_numeric
                    applied.append(msg)
                elif any(kw in stat_lower for kw in ("damage", "dps")):
                    msg = f"{change.hero}: {ab.name} base_damage {ab.base_damage} -> {change.new_numeric}"
                    if not dry_run:
                        ab.base_damage = change.new_numeric
                    applied.append(msg)
                elif "cooldown" in stat_lower:
                    msg = f"{change.hero}: {ab.name} cooldown {ab.cooldown} -> {change.new_numeric}"
                    if not dry_run:
                        ab.cooldown = change.new_numeric
                    applied.append(msg)
                elif "duration" in stat_lower:
                    msg = f"{change.hero}: {ab.name} duration {ab.duration} -> {change.new_numeric}"
                    if not dry_run:
                        ab.duration = change.new_numeric
                    applied.append(msg)
                else:
                    applied.append(
                        f"{change.hero}: {ab.name} {change.stat} -> {change.new_value} (unmapped stat)"
                    )
                break

    return applied


# ── Saving / Loading patches ──────────────────────────────────────


def save_patch(date_str: str, text: str, url: str) -> Path:
    """Save raw patch text to data/patches/ for reference."""
    _PATCH_DIR.mkdir(parents=True, exist_ok=True)
    path = _PATCH_DIR / f"{date_str}.txt"
    path.write_text(f"# Source: {url}\n\n{text}", encoding="utf-8")
    return path


def load_saved_patch(date_str: str) -> str | None:
    """Load a previously saved patch by date string."""
    path = _PATCH_DIR / f"{date_str}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def list_saved_patches() -> list[str]:
    """List date strings of all saved patches."""
    if not _PATCH_DIR.exists():
        return []
    return sorted(
        p.stem for p in _PATCH_DIR.glob("*.txt")
    )


# ── Pretty printing ───────────────────────────────────────────────


def format_report(report: PatchReport) -> str:
    """Format a PatchReport as a human-readable string."""
    lines = [
        f"Patch: {report.patch_date}",
        f"URL: {report.patch_url}",
        f"Total changes: {report.total_changes}",
        "",
    ]

    applied = report.already_applied
    if applied:
        lines.append(f"=== ALREADY APPLIED ({len(applied)}) ===")
        for e in applied:
            c = e.change
            lines.append(f"  [OK] {c.hero or c.item}: {c.ability} {c.stat} = {e.current_value}")
        lines.append("")

    needs = report.needs_update
    if needs:
        lines.append(f"=== NEEDS UPDATE ({len(needs)}) ===")
        for e in needs:
            c = e.change
            lines.append(f"  [!!] {c.raw_line}")
            lines.append(f"       {e.notes}")
        lines.append("")

    manual = report.manual_review
    if manual:
        lines.append(f"=== MANUAL REVIEW ({len(manual)}) ===")
        for e in manual:
            c = e.change
            lines.append(f"  [??] {c.raw_line}")
            if e.notes:
                lines.append(f"       {e.notes}")
        lines.append("")

    return "\n".join(lines)


# ── CLI entry point ────────────────────────────────────────────────


def _cli_main() -> None:
    """Entry point for ``deadlock-sim-patch`` console script."""
    import argparse
    import sys

    from .data import load_heroes, load_items
    from .api_client import refresh_all_data as _refresh

    parser = argparse.ArgumentParser(
        description="Fetch and apply Deadlock patch notes to the simulator.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply numeric changes.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be applied.")
    parser.add_argument("--refresh", action="store_true", help="Refresh API data first.")
    parser.add_argument("--url", type=str, default="", help="Specific patch thread URL.")
    args = parser.parse_args()

    if args.refresh:
        print("Refreshing API data...")
        _refresh()

    print("Fetching latest patch notes...")
    if args.url:
        import re as _re
        url = args.url
        m = _re.search(r"(\d{2}-\d{2}-\d{4})", url)
        date_str = m.group(1) if m else "unknown"
        text = fetch_patch_text(url)
    else:
        url, date_str, text = fetch_latest_patch()

    print(f"  Patch: {date_str}  URL: {url}")
    save_patch(date_str, text, url)

    changes = parse_patch_notes(text)
    print(f"  Parsed {len(changes)} changes\n")

    try:
        heroes = load_heroes()
        items = load_items()
    except RuntimeError as exc:
        print(f"Error: {exc}\nRun with --refresh to fetch data first.")
        sys.exit(1)

    if args.apply or args.dry_run:
        msgs = apply_patch(changes, heroes, items, dry_run=args.dry_run)
        label = "Would apply" if args.dry_run else "Applied"
        print(f"{label} {len(msgs)} changes:")
        for m in msgs:
            print(f"  {m}")
    else:
        report = diff_patch(changes, heroes, items)
        report.patch_date = date_str
        report.patch_url = url
        print(format_report(report))
