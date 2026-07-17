"""Tests for the fail-closed resource-counter reader."""

import cv2
import numpy as np

from clashbot import vision
from clashbot.resources import ResourceReader, ROWS


def test_reads_exact_values_from_live_reference_frame():
    scene = vision.load("assets/templates/base_live_zoom076.png")
    reading = ResourceReader(unknown_dir=None).read(scene)
    assert reading.gold == 51527
    assert reading.elixir == 158097
    assert reading.gems == 4
    assert reading.known() == {"gold": 51527, "elixir": 158097, "gems": 4}


def _scene_with_gold_glyphs(*glyphs: np.ndarray) -> np.ndarray:
    scene = np.zeros((720, 1280, 3), dtype=np.uint8)
    fx1, fy1, _fx2, _fy2 = ROWS["gold"]
    x = int(fx1 * 1280) + 30
    y = int(fy1 * 720) + 22
    for glyph in glyphs:
        h, w = glyph.shape[:2]
        scene[y:y + h, x:x + w] = cv2.cvtColor(glyph, cv2.COLOR_GRAY2BGR)
        x += w + 4
    return scene


def test_unknown_glyph_between_digits_fails_closed(tmp_path):
    reader = ResourceReader(unknown_dir=tmp_path / "unknown")
    five = cv2.imread("assets/templates/digits/5.png", cv2.IMREAD_GRAYSCALE)
    # A solid unfamiliar block with digit-like proportions between two fives.
    blob = np.full((five.shape[0], 10), 255, dtype=np.uint8)
    scene = _scene_with_gold_glyphs(five, blob, five)
    reading = reader.read(scene)
    assert reading.gold is None
    assert list((tmp_path / "unknown").glob("gold_*.png"))


def test_any_unknown_glyph_fails_closed_even_at_the_edge(tmp_path):
    reader = ResourceReader(unknown_dir=tmp_path / "unknown")
    five = cv2.imread("assets/templates/digits/5.png", cv2.IMREAD_GRAYSCALE)
    four = cv2.imread("assets/templates/digits/4.png", cv2.IMREAD_GRAYSCALE)
    blob = np.full((five.shape[0], 10), 255, dtype=np.uint8)
    scene = _scene_with_gold_glyphs(blob, five, four)
    assert reader.read(scene).gold is None


def test_an_oversized_gap_means_a_hidden_digit_and_fails_closed(tmp_path):
    reader = ResourceReader(unknown_dir=tmp_path / "unknown")
    five = cv2.imread("assets/templates/digits/5.png", cv2.IMREAD_GRAYSCALE)
    scene = np.zeros((720, 1280, 3), dtype=np.uint8)
    fx1, fy1, _fx2, _fy2 = ROWS["gold"]
    x = int(fx1 * 1280) + 30
    y = int(fy1 * 720) + 22
    h, w = five.shape[:2]
    bgr = cv2.cvtColor(five, cv2.COLOR_GRAY2BGR)
    scene[y:y + h, x:x + w] = bgr
    scene[y:y + h, x + w + 30:x + 2 * w + 30] = bgr
    assert reader.read(scene).gold is None


def test_empty_screen_reads_nothing():
    reading = ResourceReader(unknown_dir=None).read(
        np.zeros((720, 1280, 3), dtype=np.uint8)
    )
    assert reading.known() == {}
