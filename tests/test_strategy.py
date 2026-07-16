from clashbot.loot_planner import EnemyEvidence, Resources
from clashbot.strategy import BaseAttackCoordinator, BaseStatus


def _enemy():
    return EnemyEvidence(Resources(gold=2_000), 3, 2, 1, 1)


def test_coordinator_prioritises_a_verified_available_upgrade():
    decision = BaseAttackCoordinator().decide(
        base=BaseStatus(1, True), player_town_hall=3,
        capacity=Resources(gold=10_000), enemy=_enemy(), army={"goblin": 10},
    )
    assert decision.mode == "manage"


def test_coordinator_farms_only_after_base_work_is_unavailable():
    decision = BaseAttackCoordinator().decide(
        base=BaseStatus(0, False), player_town_hall=3,
        capacity=Resources(gold=10_000), enemy=_enemy(), army={"goblin": 10},
    )
    assert decision.mode == "loot"
