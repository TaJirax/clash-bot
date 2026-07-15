import cv2
import numpy as np

from clashbot.anti_afk import AntiAfk


def _png():
    ok, encoded = cv2.imencode(".png", np.zeros((72, 128, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


class FakeClient:
    def screenshot(self):
        return _png()


class FakeUi:
    def __init__(self, home):
        self.home = home

    def is_home(self, _scene):
        return self.home


class FakeTouchChooser:
    def point(self, _scene):
        return 50, 40


class FakeHuman:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, radius=None, settle=True):
        self.taps.append((x, y, radius, settle))


def _anti_afk(home):
    human = FakeHuman()
    anti = AntiAfk(FakeClient(), human=human, ui=FakeUi(home))
    anti.safe_touch = FakeTouchChooser()
    return anti, human


def test_anti_afk_touches_only_verified_home_grass():
    anti, human = _anti_afk(True)
    assert anti.tick(log=lambda _message: None)
    assert human.taps == [(50, 40, 5.0, False)]


def test_anti_afk_skips_when_menu_is_open():
    anti, human = _anti_afk(False)
    assert not anti.tick(log=lambda _message: None)
    assert human.taps == []


def test_anti_afk_dry_run_never_taps():
    anti, human = _anti_afk(True)
    assert anti.tick(dry_run=True, log=lambda _message: None)
    assert human.taps == []
