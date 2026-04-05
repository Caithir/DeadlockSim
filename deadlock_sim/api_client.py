"""Client for the Deadlock Assets API (assets.deadlock-api.com).

Fetches hero and item data from the API and caches it locally as JSON files.
Data is only refreshed when the user explicitly requests it, or automatically
on first run when no cache exists.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://assets.deadlock-api.com"
_CACHE_DIR = Path(__file__).parent.parent / "data" / "api_cache"

# Timeout for API requests (seconds)
_TIMEOUT = 30


def _ensure_cache_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(name: str) -> Path:
    return _CACHE_DIR / f"{name}.json"


def fetch_heroes(language: str = "english") -> list[dict]:
    """Fetch all heroes from the API."""
    url = f"{BASE_URL}/v2/heroes"
    params = {"language": language}
    log.info("Fetching heroes from %s", url)
    resp = requests.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    log.info("Fetched %d heroes", len(data))
    return data


def fetch_items(language: str = "english") -> list[dict]:
    """Fetch all items (abilities, weapons, upgrades) from the API."""
    url = f"{BASE_URL}/v2/items"
    params = {"language": language}
    log.info("Fetching items from %s", url)
    resp = requests.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    log.info("Fetched %d items", len(data))
    return data


def fetch_items_by_hero(hero_id: int, language: str = "english") -> list[dict]:
    """Fetch all items for a specific hero."""
    url = f"{BASE_URL}/v2/items/by-hero-id/{hero_id}"
    params = {"language": language}
    resp = requests.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def save_cache(name: str, data) -> None:
    """Save API response data to local cache."""
    _ensure_cache_dir()
    path = _cache_path(name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log.debug("Saved cache: %s (%d bytes)", path, path.stat().st_size)


def load_cache(name: str):
    """Load cached data. Returns None if cache doesn't exist."""
    path = _cache_path(name)
    if not path.exists():
        log.debug("Cache miss: %s", path)
        return None
    with open(path) as f:
        data = json.load(f)
    log.debug("Cache hit: %s", path)
    return data


def refresh_all_data(language: str = "english") -> dict:
    """Fetch all data from the API and save to local cache.

    Returns a summary dict with counts.
    """
    log.info("Starting full data refresh from API")
    heroes = fetch_heroes(language)
    save_cache("heroes", heroes)

    items = fetch_items(language)
    save_cache("items", items)

    # Separate items by type for easier access
    abilities = [i for i in items if i.get("type") == "ability"]
    weapons = [i for i in items if i.get("type") == "weapon"]
    upgrades = [i for i in items if i.get("type") == "upgrade"]

    save_cache("abilities", abilities)
    save_cache("weapons", weapons)
    save_cache("upgrades", upgrades)

    # Fetch items per hero for ability mapping
    hero_items = {}
    for hero in heroes:
        hero_id = hero.get("id")
        if hero_id is not None:
            try:
                h_items = fetch_items_by_hero(hero_id, language)
                hero_items[str(hero_id)] = h_items
            except requests.RequestException as exc:
                log.warning("Failed to fetch items for hero %s: %s", hero_id, exc)
    save_cache("hero_items", hero_items)

    summary = {
        "heroes": len(heroes),
        "items": len(items),
        "abilities": len(abilities),
        "weapons": len(weapons),
        "upgrades": len(upgrades),
    }
    log.info("Data refresh complete: %s", summary)
    return summary


def is_cache_available() -> bool:
    """Check if cached data exists."""
    return _cache_path("heroes").exists() and _cache_path("items").exists()


def ensure_data_available(language: str = "english") -> None:
    """Fetch and cache API data if not already cached.

    Raises requests.RequestException if the API is unreachable and no
    cache exists.
    """
    if not is_cache_available():
        log.info("No local cache found — fetching data from API")
        refresh_all_data(language)
    else:
        log.debug("Using existing data cache")
