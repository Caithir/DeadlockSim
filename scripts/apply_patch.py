"""Fetch the latest Deadlock patch notes and apply changes to the simulator.

Usage:
    python scripts/apply_patch.py              # fetch latest, show report
    python scripts/apply_patch.py --apply      # fetch latest, apply changes
    python scripts/apply_patch.py --dry-run    # show what would be applied
    python scripts/apply_patch.py --refresh    # refresh API data first, then diff
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from deadlock_sim.data import load_heroes, load_items
from deadlock_sim.api_client import refresh_all_data
from deadlock_sim.patchnotes import (
    apply_patch,
    diff_patch,
    fetch_latest_patch,
    format_report,
    parse_patch_notes,
    save_patch,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and apply Deadlock patch notes to the simulator."
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply numeric changes to currently loaded data and report results.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what changes would be applied without modifying data.",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Refresh API data before diffing (pulls latest from assets.deadlock-api.com).",
    )
    parser.add_argument(
        "--url", type=str, default="",
        help="Use a specific patch thread URL instead of auto-detecting the latest.",
    )
    args = parser.parse_args()

    # Step 1: Optionally refresh API data
    if args.refresh:
        print("Refreshing API data from assets.deadlock-api.com...")
        summary = refresh_all_data()
        print(f"  Fetched {summary.get('heroes', 0)} heroes, {summary.get('items', 0)} items")
        print()

    # Step 2: Fetch patch notes
    print("Fetching latest patch notes from forums.playdeadlock.com...")
    if args.url:
        from deadlock_sim.patchnotes import fetch_patch_text
        url = args.url
        # Extract date from URL
        import re
        date_match = re.search(r"(\d{2}-\d{2}-\d{4})", url)
        date_str = date_match.group(1) if date_match else "unknown"
        text = fetch_patch_text(url)
    else:
        url, date_str, text = fetch_latest_patch()

    print(f"  Found patch: {date_str}")
    print(f"  URL: {url}")

    # Save raw patch for reference
    saved = save_patch(date_str, text, url)
    print(f"  Saved to: {saved}")
    print()

    # Step 3: Parse changes
    changes = parse_patch_notes(text)
    print(f"Parsed {len(changes)} changes from patch notes.")
    print()

    # Step 4: Load current data
    try:
        heroes = load_heroes()
        items = load_items()
    except RuntimeError as e:
        print(f"Error loading data: {e}")
        print("Run with --refresh to fetch API data first.")
        sys.exit(1)

    # Step 5: Diff or Apply
    if args.apply or args.dry_run:
        log = apply_patch(changes, heroes, items, dry_run=args.dry_run)
        action = "Would apply" if args.dry_run else "Applied"
        print(f"{action} {len(log)} changes:")
        for msg in log:
            print(f"  {msg}")
        print()

        # Also show what couldn't be applied
        report = diff_patch(changes, heroes, items)
        report.patch_date = date_str
        report.patch_url = url
        manual = report.manual_review
        if manual:
            print(f"=== MANUAL REVIEW ({len(manual)}) ===")
            for e in manual:
                print(f"  [??] {e.change.raw_line}")
                if e.notes:
                    print(f"       {e.notes}")
    else:
        # Just show the diff report
        report = diff_patch(changes, heroes, items)
        report.patch_date = date_str
        report.patch_url = url
        print(format_report(report))


if __name__ == "__main__":
    main()
