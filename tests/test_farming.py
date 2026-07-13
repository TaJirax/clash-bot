"""Collector tests. A fake client serves a synthetic scene; no ADB/emulator."""

import cv2
import numpy as np

from clashbot.farming import Collector, INFO_PANEL_FRAC


def _patch(size=30):
    grad = np.linspace(0, 255, size).astype(np.uint8)
    return np.stack([np.tile(grad, (size, 1))] * 3, axis=-1)  # textured square


def _scene_png(positions, w=1280, h=720, patch_size=30):
    scene = np.full((h, w, 3), 30, dtype=np.uint8)
    p = _patch(patch_size)
    for x, y in positions:
        scene[y:y + patch_size, x:x + patch_size] = p
    ok, buf = cv2.imencode(".png", scene)
    assert ok
    return buf.tobytes()


def _panel_center(w=1280, h=720):
    fx1, fy1, fx2, fy2 = INFO_PANEL_FRAC
    return int((fx1 + fx2) / 2 * w), int((fy1 + fy2) / 2 * h)


class FakeClient:
    def __init__(self, png):
        self._png = png
        self.swipes = []

    def screenshot(self):
        return self._png

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2, duration_ms))


def _templates_dir(tmp_path):
    cv2.imwrite(str(tmp_path / "collect_test.png"), _patch())
    return str(tmp_path)


def test_finds_bubble_outside_panel_and_ignores_one_inside(tmp_path):
    # one patch in open base, one centred in the info-panel band.
    pcx, pcy = _panel_center()
    png = _scene_png([(100, 100), (pcx - 15, pcy - 15)])
    client = FakeClient(png)

    collector = Collector(client, templates_dir=_templates_dir(tmp_path), threshold=0.9)
    bubbles = collector.sweep(dry_run=True).collected

    assert len(bubbles) == 1
    assert abs(bubbles[0].center[0] - 115) <= 2


def test_exclude_none_keeps_panel_match(tmp_path):
    pcx, pcy = _panel_center()
    png = _scene_png([(100, 100), (pcx - 15, pcy - 15)])
    client = FakeClient(png)

    collector = Collector(client, templates_dir=_templates_dir(tmp_path),
                          threshold=0.9, exclude=None)
    assert collector.sweep(dry_run=True).count == 2


def test_detects_at_higher_resolution(tmp_path):
    # Template authored at 30px (1280x720). At 1920x1080 the emulator renders
    # the bubble at 1.5x (45px); the collector must scale the template to match
    # and report coordinates in the 1080p space.
    png = _scene_png([(300, 200)], w=1920, h=1080, patch_size=45)
    client = FakeClient(png)

    collector = Collector(client, templates_dir=_templates_dir(tmp_path), threshold=0.9)
    bubbles = collector.sweep(dry_run=True).collected

    assert len(bubbles) == 1
    cx, cy = bubbles[0].center
    assert abs(cx - 322) <= 3 and abs(cy - 222) <= 3  # 300+45/2, 200+45/2


def test_panel_exclusion_scales_with_resolution(tmp_path):
    # The info-panel band is fractional, so a panel-region match is still
    # excluded at 1920x1080.
    pcx, pcy = _panel_center(1920, 1080)
    png = _scene_png([(300, 200), (pcx - 22, pcy - 22)], w=1920, h=1080, patch_size=45)
    client = FakeClient(png)

    collector = Collector(client, templates_dir=_templates_dir(tmp_path), threshold=0.9)
    assert collector.sweep(dry_run=True).count == 1  # panel one dropped


def test_sweep_taps_each_bubble(tmp_path):
    png = _scene_png([(100, 100), (300, 200)])
    client = FakeClient(png)
    collector = Collector(client, templates_dir=_templates_dir(tmp_path), threshold=0.9)

    result = collector.sweep(dry_run=False)

    assert result.count == 2
    assert len(client.swipes) == 2  # one human-tap (press) per bubble
