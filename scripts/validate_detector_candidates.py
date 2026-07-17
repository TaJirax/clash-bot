"""Validate built composite PNGs before they enter the training pipeline."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


def inspect(path: Path) -> dict:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        return {"path": str(path), "status": "invalid_png"}
    points = cv2.findNonZero((image[:, :, 3] > 3).astype(np.uint8))
    if points is None:
        return {"path": str(path), "status": "blank"}
    x, y, width, height = cv2.boundingRect(points)
    return {
        "path": str(path), "status": "ok",
        "dimensions": [int(image.shape[1]), int(image.shape[0])],
        "visible_box": [int(x), int(y), int(width), int(height)],
        "visible_fraction": round(float(np.mean(image[:, :, 3] > 3)), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("assets/derived_cache/detector_candidates"))
    args = parser.parse_args()
    records = [inspect(path) for path in sorted(args.root.rglob("*.png"))]
    summary = Counter(record["status"] for record in records)
    manifest = {"summary": dict(sorted(summary.items())), "records": records}
    (args.root / "quality_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["summary"], indent=2))


if __name__ == "__main__":
    main()
