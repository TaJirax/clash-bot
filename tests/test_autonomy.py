from types import SimpleNamespace

import cv2
import numpy as np

from clashbot.autonomy import AutonomousBaseScanner, find_connection_retry
from clashbot.upgrades import BuildingTarget


class FakeClient:
    def __init__(self):
        self.scene = np.full((180, 320, 3), (70, 150, 65), dtype=np.uint8)

    def screenshot(self):
        ok, encoded = cv2.imencode(".png", self.scene)
        assert ok
        return encoded.tobytes()

    def tap(self, _x, _y):
        pass


class FakeRecognizer:
    def find(self, _scene):
        return [BuildingTarget("cannon", "cannon_3", 150, 90, 0.9)]


class FakePan:
    def pan(self, direction):
        return SimpleNamespace(verified=True, direction=direction)


class FakeZoom:
    def __init__(self):
        self.calls = 0

    def adjust(self, direction):
        self.calls += 1
        return SimpleNamespace(verified=True, direction=direction)


class FakeFanKit:
    def assets_for(self, category):
        return (1, 2) if category == "cannon" else ()

    def levels_for(self, category):
        return (1, 2, 3) if category == "cannon" else ()


class FakeAssetCatalog:
    class Record:
        def __init__(self, role, level):
            self.role, self.level = role, level

    def find(self, category, *, roles=None):
        assert category == "cannon"
        assert roles == {"labelled_reference", "vector_composition"}
        return (self.Record("labelled_reference", 3), self.Record("vector_composition", 4))


def test_autonomous_scan_captures_and_uses_zoom_pan_recovery(tmp_path):
    zoom = FakeZoom()
    scanner = AutonomousBaseScanner(
        FakeClient(),
        FakeRecognizer(),
        pan=FakePan(),
        zoom=zoom,
        fankit=FakeFanKit(),
        root=tmp_path,
        sleep=lambda _seconds: None,
        is_home=lambda _scene: True,
    )

    report = scanner.run("test", route=("right",), min_detections=2, min_categories=2)

    assert zoom.calls == 2
    assert len(report.views) == 4
    assert report.counts == {"cannon": 1}
    assert report.reference_assets == {"cannon": 2}
    assert report.reference_levels == {"cannon": (1, 2, 3)}
    assert (tmp_path / "test" / "report.json").is_file()


def test_autonomous_scan_uses_unified_asset_catalog_when_available(tmp_path):
    scanner = AutonomousBaseScanner(
        FakeClient(), FakeRecognizer(), pan=FakePan(), fankit=FakeFanKit(),
        asset_catalog=FakeAssetCatalog(), root=tmp_path, sleep=lambda _seconds: None,
        is_home=lambda _scene: True,
    )

    report = scanner.run("catalog", route=(), min_detections=1, min_categories=1)

    assert report.reference_assets == {"cannon": 2}
    assert report.reference_levels == {"cannon": (3, 4)}
    assert report.asset_roles == {"cannon": {"labelled_reference": 1, "vector_composition": 1}}


def test_connection_retry_requires_dark_modal_and_cyan_action():
    scene = np.full((720, 1280, 3), (70, 150, 65), dtype=np.uint8)
    cv2.rectangle(scene, (248, 242), (1031, 478), (30, 32, 33), -1)
    cv2.putText(
        scene, "TRY AGAIN", (284, 445), cv2.FONT_HERSHEY_SIMPLEX,
        0.65, (245, 220, 180), 2, cv2.LINE_AA,
    )

    point = find_connection_retry(scene)

    assert point is not None
    assert 280 <= point[0] <= 410
    assert 420 <= point[1] <= 455
    assert find_connection_retry(np.full_like(scene, (70, 150, 65))) is None
