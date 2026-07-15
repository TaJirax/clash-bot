import cv2
import numpy as np

from clashbot.navigation import BaseMapper, MappedBuilding, estimate_translation


def test_estimate_translation_tracks_shifted_map_content():
    rng = np.random.default_rng(5)
    before = rng.integers(0, 256, (300, 500, 3), dtype=np.uint8)
    transform = np.float32([[1, 0, 24], [0, 1, -17]])
    after = cv2.warpAffine(before, transform, (500, 300))
    dx, dy, response = estimate_translation(before, after)
    assert abs(dx - 24) < 2
    assert abs(dy + 17) < 2
    assert response > 0.2


def test_map_merge_deduplicates_same_category_in_world_coordinates():
    buildings = [MappedBuilding("gold_mine", "mine", 100, 100, 0.8, 1.0, 1, 100, 100)]
    newer = MappedBuilding("gold_mine", "mine", 112, 107, 0.9, 1.0, 2, 200, 200)
    BaseMapper._merge(buildings, newer)
    assert len(buildings) == 1
    assert buildings[0].score == 0.9


def test_map_merge_keeps_different_categories_at_same_location():
    buildings = [MappedBuilding("gold_mine", "mine", 100, 100, 0.8, 1.0, 1, 100, 100)]
    other = MappedBuilding("town_hall", "th", 100, 100, 0.9, 1.0, 2, 200, 200)
    BaseMapper._merge(buildings, other)
    assert len(buildings) == 2
