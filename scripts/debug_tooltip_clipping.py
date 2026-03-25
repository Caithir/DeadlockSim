"""
Playwright debug script: inspect item tooltip clipping on the Build tab.

Starts the NiceGUI server, opens the Build tab, hovers over items in
different grid positions, and reports:
  - Tooltip bounding rect
  - Viewport dimensions
  - How much (if any) the tooltip is clipped on each edge
  - Screenshots saved to /tmp/tooltip_debug/
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


def wait_for_server(url: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=2).status_code < 500:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def clip_report(rect: dict, viewport: dict) -> dict:
    """Return how many pixels each edge is clipped (negative = off-screen)."""
    return {
        "left_clip":   rect["x"],
        "top_clip":    rect["y"],
        "right_clip":  viewport["width"]  - (rect["x"] + rect["width"]),
        "bottom_clip": viewport["height"] - (rect["y"] + rect["height"]),
    }


def describe_clip(c: dict) -> str:
    problems = []
    if c["left_clip"] < 0:
        problems.append(f"LEFT by {-c['left_clip']:.0f}px")
    if c["top_clip"] < 0:
        problems.append(f"TOP by {-c['top_clip']:.0f}px")
    if c["right_clip"] < 0:
        problems.append(f"RIGHT by {-c['right_clip']:.0f}px")
    if c["bottom_clip"] < 0:
        problems.append(f"BOTTOM by {-c['bottom_clip']:.0f}px")
    return "CLIPPED " + " | ".join(problems) if problems else "OK (fully visible)"


def debug_tooltips():
    env = os.environ.copy()
    env["NICEGUI_SCREEN_TEST_PORT"] = str(SERVER_PORT)

    print("Starting NiceGUI server...")
    proc = subprocess.Popen(
        ["python", "-m", "deadlock_sim.ui.gui"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not wait_for_server(SERVER_URL):
        proc.terminate()
        print("ERROR: server did not start")
        sys.exit(1)
    print("Server ready.\n")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROMIUM)
            # Use a typical laptop viewport
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.goto(SERVER_URL)
            page.wait_for_load_state("networkidle")

            viewport = page.viewport_size

            # Navigate to Build tab (triggers lazy-load)
            page.get_by_role("tab", name="Build").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)  # wait for shop to render

            # Collect all item icon buttons
            buttons = page.locator(".item-icon-btn").all()
            print(f"Found {len(buttons)} item icon buttons\n")

            if not buttons:
                print("No item buttons found — shop may not have loaded.")
                page.screenshot(path=str(OUT_DIR / "build_tab.png"))
                print(f"  Screenshot saved: {OUT_DIR}/build_tab.png")
                return

            # Screenshot of the full page before hovering
            page.screenshot(path=str(OUT_DIR / "00_build_tab_overview.png"), full_page=True)
            print(f"Overview screenshot: {OUT_DIR}/00_build_tab_overview.png\n")

            # Sample buttons: first, last, and a spread across the grid
            n = len(buttons)
            indices_to_check = sorted(set([
                0,              # top-left area
                1,
                n // 4,         # quarter way
                n // 2,         # middle
                3 * n // 4,     # three-quarter
                n - 2,
                n - 1,          # bottom-right area
            ]))

            results = []
            for idx in indices_to_check:
                btn = buttons[idx]
                try:
                    btn.scroll_into_view_if_needed()
                    btn.hover()
                    page.wait_for_timeout(300)

                    # Locate the visible tooltip inside this button
                    tooltip = btn.locator(".item-tooltip")
                    t_box = tooltip.bounding_box()
                    b_box = btn.bounding_box()

                    screenshot_path = OUT_DIR / f"item_{idx:03d}.png"
                    page.screenshot(path=str(screenshot_path))

                    if t_box:
                        clip = clip_report(t_box, viewport)
                        status = describe_clip(clip)
                        results.append({
                            "idx": idx,
                            "btn_x": round(b_box["x"]) if b_box else "?",
                            "tooltip": t_box,
                            "clip": clip,
                            "status": status,
                        })
                        print(f"  Item #{idx:3d} | btn_x={round(b_box['x']) if b_box else '?':4} "
                              f"| tooltip x={t_box['x']:.0f} w={t_box['width']:.0f} "
                              f"| {status}")
                    else:
                        print(f"  Item #{idx:3d} | tooltip not visible / no bounding box")

                except Exception as e:
                    print(f"  Item #{idx:3d} | ERROR: {e}")

            # Summary
            print("\n── Summary ─────────────────────────────────────────────────")
            clipped = [r for r in results if "CLIPPED" in r["status"]]
            ok      = [r for r in results if "OK" in r["status"]]
            print(f"  Checked : {len(results)} items")
            print(f"  OK      : {len(ok)}")
            print(f"  Clipped : {len(clipped)}")

            if clipped:
                print("\n  Clipped items:")
                for r in clipped:
                    print(f"    #{r['idx']:3d}  btn_x={r['btn_x']:4}  {r['status']}")
                    print(f"           tooltip rect: x={r['tooltip']['x']:.0f}  "
                          f"y={r['tooltip']['y']:.0f}  "
                          f"w={r['tooltip']['width']:.0f}  "
                          f"h={r['tooltip']['height']:.0f}")

            print(f"\n  Viewport : {viewport['width']}×{viewport['height']}")
            print(f"  Screenshots in : {OUT_DIR}/")

            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    debug_tooltips()
