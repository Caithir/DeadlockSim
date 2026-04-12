"""Screen-capture build import using OpenCV template matching.

Captures a frame from the user's screen (via browser getDisplayMedia),
then uses multi-scale template matching against the local item icon PNGs
to detect which items are present in the Deadlock buy menu / build UI.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

# ── Result dataclass ───────────────────────────────────────────────

@dataclass
class ImportMatch:
    """A single item detected in the screenshot."""
    item_name: str
    confidence: float
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


@dataclass
class ImportResult:
    """Full result of a build import scan."""
    matches: list[ImportMatch] = field(default_factory=list)
    screenshot_width: int = 0
    screenshot_height: int = 0
    error: str = ""


# ── Template cache ─────────────────────────────────────────────────

_templates: dict[str, np.ndarray] = {}  # item_name -> grayscale template


def _load_templates(
    image_dir: Path,
    item_image_map: dict[str, str],
) -> dict[str, np.ndarray]:
    """Load and cache item icon templates as grayscale images."""
    global _templates
    if _templates:
        return _templates

    for item_name, filename in item_image_map.items():
        filepath = image_dir / filename
        if not filepath.exists():
            continue
        img = cv2.imread(str(filepath), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        # Convert to grayscale, handling RGBA
        if len(img.shape) == 3 and img.shape[2] == 4:
            # RGBA — use alpha channel to mask
            gray = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
        elif len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        _templates[item_name] = gray

    log.info("Loaded %d item templates from %s", len(_templates), image_dir)
    return _templates


# ── Core matching ──────────────────────────────────────────────────

class BuildImporter:
    """Detects item icons in a screenshot using multi-scale template matching."""

    # Scales to test — covers common game resolutions vs template size
    SCALES = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0]

    # Confidence threshold for a match
    CONFIDENCE_THRESHOLD = 0.80

    # Minimum distance between matches of the same item (pixels at source scale)
    MIN_MATCH_DISTANCE = 30

    @staticmethod
    def decode_screenshot(data_url: str) -> np.ndarray | None:
        """Decode a base64 data URL (from canvas.toDataURL) to an OpenCV image."""
        try:
            # Strip "data:image/png;base64," prefix
            if "," in data_url:
                data_url = data_url.split(",", 1)[1]
            raw = base64.b64decode(data_url)
            arr = np.frombuffer(raw, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return img
        except Exception as exc:
            log.error("Failed to decode screenshot: %s", exc)
            return None

    @staticmethod
    def find_items(
        screenshot: np.ndarray,
        templates: dict[str, np.ndarray],
        *,
        confidence_threshold: float = 0.80,
        scales: list[float] | None = None,
    ) -> ImportResult:
        """Run multi-scale template matching on a screenshot.

        Returns ImportResult with all matched items above the confidence threshold.
        Each item name appears at most once (highest confidence wins).
        """
        if scales is None:
            scales = BuildImporter.SCALES

        h_img, w_img = screenshot.shape[:2]
        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)

        result = ImportResult(screenshot_width=w_img, screenshot_height=h_img)

        # Track best match per item name
        best: dict[str, ImportMatch] = {}

        for item_name, tmpl in templates.items():
            th, tw = tmpl.shape[:2]
            best_conf = 0.0
            best_loc = (0, 0)
            best_scale = 1.0

            for scale in scales:
                new_w = int(tw * scale)
                new_h = int(th * scale)
                if new_w < 8 or new_h < 8:
                    continue
                if new_w > w_img or new_h > h_img:
                    continue

                resized = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(gray_screen, resized, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                if max_val > best_conf:
                    best_conf = max_val
                    best_loc = max_loc
                    best_scale = scale

            if best_conf >= confidence_threshold:
                match = ImportMatch(
                    item_name=item_name,
                    confidence=round(best_conf, 4),
                    x=best_loc[0],
                    y=best_loc[1],
                    w=int(tw * best_scale),
                    h=int(th * best_scale),
                )
                # Keep only the best match per item name
                existing = best.get(item_name)
                if existing is None or match.confidence > existing.confidence:
                    best[item_name] = match

        # Sort by confidence descending
        result.matches = sorted(best.values(), key=lambda m: -m.confidence)
        return result

    @staticmethod
    def import_from_data_url(
        data_url: str,
        image_dir: Path,
        item_image_map: dict[str, str],
        *,
        confidence_threshold: float = 0.80,
    ) -> ImportResult:
        """Full pipeline: decode screenshot -> load templates -> match items."""
        screenshot = BuildImporter.decode_screenshot(data_url)
        if screenshot is None:
            return ImportResult(error="Failed to decode screenshot image.")

        templates = _load_templates(image_dir, item_image_map)
        if not templates:
            return ImportResult(error="No item templates found. Check data/images/items/.")

        return BuildImporter.find_items(
            screenshot,
            templates,
            confidence_threshold=confidence_threshold,
        )
