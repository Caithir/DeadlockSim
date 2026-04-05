"""Core simulation engine - calculations with no UI dependencies."""

from .builds import BuildEngine, BuildOptimizer
from .comparison import ComparisonEngine
from .damage import DamageCalculator
from .heroes import HeroMetrics
from .primitives import apply_amplifiers, extract_item_damage, resist_after_shred
from .scaling import ScalingCalculator
from .scoring import ItemScore, ItemScorer, ScoringConfig
from .simulation import CombatSimulator, SimConfig, SimResult, SimSettings
from .ttk import TTKCalculator

__all__ = [
    "BuildEngine",
    "BuildOptimizer",
    "CombatSimulator",
    "ComparisonEngine",
    "DamageCalculator",
    "HeroMetrics",
    "ItemScore",
    "ItemScorer",
    "ScalingCalculator",
    "ScoringConfig",
    "SimConfig",
    "SimResult",
    "SimSettings",
    "TTKCalculator",
    "apply_amplifiers",
    "extract_item_damage",
    "resist_after_shred",
]
