"""Pytest configuration and fixtures for Playwright GUI tests."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


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


def _find_free_port() -> int:
    """Reserve and return an available local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _terminate_gui_processes() -> None:
    """Stop leftover GUI processes from prior manual or test runs."""
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process "
                    "| Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'deadlock_sim.ui.gui' } "
                    "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
                ),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


@pytest.fixture(scope="session")
def gui_server():
    """Start the NiceGUI server once for the whole test session."""
    _terminate_gui_processes()

    # NiceGUI detects pytest-playwright and activates screen-test mode,
    # which requires NICEGUI_SCREEN_TEST_PORT to be set.
    server_port = _find_free_port()
    server_url = f"http://localhost:{server_port}"
    env = os.environ.copy()
    env["NICEGUI_SCREEN_TEST_PORT"] = str(server_port)
    env["PORT"] = str(server_port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "deadlock_sim.ui.gui"],
        cwd=str(_PROJECT_ROOT),
        env=env,
    )
    if not wait_for_server(server_url):
        proc.terminate()
        raise RuntimeError("GUI server did not start in time")
    yield server_url
    proc.terminate()
    proc.wait(timeout=10)
    _terminate_gui_processes()


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
