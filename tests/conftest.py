"""Pytest configuration and fixtures for Playwright GUI tests."""

import os
import subprocess
import time

import pytest
import requests


SERVER_URL = "http://localhost:8080"
SERVER_PORT = 8080


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
        ["python", "-m", "deadlock_sim.ui.gui"],
        cwd="/home/user/DeadlockSim",
        env=env,
    )
    if not wait_for_server(SERVER_URL):
        proc.terminate()
        raise RuntimeError("GUI server did not start in time")
    yield SERVER_URL
    proc.terminate()
    proc.wait(timeout=10)


CHROMIUM_EXECUTABLE = "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome"


@pytest.fixture()
def page(playwright, gui_server):
    """Provide a Playwright page pointed at the running GUI."""
    browser = playwright.chromium.launch(executable_path=CHROMIUM_EXECUTABLE)
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(gui_server)
    pg.wait_for_load_state("networkidle")
    yield pg
    context.close()
    browser.close()
