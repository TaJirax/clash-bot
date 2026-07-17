"""Train the local asset retrieval model from every usable PNG sample."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from clashbot.asset_model import AssetRetrievalModel, feature


def load_records(derived: Path) -> list[dict]:
    records: list[dict] = []
    candidate = derived / "detector_candidates" / "manifest.json"
    visual = derived / "visual" / "manifest.json"
    if candidate.is_file():
        data = json.loads(candidate.read_text(encoding="utf-8"))
        for item in data.get("records", []):
            records.append({
                "path": derived / "detector_candidates" / item["output"],
                "label": f"{item.get('category', 'other')}:{item.get('family', 'unknown')}",
                "source": "synthetic_candidate",
            })
    if visual.is_file():
        data = json.loads(visual.read_text(encoding="utf-8"))
        for item in data.get("records", []):
            if "output" in item:
                records.append({
                    "path": derived / "visual" / item["output"],
                    "label": f"{item.get('category', 'other')}:{item.get('label', 'unknown')}",
                    "source": "labelled_reference",
                })
    return records


def train_model(derived_root: Path, output: Path) -> dict:
    records = load_records(derived_root)
    vectors, labels, sources, used, failed = [], [], [], [], []
    seen: set[str] = set()
    for item in records:
        path = item["path"]
        if not path.is_file() or str(path) in seen:
            continue
        seen.add(str(path))
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            failed.append({"path": str(path), "error": "decode_failed"})
            continue
        vectors.append(feature(image))
        labels.append(item["label"])
        sources.append(item["source"])
        used.append({"path": str(path), "label": item["label"], "source": item["source"]})
    if not vectors:
        raise SystemExit("no usable PNG samples found")
    matrix = np.asarray(vectors, dtype=np.float32)
    model = AssetRetrievalModel(matrix, tuple(labels), tuple(sources))
    model.save(output)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": str(output),
        "feature": "64x64 HOG(9-bin cells)+HSV histograms, cosine retrieval",
        "samples": len(used),
        "failed": len(failed),
        "labels": len(set(labels)),
        "sources": dict(Counter(sources)),
        "records_sha256": hashlib.sha256(json.dumps(used, sort_keys=True).encode()).hexdigest(),
        "failed_records": failed,
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derived-root", type=Path, default=Path("assets/derived_cache"))
    parser.add_argument("--output", type=Path,
                        default=Path("assets/derived_cache/model/asset_retrieval.npz"))
    args = parser.parse_args()
    manifest = train_model(args.derived_root, args.output)
    print(json.dumps({k: manifest[k] for k in ("samples", "failed", "labels", "sources")}, indent=2))


if __name__ == "__main__":
    main()
