"""Human-input tests. A fake AdbClient records gestures instead of calling ADB."""

import math
import random

from clashbot.human import HumanInput, HumanProfile


class FakeClient:
    def __init__(self):
        self.taps = []
        self.swipes = []

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2, duration_ms))


def _human(seed=0, **profile):
    client = FakeClient()
    h = HumanInput(client, profile=HumanProfile(**profile), rng=random.Random(seed))
    return client, h


def test_tap_is_a_real_press_not_instant():
    # A human tap must register as a held touch (swipe with duration),
    # never the instantaneous input tap.
    client, h = _human()
    h.tap(500, 400, settle=False)

    assert client.taps == []
    assert len(client.swipes) == 1
    x1, y1, x2, y2, dur = client.swipes[0]
    assert dur > 0  # finger stayed down for a measurable time


def test_tap_lands_within_radius():
    client, h = _human(tap_radius=7.0)
    target = (500, 400)
    for _ in range(200):
        client.swipes.clear()
        px, py = h.tap(*target, settle=False)
        dist = math.hypot(px - target[0], py - target[1])
        # +1 px slack: the aim is clamped to the radius before coordinates are
        # rounded to whole pixels, which can nudge the landing point out slightly.
        assert dist <= 7.0 + 1.0


def test_taps_are_not_all_identical():
    # Jitter should spread taps out; a bot that hits the same pixel is a tell.
    client, h = _human()
    points = {h.tap(500, 400, settle=False) for _ in range(30)}
    assert len(points) > 1


def test_swipe_endpoints_jitter_around_targets():
    client, h = _human(tap_radius=7.0)
    h.swipe(100, 200, 600, 500, settle=False)
    x1, y1, x2, y2, dur = client.swipes[0]
    assert math.hypot(x1 - 100, y1 - 200) <= 7.0 + 1e-9
    assert math.hypot(x2 - 600, y2 - 500) <= 7.0 + 1e-9
    assert dur > 0
