"""Boon/level scaling calculations.

Backward-compatibility wrapper — delegates to :class:`HeroMetrics`.
"""

from __future__ import annotations

from ..models import HeroStats, ScalingSnapshot
from .heroes import HeroMetrics


class ScalingCalculator:
    """Backward-compat alias.  Prefer :class:`HeroMetrics`."""

    snapshot_at_boon = staticmethod(HeroMetrics.snapshot)
    scaling_curve = staticmethod(HeroMetrics.scaling_curve)
    growth_percentage = staticmethod(HeroMetrics.growth_percentage)
    boon_item_scaling = staticmethod(HeroMetrics.item_boon_scaling)
