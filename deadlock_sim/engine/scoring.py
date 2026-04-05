"""Item scoring engine.

Scores candidate items against a baseline build by computing DPS, EHP,
and per-soul deltas.  Supports both a fast analytical mode and a full
simulation mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Build, BuildStats, CombatConfig, HeroStats, Item
from .builds import BuildEngine
from .damage import DamageCalculator
from .simulation import AbilityUse, CombatSimulator, SimConfig, SimSettings


@dataclass
class ScoringConfig:
    """Configuration for item scoring, decoupled from UI globals."""

    sim_settings: SimSettings | None = None
    ability_schedule: list[AbilityUse] = field(default_factory=list)
    custom_item_dps: dict[str, float] = field(default_factory=dict)
    custom_item_ehp: dict[str, float] = field(default_factory=dict)


@dataclass
class ItemScore:
    """All computed metrics for a single candidate item."""

    item_name: str = ""
    # Fast-mode deltas
    dps_delta: float = 0.0
    spirit_dps_delta: float = 0.0
    ehp_delta: float = 0.0
    dps_per_soul: float = 0.0
    ehp_per_soul: float = 0.0
    # Simulation-mode deltas
    sim_dps_delta: float = 0.0
    sim_ehp_delta: float = 0.0
    sim_dps: float = 0.0
    sim_ehp: float = 0.0
    sim_dps_per_soul: float = 0.0
    sim_ehp_per_soul: float = 0.0


class ItemScorer:
    """Score candidate items against a baseline build."""

    @staticmethod
    def score_candidates(
        hero: HeroStats,
        baseline_build: Build,
        candidates: list[Item],
        boons: int = 0,
        mode: str = "fast",
        config: ScoringConfig | None = None,
    ) -> dict[str, ItemScore]:
        """Score each candidate item against *baseline_build*.

        Parameters
        ----------
        hero : HeroStats
            The hero whose build is being optimized.
        baseline_build : Build
            Current build (items already purchased).
        candidates : list[Item]
            Items to evaluate (not yet in the build).
        boons : int
            Current boon level.
        mode : str
            ``"fast"`` — analytical DPS/EHP only (no simulation).
            ``"sim_gun"`` — simulation with weapon only.
            ``"sim_spirit"`` — simulation with abilities only.
            ``"sim_hybrid"`` — simulation with both.
        config : ScoringConfig | None
            Optional advanced settings (sim settings, ability schedule,
            custom DPS/EHP overrides).

        Returns
        -------
        dict[str, ItemScore]
            Mapping of ``item.name`` → score data.
        """
        cfg = config or ScoringConfig()

        if mode == "fast":
            return ItemScorer._score_fast(hero, baseline_build, candidates, boons, cfg)

        return ItemScorer._score_sim(hero, baseline_build, candidates, boons, mode, cfg)

    # ── Fast (analytical) scoring ─────────────────────────────────

    @staticmethod
    def _score_fast(
        hero: HeroStats,
        baseline_build: Build,
        candidates: list[Item],
        boons: int,
        cfg: ScoringConfig,
    ) -> dict[str, ItemScore]:
        cur_stats = BuildEngine.aggregate_stats(baseline_build)
        cur_cfg = BuildEngine.build_to_attacker_config(cur_stats, boons=boons, spirit_gain=hero.spirit_gain)

        cur_gun = DamageCalculator.calculate_bullet(hero, cur_cfg).sustained_dps
        cur_spirit = DamageCalculator.hero_total_spirit_dps(
            hero,
            current_spirit=cur_cfg.current_spirit,
            cooldown_reduction=cur_stats.cooldown_reduction,
            spirit_amp=cur_stats.spirit_amp_pct,
            resist_shred=cur_stats.spirit_resist_shred,
        )
        cur_ehp = _compute_ehp(hero, boons, cur_stats)

        scores: dict[str, ItemScore] = {}
        for item in candidates:
            t_build = Build(items=list(baseline_build.items) + [item])
            t_stats = BuildEngine.aggregate_stats(t_build)
            t_cfg = BuildEngine.build_to_attacker_config(t_stats, boons=boons, spirit_gain=hero.spirit_gain)

            gun_d = DamageCalculator.calculate_bullet(hero, t_cfg).sustained_dps - cur_gun
            spirit_d = DamageCalculator.hero_total_spirit_dps(
                hero,
                current_spirit=t_cfg.current_spirit,
                cooldown_reduction=t_stats.cooldown_reduction,
                spirit_amp=t_stats.spirit_amp_pct,
                resist_shred=t_stats.spirit_resist_shred,
            ) - cur_spirit
            ehp_d = _compute_ehp(hero, boons, t_stats) - cur_ehp

            cost = item.cost or 1
            scores[item.name] = ItemScore(
                item_name=item.name,
                dps_delta=gun_d,
                spirit_dps_delta=spirit_d,
                ehp_delta=ehp_d,
                dps_per_soul=gun_d / cost,
                ehp_per_soul=ehp_d / cost,
            )

        return scores

    # ── Simulation scoring ────────────────────────────────────────

    @staticmethod
    def _score_sim(
        hero: HeroStats,
        baseline_build: Build,
        candidates: list[Item],
        boons: int,
        mode: str,
        cfg: ScoringConfig,
    ) -> dict[str, ItemScore]:
        dummy = HeroStats(name="Dummy Target", base_hp=2500, base_regen=0)

        settings = cfg.sim_settings or SimSettings()
        settings.attacker_boons = boons
        settings.defender_boons = 0

        if mode == "sim_gun":
            settings.ability_uptime = 0.0
        elif mode == "sim_spirit":
            settings.weapon_uptime = 0.0
            settings.ability_uptime = 1.0

        settings.duration = min(settings.duration, 10.0)

        ability_schedule = list(cfg.ability_schedule)

        base_config = SimConfig(
            attacker=hero,
            attacker_build=Build(items=list(baseline_build.items)),
            defender=dummy,
            settings=settings,
            ability_schedule=ability_schedule,
        )
        base_result = CombatSimulator.run(base_config)
        base_dps = base_result.overall_dps

        base_stats = BuildEngine.aggregate_stats(baseline_build)
        base_ehp = _compute_ehp(hero, boons, base_stats)

        scores: dict[str, ItemScore] = {}
        for item in candidates:
            test_items = list(baseline_build.items) + [item]

            test_config = SimConfig(
                attacker=hero,
                attacker_build=Build(items=test_items),
                defender=dummy,
                settings=settings,
                ability_schedule=list(ability_schedule),
            )
            test_result = CombatSimulator.run(test_config)
            test_dps = test_result.overall_dps

            test_stats = BuildEngine.aggregate_stats(Build(items=test_items))
            test_ehp = _compute_ehp(hero, boons, test_stats)

            cost = item.cost or 1
            dps_delta = test_dps - base_dps
            ehp_delta = test_ehp - base_ehp

            dps_delta += cfg.custom_item_dps.get(item.name, 0.0)
            ehp_delta += cfg.custom_item_ehp.get(item.name, 0.0)

            scores[item.name] = ItemScore(
                item_name=item.name,
                sim_dps_delta=dps_delta,
                sim_ehp_delta=ehp_delta,
                sim_dps=test_dps,
                sim_ehp=test_ehp,
                sim_dps_per_soul=dps_delta / cost,
                sim_ehp_per_soul=ehp_delta / cost,
            )

        return scores


# ── Helpers ───────────────────────────────────────────────────────


def _compute_ehp(hero: HeroStats, boons: int, stats: BuildStats) -> float:
    """Compute effective HP from base stats, boons, and build stats."""
    base_hp = (hero.base_hp + hero.hp_gain * boons) * (1.0 + stats.base_hp_pct)
    ehp = base_hp + stats.bonus_hp + stats.bullet_shield + stats.spirit_shield
    if stats.bullet_resist_pct > 0:
        ehp /= (1.0 - min(0.9, stats.bullet_resist_pct))
    if stats.spirit_resist_pct > 0:
        spirit_mult = 1.0 / (1.0 - min(0.9, stats.spirit_resist_pct))
        ehp = ehp * (0.5 + 0.5 * spirit_mult)
    return ehp
