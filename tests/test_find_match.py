import cv2
import numpy as np

from clashbot import vision
from clashbot.attack import FindMatchNavigator


def _png(stage):
    image = np.full((72, 128, 3), stage, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


class FakeClient:
    def __init__(self, stages):
        self.stages = iter(stages)

    def screenshot(self):
        return _png(next(self.stages))


class FakeHuman:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, radius=None):
        self.taps.append((x, y, radius))

    def wait(self, *_args):
        pass


class FakeUi:
    @staticmethod
    def _stage(scene):
        return int(scene[0, 0, 0])

    @staticmethod
    def _match(name):
        return vision.Match(name, 20, 20, 30, 20, 1.0)

    def find_menu(self, scene):
        return self._match("menu") if self._stage(scene) == 1 else None

    def find_find_match(self, scene):
        return self._match("find") if self._stage(scene) == 1 else None

    def find_army_confirmation(self, scene):
        return self._match("army") if self._stage(scene) == 2 else None

    def find_confirm_match(self, scene):
        return self._match("confirm") if self._stage(scene) == 2 else None

    def find_opponent_scout(self, scene):
        return self._match("scout") if self._stage(scene) == 3 else None

    def is_home(self, scene):
        return self._stage(scene) == 4


def test_find_match_stops_at_army_confirmation_by_default():
    human = FakeHuman()
    result = FindMatchNavigator(
        FakeClient([1, 2]), FakeUi(), human
    ).find()
    assert result.prepared
    assert not result.opponent_found
    assert len(human.taps) == 1


def test_confirmed_find_match_exits_scout_without_deploying():
    human = FakeHuman()
    result = FindMatchNavigator(
        FakeClient([1, 2, 3, 4]), FakeUi(), human
    ).find(confirm=True, return_home=True)
    assert result.opponent_found
    assert result.returned_home
    assert len(human.taps) == 3
