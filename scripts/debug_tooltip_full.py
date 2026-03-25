"""
Full scan: check every item tooltip for clipping, save close-up screenshots
of clipped cases and report patterns.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SERVER_URL = "http://localhost:8080"
SERVER_PORT = 8080
CHROMIUM = "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome"
OUT_DIR = Path("/tmp/tooltip_debug")

OUT_DIR.mkdir(parents=True, exist_ok=True)


def wait_for_server(url, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=2).status_code < 500:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def main():
    env = os.environ.copy()
    env["NICEGUI_SCREEN_TEST_PORT"] = str(SERVER_PORT)

    print("Starting server...")
    proc = subprocess.Popen(
        ["python", "-m", "deadlock_sim.ui.gui"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not wait_for_server(SERVER_URL):
        proc.terminate()
        sys.exit("Server failed to start")
    print("Ready.\n")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROMIUM)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.goto(SERVER_URL)
            page.wait_for_load_state("networkidle")

            vp = page.viewport_size

            page.get_by_role("tab", name="Build").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)

            buttons = page.locator(".item-icon-btn").all()
            print(f"Scanning {len(buttons)} items...\n")

            clipped = []
            ok_count = 0
            skip_count = 0

            for idx, btn in enumerate(buttons):
                try:
                    btn.scroll_into_view_if_needed()
                    btn.hover()
                    page.wait_for_timeout(150)

                    tooltip = btn.locator(".item-tooltip")
                    t_box = tooltip.bounding_box()
                    b_box = btn.bounding_box()
                    if not t_box or not b_box:
                        skip_count += 1
                        continue

                    left_clip   = t_box["x"]
                    right_clip  = vp["width"]  - (t_box["x"] + t_box["width"])
                    top_clip    = t_box["y"]
                    bottom_clip = vp["height"] - (t_box["y"] + t_box["height"])

                    issues = {}
                    if left_clip < 0:   issues["left"]   = -left_clip
                    if right_clip < 0:  issues["right"]  = -right_clip
                    if top_clip < 0:    issues["top"]    = -top_clip
                    if bottom_clip < 0: issues["bottom"] = -bottom_clip

                    # Get item name from tooltip
                    name = btn.locator(".tooltip-name").inner_text().strip()

                    if issues:
                        clipped.append({
                            "idx": idx,
                            "name": name,
                            "btn": b_box,
                            "tooltip": t_box,
                            "issues": issues,
                        })
                        # Close-up screenshot: clip around the button + tooltip area
                        clip_y = max(0, int(t_box["y"]) - 10)
                        clip_x = max(0, int(b_box["x"]) - 10)
                        clip_w = min(vp["width"]  - clip_x, int(b_box["width"])  + 300)
                        clip_h = min(vp["height"] - clip_y, int(b_box["height"]) + int(t_box["height"]) + 20)
                        page.screenshot(
                            path=str(OUT_DIR / f"clipped_{idx:03d}_{name.replace(' ', '_')}.png"),
                            clip={"x": clip_x, "y": clip_y, "width": clip_w, "height": clip_h},
                        )
                    else:
                        ok_count += 1
                except Exception as e:
                    skip_count += 1

            # ── Report ──────────────────────────────────────────────
            print(f"Results  (viewport {vp['width']}×{vp['height']})")
            print(f"  OK      : {ok_count}")
            print(f"  Clipped : {len(clipped)}")
            print(f"  Skipped : {skip_count}")

            if clipped:
                print("\nClipped items:")
                for r in clipped:
                    issues_str = "  ".join(
                        f"{side.upper()} {px:.0f}px" for side, px in r["issues"].items()
                    )
                    print(f"  #{r['idx']:3d}  {r['name']:<35}  btn_x={r['btn']['x']:.0f}  {issues_str}")

                # Pattern analysis
                left_clipped  = [r for r in clipped if "left"  in r["issues"]]
                right_clipped = [r for r in clipped if "right" in r["issues"]]
                top_clipped   = [r for r in clipped if "top"   in r["issues"]]

                print("\nPattern:")
                if left_clipped:
                    xs = sorted(set(round(r["btn"]["x"]) for r in left_clipped))
                    print(f"  Left-clipped items have btn_x in: {xs}")
                    print(f"  → Items in the leftmost column(s) of the grid")
                if right_clipped:
                    xs = sorted(set(round(r["btn"]["x"]) for r in right_clipped))
                    print(f"  Right-clipped items have btn_x in: {xs}")
                    print(f"  → Items in the rightmost column(s) of the grid")
                if top_clipped:
                    print(f"  Top-clipped: {len(top_clipped)} items")

                print(f"\nClose-up screenshots in: {OUT_DIR}/clipped_*.png")

                # Root cause
                print("\nRoot cause:")
                print("  .item-tooltip uses  position:absolute; left:50%; transform:translateX(-50%)")
                print("  which centres the tooltip on the button horizontally.")
                print("  For buttons near the left viewport edge the tooltip overflows left.")
                print("  tooltip width ≈ 253px  →  half = ~126px to the left of button centre.")
                if left_clipped:
                    r = left_clipped[0]
                    btn_cx = r["btn"]["x"] + r["btn"]["width"] / 2
                    print(f"  Example: btn centre x={btn_cx:.0f}  →  tooltip starts at {btn_cx - r['tooltip']['width']/2:.0f}px (off-screen)")

            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    main()
