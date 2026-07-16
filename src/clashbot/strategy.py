"""One cohesive decision point for base progress versus loot attacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .loot_planner import AttackPlan, EnemyEvidence, LootPlanner, Resources


@dataclass(frozen=True)
class BaseStatus:
    builders_available: int | None
    upgrade_available: bool | None


@dataclass(frozen=True)
class CycleDecision:
    mode: str
    reason: str
    attack_plan: AttackPlan | None = None


class BaseAttackCoordinator:
    """Prefer upgrades; farm only when base work is verified unavailable."""

    def __init__(self, loot_planner: LootPlanner | None = None):
        self.loot_planner = loot_planner or LootPlanner()

    def decide(self, *, base: BaseStatus, player_town_hall: int | None,
               capacity: Resources | None, enemy: EnemyEvidence,
               army: Mapping[str, int]) -> CycleDecision:
        if base.builders_available is None or base.upgrade_available is None:
            return CycleDecision("wait", "base status is unverified")
        if base.builders_available > 0 and base.upgrade_available:
            return CycleDecision("manage", "verified builder and upgrade are available")
        plan = self.loot_planner.decide(
            player_town_hall=player_town_hall, capacity=capacity,
            enemy=enemy, army=army,
        )
        if plan.attack:
            return CycleDecision("loot", plan.reason, plan)
        return CycleDecision("wait", plan.reason, plan)
