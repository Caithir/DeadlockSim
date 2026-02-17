"""Client for the Deadlock Assets API (assets.deadlock-api.com).

Fetches hero and item data from the API and caches it locally as JSON files.
Data is only refreshed when the user explicitly requests it.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

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
    resp = requests.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_items(language: str = "english") -> list[dict]:
    """Fetch all items (abilities, weapons, upgrades) from the API."""
    url = f"{BASE_URL}/v2/items"
    params = {"language": language}
    resp = requests.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


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


def load_cache(name: str):
    """Load cached data. Returns None if cache doesn't exist."""
    path = _cache_path(name)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def refresh_all_data(language: str = "english") -> dict:
    """Fetch all data from the API and save to local cache.

    Returns a summary dict with counts.
    """
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
            except requests.RequestException:
                pass
    save_cache("hero_items", hero_items)

    return {
        "heroes": len(heroes),
        "items": len(items),
        "abilities": len(abilities),
        "weapons": len(weapons),
        "upgrades": len(upgrades),
    }


def is_cache_available() -> bool:
    """Check if cached data exists."""
    return _cache_path("heroes").exists() and _cache_path("items").exists()
