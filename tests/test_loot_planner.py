from clashbot.loot_planner import EnemyEvidence, LootPlanner, Resources


def _enemy(**changes):
    values = dict(
        available_loot=Resources(gold=2_000, elixir=500),
        town_hall_level=3,
        defensive_buildings=3,
        reachable_resource_buildings=2,
        exposed_resource_buildings=1,
    )
    values.update(changes)
    return EnemyEvidence(**values)


def test_planner_approves_exposed_loot_with_a_learned_army():
    plan = LootPlanner().decide(
        player_town_hall=3, capacity=Resources(gold=10_000, elixir=10_000),
        enemy=_enemy(), army={"giant": 2, "goblin": 20, "archer": 15},
    )
    assert plan.attack
    assert plan.composition[0].startswith("giants")
    assert any(step.startswith("goblins") for step in plan.composition)


def test_planner_skips_unknown_enemy_facts():
    plan = LootPlanner().decide(
        player_town_hall=3, capacity=Resources(gold=10_000),
        enemy=_enemy(available_loot=None), army={"goblin": 20},
    )
    assert not plan.attack
    assert "unverified" in plan.reason


def test_planner_skips_low_loot_and_high_level_targets():
    planner = LootPlanner()
    low_loot = planner.decide(
        player_town_hall=3, capacity=Resources(gold=10_000),
        enemy=_enemy(available_loot=Resources(gold=100)), army={"goblin": 20},
    )
    high_level = planner.decide(
        player_town_hall=3, capacity=Resources(gold=10_000),
        enemy=_enemy(town_hall_level=5), army={"goblin": 20},
    )
    assert not low_loot.attack and "below" in low_loot.reason
    assert not high_level.attack and "above" in high_level.reason


def test_planner_requires_troop_power_when_verified_defenses_are_stronger():
    planner = LootPlanner()
    enemy = _enemy(defense_power=120)
    weak = planner.decide(
        player_town_hall=3, capacity=Resources(gold=10_000, elixir=10_000),
        enemy=enemy, army={"giant": 2, "goblin": 20}, army_power=90,
    )
    strong = planner.decide(
        player_town_hall=3, capacity=Resources(gold=10_000, elixir=10_000),
        enemy=enemy, army={"giant": 2, "goblin": 20}, army_power=120,
    )
    assert not weak.attack and "exceed troop power" in weak.reason
    assert strong.attack
