import cv2
import numpy as np

from clashbot.attack import AttackNavigator, AttackUi


def _template(color):
    image = np.full((30, 50, 3), color, dtype=np.uint8)
    image[5:25, 10:40] = tuple(min(255, value + 60) for value in color)
    return image


def _png(image):
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


class FakeClient:
    def __init__(self, images):
        self.images = iter(images)

    def screenshot(self):
        return _png(next(self.images))


class FakeHuman:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, radius=None):
        self.taps.append((x, y, radius))

    def wait(self, *_args):
        pass


def test_attack_navigator_opens_only_from_verified_button():
    button, menu = _template((20, 90, 160)), _template((80, 40, 20))
    home = np.zeros((720, 1280, 3), dtype=np.uint8)
    home[620:650, 50:100] = button
    opened = np.zeros_like(home)
    opened[40:70, 80:130] = menu
    human = FakeHuman()

    result = AttackNavigator(
        FakeClient([home, opened]), AttackUi(button, menu), human
    ).open()

    assert result.opened
    assert len(human.taps) == 1


def test_attack_navigator_does_not_tap_without_button():
    button, menu = _template((20, 90, 160)), _template((80, 40, 20))
    human = FakeHuman()
    result = AttackNavigator(
        FakeClient([np.zeros((720, 1280, 3), dtype=np.uint8)]),
        AttackUi(button, menu), human,
    ).open()
    assert not result.opened
    assert human.taps == []
