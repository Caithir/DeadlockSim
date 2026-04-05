"""Time-to-Kill calculation engine.

Backward-compatibility wrapper — delegates to :class:`HeroMetrics`.
"""

from __future__ import annotations

from ..models import CombatConfig, HeroStats, TTKResult
from .heroes import HeroMetrics


class TTKCalculator:
    """Backward-compat alias.  Prefer :class:`HeroMetrics`."""

    calculate = staticmethod(HeroMetrics.ttk)
    ttk_curve = staticmethod(HeroMetrics.ttk_curve)
