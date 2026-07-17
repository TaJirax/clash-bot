"""Tests for the held-out precision/recall evaluation harness."""

import cv2
import numpy as np

from clashbot.upgrades import BuildingTarget
from scripts.evaluate_building_recognizer import evaluate, match_detections


def test_match_detections_pairs_by_nearest_same_category_within_radius():
    detections = [
        {"category": "town_hall", "x": 100, "y": 100, "score": 0.9},
        {"category": "cannon", "x": 500, "y": 500, "score": 0.8},
    ]
    ground_truth = [
        {"category": "town_hall", "x": 106, "y": 98},
        {"category": "cannon", "x": 900, "y": 900},
    ]

    matched, unmatched_detections, unmatched_truth = match_detections(
        detections, ground_truth, radius=24.0
    )

    assert len(matched) == 1
    assert matched[0][0]["category"] == "town_hall"
    assert unmatched_detections == [detections[1]]
    assert unmatched_truth == [ground_truth[1]]


def test_match_detections_never_pairs_across_categories():
    detections = [{"category": "cannon", "x": 100, "y": 100, "score": 0.9}]
    ground_truth = [{"category": "mortar", "x": 100, "y": 100}]

    matched, unmatched_detections, unmatched_truth = match_detections(
        detections, ground_truth, radius=24.0
    )

    assert matched == []
    assert unmatched_detections == detections
    assert unmatched_truth == ground_truth


class _FakeRecognizer:
    def __init__(self, targets):
        self._targets = targets

    def find(self, scene):
        return self._targets


def test_evaluate_reports_precision_recall_and_exact_count_match(tmp_path):
    image_path = tmp_path / "base1.png"
    cv2.imwrite(str(image_path), np.zeros((16, 16, 3), dtype=np.uint8))
    annotations = [{
        "image": str(image_path),
        "buildings": [
            {"category": "town_hall", "level": 11, "x": 100, "y": 100},
            {"category": "cannon", "level": 5, "x": 300, "y": 300},
        ],
    }]
    recognizer = _FakeRecognizer([
        BuildingTarget(category="town_hall", name="town_hall_lv11", x=102, y=99, score=0.95),
        BuildingTarget(category="cannon", name="cannon_lv5", x=900, y=900, score=0.90),
    ])

    report = evaluate(recognizer, annotations, radius=24.0)

    assert report["categories"]["town_hall"] == {
        "true_positive": 1, "false_positive": 0, "false_negative": 0,
        "precision": 1.0, "recall": 1.0,
    }
    assert report["categories"]["cannon"] == {
        "true_positive": 0, "false_positive": 1, "false_negative": 1,
        "precision": 0.0, "recall": 0.0,
    }
    assert report["exact_count_match_rate"] == 0.0
