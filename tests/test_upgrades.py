"""Upgrade recognition/state-machine tests; no emulator is required."""

import random
from pathlib import Path

import cv2
import numpy as np

from clashbot import vision
from clashbot.upgrades import BuildingTarget, SafeIdleTouch, UpgradeBot, UpgradeUi
from clashbot.upgrades import BuildingRecognizer, ReferenceCatalog


def _png(image):
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return buf.tobytes()


def test_resource_confirm_only_accepts_large_lower_green_button():
    scene = np.full((720, 1280, 3), 30, dtype=np.uint8)
    scene[30:60, 1000:1030] = (50, 190, 50)
    scene[570:635, 535:745] = (45, 180, 55)

    match = UpgradeUi.find_resource_confirm(scene)

    assert match is not None
    assert 630 <= match.center[0] <= 650
    assert 590 <= match.center[1] <= 615


def test_resource_confirm_rejects_scene_without_button():
    scene = np.full((720, 1280, 3), 30, dtype=np.uint8)
    assert UpgradeUi.find_resource_confirm(scene) is None


def test_safe_idle_touch_chooses_uniform_grass_inside_play_area():
    scene = np.full((720, 1280, 3), (45, 145, 85), dtype=np.uint8)
    scene[220:500, 350:900] = (40, 40, 180)
    chooser = SafeIdleTouch(random.Random(4))

    point = chooser.point(scene)

    assert point is not None
    x, y = point
    assert int(0.13 * 1280) <= x < int(0.84 * 1280)
    assert int(0.13 * 720) <= y < int(0.77 * 720)
    assert not (350 <= x < 900 and 220 <= y < 500)


class FakeClient:
    def __init__(self, image):
        self.data = _png(image)
        self.backs = 0

    def screenshot(self):
        return self.data

    def back(self):
        self.backs += 1


class FakeHuman:
    def __init__(self):
        self.taps = []
        self.waits = 0

    def tap(self, x, y, radius=None, settle=True):
        self.taps.append((x, y, radius, settle))
        return x, y

    def wait(self, *args, **kwargs):
        self.waits += 1


class FakeRecognizer:
    def find(self, _scene):
        # Deliberately backwards: UpgradeBot must impose PRIORITY.
        return [
            BuildingTarget("gold_storage", "storage", 800, 300, 0.95),
            BuildingTarget("town_hall", "th", 600, 300, 0.90),
        ]


class FakeIdle:
    def point(self, _scene):
        return 200, 200


class SuccessfulUi:
    def __init__(self):
        self.confirm_calls = 0

    def find_hammer(self, _scene):
        return vision.Match("hammer", 450, 550, 60, 60, 0.9)

    def find_resource_confirm(self, _scene):
        self.confirm_calls += 1
        if self.confirm_calls in (1, 3):
            return vision.Match("confirm", 550, 570, 180, 60, 0.8)
        return None


def _bot(image, ui):
    bot = UpgradeBot.__new__(UpgradeBot)
    bot.client = FakeClient(image)
    bot.rng = random.Random(0)
    bot.human = FakeHuman()
    bot.recognizer = FakeRecognizer()
    bot.ui = ui
    bot.idle = FakeIdle()
    bot._known = {}
    return bot


def test_scan_uses_priority_and_never_backs_from_successful_home_screen():
    scene = np.full((720, 1280, 3), (45, 145, 85), dtype=np.uint8)
    bot = _bot(scene, SuccessfulUi())

    result = bot.scan_once(log=lambda _message: None)

    assert [target.category for target in result.attempted] == ["town_hall", "gold_storage"]
    assert bot.client.backs == 0
    assert len(bot.human.taps) == 8


class ModalUi:
    def find_hammer(self, _scene):
        return vision.Match("hammer", 450, 550, 60, 60, 0.9)

    def find_resource_confirm(self, _scene):
        return vision.Match("confirm_or_offer", 550, 570, 180, 60, 0.8)


def test_scan_backs_out_when_confirm_leaves_a_modal_open():
    scene = np.full((720, 1280, 3), (45, 145, 85), dtype=np.uint8)
    bot = _bot(scene, ModalUi())

    bot.scan_once(log=lambda _message: None)

    assert bot.client.backs == 2
    assert len(bot.human.taps) == 6


def test_dry_run_only_takes_screenshot_and_reports_counts():
    scene = np.full((720, 1280, 3), (45, 145, 85), dtype=np.uint8)
    bot = _bot(scene, SuccessfulUi())

    result = bot.scan_once(dry_run=True, log=lambda _message: None)

    assert result.found == {"town_hall": 1, "gold_storage": 1}
    assert bot.human.taps == []


def test_live_base_catalog_recognizes_all_configured_categories():
    """Each reference scene must retain coverage for templates sourced from it."""
    catalog = ReferenceCatalog("assets/buildings.json")
    for source in ("base_now.png", "assets/templates/base_current_live.png"):
        resolved = str(Path(source).resolve())
        expected = {
            spec.category for spec in catalog.specs if spec.source == resolved
        }
        found = {
            target.category
            for target in BuildingRecognizer(catalog).find(vision.load(source))
        }

        assert expected <= found


def test_custom_upgrade_priority_controls_target_order():
    scene = np.full((720, 1280, 3), (45, 145, 85), dtype=np.uint8)
    bot = _bot(scene, SuccessfulUi())
    bot.priority = ("gold_storage", "town_hall")

    targets = bot._targets(scene)

    assert [target.category for target in targets] == ["gold_storage", "town_hall"]
