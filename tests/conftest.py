"""Pytest configuration and fixtures for Playwright GUI tests."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


SERVER_URL = "http://localhost:8080"
SERVER_PORT = 8080
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """Poll until the server responds or timeout is reached."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def gui_server():
    """Start the NiceGUI server once for the whole test session."""
    # NiceGUI detects pytest-playwright and activates screen-test mode,
    # which requires NICEGUI_SCREEN_TEST_PORT to be set.
    env = os.environ.copy()
    env["NICEGUI_SCREEN_TEST_PORT"] = str(SERVER_PORT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "deadlock_sim.ui.gui"],
        cwd=str(_PROJECT_ROOT),
        env=env,
    )
    if not wait_for_server(SERVER_URL):
        proc.terminate()
        raise RuntimeError("GUI server did not start in time")
    yield SERVER_URL
    proc.terminate()
    proc.wait(timeout=10)


def _find_chromium() -> str | None:
    """Discover Playwright's bundled Chromium executable."""
    # Let playwright tell us where browsers live
    try:
        from playwright._impl._driver import compute_driver_executable  # type: ignore
    except ImportError:
        pass
    # Common cache locations by platform
    if sys.platform == "win32":
        cache = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    else:
        cache = Path.home() / ".cache" / "ms-playwright"
    if cache.exists():
        for chrome in sorted(cache.rglob("chrome" if sys.platform != "win32" else "chrome.exe"), reverse=True):
            return str(chrome)
    return None


@pytest.fixture()
def page(playwright, gui_server):
    """Provide a Playwright page pointed at the running GUI."""
    chromium_path = _find_chromium()
    launch_kwargs: dict = {}
    if chromium_path:
        launch_kwargs["executable_path"] = chromium_path
    browser = playwright.chromium.launch(**launch_kwargs)
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(gui_server)
    pg.wait_for_load_state("networkidle")
    yield pg
    context.close()
    browser.close()
