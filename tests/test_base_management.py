import numpy as np

from clashbot.base_management import BaseManagementInspector


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
