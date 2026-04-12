"""Download and cache assets for the deadlock-ui web components.

The @deadlock-api/ui-core library fetches item data and images from two CDN
origins at runtime.  This module pre-downloads everything so the NiceGUI app
can serve them locally, enabling fully-offline operation after the first run.

Cache layout under ``data/``:

    ui_lib/main.esm.js          – patched ESM bundle (API URLs rewritten)
    ui_cache/api/*.json          – raw API responses for the web components
    ui_cache/cdn/images/…        – item / shop images
    ui_cache/cdn/fonts/…         – Retail Demo + Tetsubingothic fonts
    ui_cache/cdn/icons/…         – soul icon SVG
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_LIB_DIR = _DATA_DIR / "ui_lib"
_CACHE_DIR = _DATA_DIR / "ui_cache"
_CDN_DIR = _CACHE_DIR / "cdn"
_API_DIR = _CACHE_DIR / "api"

_BUNDLE_URL = "https://unpkg.com/@deadlock-api/ui-core/dist/main/main.esm.js"
_BUNDLE_META_URL = "https://unpkg.com/@deadlock-api/ui-core/dist/main/?meta"
_BUNDLE_BASE_URL = "https://unpkg.com/@deadlock-api/ui-core/dist/main/"

_API_BASE = "https://assets.deadlock-api.com"
_CDN_BASE = "https://assets-bucket.deadlock-api.com/assets-api-res"

_TIMEOUT = 30

# ── Known shop UI assets (derived from deadlock-ui assets.ts) ──────────────

_SHOP_SLOTS = ("weapon", "vitality", "spirit")
_SHOP_TIERS = (1, 2, 3, 4)

_SHOP_ASSETS: list[str] = []
for _slot in _SHOP_SLOTS:
    _SHOP_ASSETS.append(f"images/shop/catalog/catalog_tooltip_header_{_slot}.png")
    _SHOP_ASSETS.append(f"images/shop/catalog/catalog_tooltip_bg_{_slot}.png")
    _mapped = "spirit" if _slot == "tech" else _slot
    _SHOP_ASSETS.append(f"images/shop/catalog/catalog_shop_bg_{_mapped}.webp")
    _SHOP_ASSETS.append(f"images/shop/catalog/catalog_shop_tab_icon_{_slot}.png")
    for _tier in _SHOP_TIERS:
        _SHOP_ASSETS.append(
            f"images/shop/catalog/cards/card_backer_{_slot}_t{_tier}.png"
        )
_SHOP_ASSETS.append("images/shop/catalog/catalog_shop_tab_shape.png")
_SHOP_ASSETS.append("images/shop/catalog/catalog_shop_tab_edge_overlay.png")

_FONT_FILES = [
    "fonts/retaildemo-regular.otf",
    "fonts/retaildemo-italic.otf",
    "fonts/retaildemo-semibold.otf",
    "fonts/retaildemo-semibolditalic.otf",
    "fonts/retaildemo-bold.otf",
    "fonts/retaildemo-bolditalic.otf",
    "fonts/tetsubingothic.otf",
]

_ICON_FILES = [
    "icons/icon_soul.svg",
]

# ── Helpers ────────────────────────────────────────────────────────────────

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _download(url: str, dest: Path) -> bool:
    """Download *url* to *dest*, creating parent dirs.  Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = _get_session().get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except requests.RequestException as exc:
        log.warning("Download failed %s → %s: %s", url, dest, exc)
        return False


def _cdn_url(path: str) -> str:
    return f"{_CDN_BASE}/{path}"


def _cdn_dest(path: str) -> Path:
    return _CDN_DIR / path


# ── Step 1: ESM bundle (multi-file Stencil output) ────────────────────────

def download_esm_bundle(force: bool = False) -> Path:
    """Download all @deadlock-api/ui-core ESM bundle files and patch API URLs.

    Stencil outputs multiple chunked JS files plus a CSS file.  We download
    all of them into ``data/ui_lib/`` and rewrite hardcoded CDN URLs in each
    JavaScript file so components fetch from our local proxy routes.
    """
    marker = _LIB_DIR / ".downloaded"
    if marker.exists() and not force:
        log.debug("ESM bundle already cached: %s", _LIB_DIR)
        return _LIB_DIR

    _LIB_DIR.mkdir(parents=True, exist_ok=True)

    # Discover all dist/main/ files via unpkg's ?meta endpoint
    log.info("Fetching ESM bundle file listing from %s", _BUNDLE_META_URL)
    resp = _get_session().get(_BUNDLE_META_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    meta = resp.json()

    for entry in meta.get("files", []):
        filename = entry["path"].split("/")[-1]
        url = _BUNDLE_BASE_URL + filename
        dest = _LIB_DIR / filename

        log.info("Downloading bundle file: %s", filename)
        file_resp = _get_session().get(url, timeout=60)
        file_resp.raise_for_status()

        content = file_resp.content
        # Patch JS files to redirect API/CDN URLs to our local routes
        if filename.endswith(".js"):
            text = content.decode("utf-8")
            text = text.replace(_API_BASE + "/v2", "/dl-api")
            text = text.replace(_CDN_BASE, "/dl-cdn")
            content = text.encode("utf-8")

        dest.write_bytes(content)
        log.debug("  → %s (%d bytes)", dest, len(content))

    marker.write_text("ok")
    log.info("ESM bundle saved and patched (%d files)", len(meta.get("files", [])))
    return dest


# ── Step 2: CDN assets (images, fonts, icons) ─────────────────────────────

def _collect_item_image_urls() -> set[str]:
    """Extract all image URLs from the local items.json API cache."""
    items_path = _DATA_DIR / "api_cache" / "items.json"
    if not items_path.exists():
        log.warning("items.json not found at %s — skipping item images", items_path)
        return set()

    with open(items_path) as f:
        items = json.load(f)

    urls: set[str] = set()
    image_keys = ("image", "image_webp", "shop_image", "shop_image_small", "shop_image_webp")
    for item in items:
        for key in image_keys:
            val = item.get(key)
            if val and isinstance(val, str) and val.startswith(_CDN_BASE) and "panorama:" not in val:
                urls.add(val)
        # Property icons (like cooldown, damage type icons)
        for prop in (item.get("properties") or {}).values():
            if isinstance(prop, dict):
                icon = prop.get("icon")
                if icon and isinstance(icon, str) and icon.startswith(_CDN_BASE) and "panorama:" not in icon:
                    urls.add(icon)
    return urls


def _cdn_relative_path(url: str) -> str:
    """Convert a full CDN URL to a relative path under ui_cache/cdn/."""
    # e.g. https://assets-bucket.deadlock-api.com/assets-api-res/images/items/weapon/foo.webp
    #   → images/items/weapon/foo.webp
    parsed = urlparse(url)
    path = parsed.path
    prefix = "/assets-api-res/"
    idx = path.find(prefix)
    if idx >= 0:
        return path[idx + len(prefix):]
    # Fallback: strip leading slash
    return path.lstrip("/")


def download_cdn_assets(force: bool = False) -> int:
    """Download all CDN assets (images, fonts, icons). Returns count downloaded."""
    # Collect all URLs to download
    relative_paths: list[str] = []
    relative_paths.extend(_SHOP_ASSETS)
    relative_paths.extend(_FONT_FILES)
    relative_paths.extend(_ICON_FILES)

    # Item image URLs from the API cache
    item_urls = _collect_item_image_urls()
    item_paths = {_cdn_relative_path(u): u for u in item_urls}

    count = 0
    # Download known assets
    for rp in relative_paths:
        dest = _cdn_dest(rp)
        if dest.exists() and not force:
            continue
        if _download(_cdn_url(rp), dest):
            count += 1

    # Download item images
    for rp, url in item_paths.items():
        dest = _cdn_dest(rp)
        if dest.exists() and not force:
            continue
        if _download(url, dest):
            count += 1

    log.info(
        "CDN assets: %d downloaded, %d already cached",
        count,
        len(relative_paths) + len(item_paths) - count,
    )
    return count


# ── Step 3: API data for web components ───────────────────────────────────

def download_api_data(force: bool = False) -> None:
    """Download the raw API JSON that the web components expect."""
    endpoints = {
        "items_english.json": f"{_API_BASE}/v2/items?language=english",
        "generic-data.json": f"{_API_BASE}/v2/generic-data",
    }
    _API_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in endpoints.items():
        dest = _API_DIR / filename
        if dest.exists() and not force:
            log.debug("API cache hit: %s", dest)
            continue
        log.info("Downloading API data: %s", url)
        _download(url, dest)


# ── Public API ────────────────────────────────────────────────────────────

def ensure_ui_assets(force: bool = False) -> None:
    """Ensure all UI component assets are downloaded and cached.

    Called at GUI startup after ``ensure_data_available()``.
    Pass ``force=True`` to re-download everything (e.g. on "Refresh Data").
    """
    log.info("Ensuring UI component assets are available (force=%s)", force)
    download_esm_bundle(force=force)
    download_cdn_assets(force=force)
    download_api_data(force=force)
    log.info("UI component assets ready")


def get_lib_dir() -> Path:
    """Return the path to the patched ESM bundle directory."""
    return _LIB_DIR


def get_cdn_dir() -> Path:
    """Return the path to the cached CDN assets directory."""
    return _CDN_DIR


def get_api_dir() -> Path:
    """Return the path to the cached API data directory."""
    return _API_DIR
