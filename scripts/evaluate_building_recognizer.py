"""Measure BuildingRecognizer precision/recall against held-out screenshots.

Held-out annotations live under assets/eval/held_out/ (see
scripts/label_buildings.py and its README for the schema). Nothing in this
script is used for training; it only scores the existing recognizer.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from clashbot import vision
from clashbot.asset_catalog import AssetCatalog
from clashbot.upgrades import BuildingRecognizer, ReferenceCatalog


def load_annotations(held_out_dir: Path) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(held_out_dir.glob("*.json"))
    ]


def match_detections(
    detections: list[dict],
    ground_truth: list[dict],
    *,
    radius: float,
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Greedily pair detections to ground truth by nearest center, same
    category, within `radius` pixels. Highest-score detections match first.

    Returns (matched (detection, truth) pairs, unmatched detections,
    unmatched ground truth).
    """
    remaining_truth = list(ground_truth)
    matched: list[tuple[dict, dict]] = []
    unmatched_detections: list[dict] = []
    for detection in sorted(detections, key=lambda item: -item.get("score", 0.0)):
        best = None
        best_distance = radius
        for truth in remaining_truth:
            if truth["category"] != detection["category"]:
                continue
            distance = ((truth["x"] - detection["x"]) ** 2
                        + (truth["y"] - detection["y"]) ** 2) ** 0.5
            if distance <= best_distance:
                best = truth
                best_distance = distance
        if best is None:
            unmatched_detections.append(detection)
        else:
            matched.append((detection, best))
            remaining_truth.remove(best)
    return matched, unmatched_detections, remaining_truth


def evaluate(recognizer, annotations: list[dict], *, radius: float = 24.0) -> dict:
    per_category: dict[str, Counter] = {}
    exact_count_hits = 0
    for annotation in annotations:
        scene = vision.load(annotation["image"])
        targets = recognizer.find(scene)
        detections = [
            {"category": t.category, "x": t.x, "y": t.y, "score": t.score}
            for t in targets
        ]
        ground_truth = annotation["buildings"]
        matched, unmatched_detections, unmatched_truth = match_detections(
            detections, ground_truth, radius=radius
        )
        categories = {item["category"] for item in ground_truth} | {
            item["category"] for item in detections
        }
        for category in categories:
            counter = per_category.setdefault(category, Counter())
            counter["true_positive"] += sum(
                1 for _detection, truth in matched if truth["category"] == category
            )
            counter["false_positive"] += sum(
                1 for detection in unmatched_detections if detection["category"] == category
            )
            counter["false_negative"] += sum(
                1 for truth in unmatched_truth if truth["category"] == category
            )
        if not unmatched_detections and not unmatched_truth:
            exact_count_hits += 1

    report: dict[str, object] = {
        "images": len(annotations),
        "exact_count_match_rate": exact_count_hits / len(annotations) if annotations else None,
        "categories": {},
    }
    for category, counter in sorted(per_category.items()):
        true_positive = counter["true_positive"]
        false_positive = counter["false_positive"]
        false_negative = counter["false_negative"]
        precision = (
            true_positive / (true_positive + false_positive)
            if (true_positive + false_positive) else None
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if (true_positive + false_negative) else None
        )
        report["categories"][category] = {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--held-out-dir", type=Path, default=Path("assets/eval/held_out"))
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--radius", type=float, default=24.0)
    parser.add_argument("--fankit", type=Path, default=Path("assets/supercell_fankit"))
    parser.add_argument("--derived-assets", type=Path, default=Path("assets/derived_cache"))
    args = parser.parse_args()
    annotations = load_annotations(args.held_out_dir)
    if not annotations:
        raise SystemExit(f"no annotations found under {args.held_out_dir}")
    asset_catalog = AssetCatalog(args.derived_assets, args.fankit)
    recognizer = BuildingRecognizer(ReferenceCatalog(args.catalog), asset_catalog=asset_catalog)
    report = evaluate(recognizer, annotations, radius=args.radius)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
