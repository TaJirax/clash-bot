import numpy as np

from clashbot.base_management import (
    BaseManagementInspector, BaseManagementStatus, plan_base_management,
)


class Buildings:
    def find(self, _scene):
        return [object(), object()]


class Menus:
    def classify(self, _scene):
        return None


def test_management_status_never_infers_untrained_base_facts():
    inspector = BaseManagementInspector.__new__(BaseManagementInspector)
    inspector.buildings = Buildings()
    inspector.menus = Menus()
    inspector.builder_free = np.zeros((2, 2, 3), dtype=np.uint8)
    inspector.research_ready = np.zeros((2, 2, 3), dtype=np.uint8)
    inspector._find = lambda *_args: False
    inspector.boosts = type("Boosts", (), {"find": lambda *_args: []})()
    status = inspector.inspect(np.zeros((20, 20, 3), dtype=np.uint8))
    assert status.recognized_buildings == 2
    assert status.builders_available is None
    assert status.research_available is None
    assert status.upgrade_affordable is None


def _status(**changes):
    values = dict(
        recognized_buildings=20, menu_state=None, builders_available=0,
        research_available=False, upgrade_affordable=False, boost_auras=0,
        next_step="", collection_pending=False, army_ready=True,
    )
    values.update(changes)
    return BaseManagementStatus(**values)


def test_management_plan_prioritizes_research_and_upgrades_before_attack():
    assert plan_base_management(_status(research_available=True)).action == "research"
    assert plan_base_management(_status(builders_available=1, upgrade_affordable=True)).action == "upgrade"
    assert plan_base_management(_status()).action == "attack"


def test_management_plan_stays_fail_closed_when_state_is_unknown():
    plan = plan_base_management(_status(builders_available=None))
    assert plan.action == "inspect"
    assert "incomplete" in plan.reason
