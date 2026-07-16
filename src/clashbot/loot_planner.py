"""Conservative, evidence-driven decisions for loot attacks.

This module deliberately separates *planning* from screen input.  An attack is
approved only after vision has supplied all of the facts below; missing or
ambiguous facts always produce a skip decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Resources:
    gold: int = 0
    elixir: int = 0
    dark_elixir: int = 0

    def fraction_of(self, capacity: "Resources") -> float:
        fractions = [
            self.gold / capacity.gold if capacity.gold > 0 else 0.0,
            self.elixir / capacity.elixir if capacity.elixir > 0 else 0.0,
            self.dark_elixir / capacity.dark_elixir if capacity.dark_elixir > 0 else 0.0,
        ]
        return max(fractions)


@dataclass(frozen=True)
class EnemyEvidence:
    """Facts that must be visually verified before a loot attack is allowed."""

    available_loot: Resources | None
    town_hall_level: int | None
    defensive_buildings: int | None
    reachable_resource_buildings: int | None
    exposed_resource_buildings: int | None


@dataclass(frozen=True)
class LootPolicy:
    minimum_capacity_fraction: float = 0.20
    max_town_hall_advantage: int = 1
    max_defenses_for_loot: int = 5
    min_reachable_resources: int = 1
    min_exposed_resources: int = 1


@dataclass(frozen=True)
class AttackPlan:
    attack: bool
    reason: str
    composition: tuple[str, ...] = ()


# Troop purpose is intentionally explicit instead of treating all troop cards
# as interchangeable clicks.  New troops are added only after their battle-bar
# cards and behaviour have been learned.
TROOP_ROLES = {
    "barbarian": "cheap melee cleanup and distraction",
    "archer": "ranged cleanup behind a tank",
    "giant": "targets defences and absorbs defensive fire",
    "goblin": "prioritises resource buildings and is the primary loot unit",
}


class LootPlanner:
    def __init__(self, policy: LootPolicy | None = None):
        self.policy = policy or LootPolicy()

    def decide(self, *, player_town_hall: int | None, capacity: Resources | None,
               enemy: EnemyEvidence, army: Mapping[str, int]) -> AttackPlan:
        if player_town_hall is None or capacity is None:
            return AttackPlan(False, "skip: player Town Hall level or resource capacity is unverified")
        if enemy.available_loot is None:
            return AttackPlan(False, "skip: available loot is unverified")
        if enemy.town_hall_level is None:
            return AttackPlan(False, "skip: enemy Town Hall level is unverified")
        if enemy.defensive_buildings is None:
            return AttackPlan(False, "skip: enemy defenses are unverified")
        if enemy.reachable_resource_buildings is None or enemy.exposed_resource_buildings is None:
            return AttackPlan(False, "skip: resource reachability is unverified")

        if enemy.available_loot.fraction_of(capacity) < self.policy.minimum_capacity_fraction:
            return AttackPlan(False, "skip: loot is below 20% of verified storage capacity")
        if enemy.town_hall_level > player_town_hall + self.policy.max_town_hall_advantage:
            return AttackPlan(False, "skip: enemy Town Hall is too far above the player")
        if enemy.defensive_buildings > self.policy.max_defenses_for_loot:
            return AttackPlan(False, "skip: too many verified defenses for a loot attack")
        if enemy.reachable_resource_buildings < self.policy.min_reachable_resources:
            return AttackPlan(False, "skip: no reachable resource building")
        if enemy.exposed_resource_buildings < self.policy.min_exposed_resources:
            return AttackPlan(False, "skip: resource buildings are not exposed")

        composition: list[str] = []
        if army.get("giant", 0):
            composition.append("giants first to draw defense fire")
        if army.get("goblin", 0):
            composition.append("goblins onto exposed resource buildings")
        if army.get("archer", 0):
            composition.append("archers behind tanks for cleanup")
        if army.get("barbarian", 0):
            composition.append("barbarians for cheap cleanup/distraction")
        if not composition:
            return AttackPlan(False, "skip: no learned deployable army composition")
        return AttackPlan(True, "attack: verified loot target meets policy", tuple(composition))
