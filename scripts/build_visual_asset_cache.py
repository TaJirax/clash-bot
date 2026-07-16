"""Normalize labelled source images into a provenance-aware recognition cache.

Source artwork remains outside tracked paths. Each output is a centered PNG on
a fixed canvas, while the manifest keeps its source, label, level and hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
LEVEL_PATTERN = re.compile(r"(?:level|lvl)[ _-]*(\d+)", re.IGNORECASE)


def file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._-")
    return cleaned[:96] or "unlabelled"


def infer_metadata(root: Path, path: Path) -> dict:
    relative = path.relative_to(root)
    parts = relative.parts
    category = parts[0] if len(parts) > 1 else "uncategorized"
    label = path.stem
    level = None
    for value in reversed(parts):
        match = LEVEL_PATTERN.search(value)
        if match:
            level = int(match.group(1))
            break
    # Statscell hall filenames are the level/weapon-stage identifier.
    if category.lower() in {"townhalls", "builderhalls"}:
        label = category[:-1] if category.endswith("s") else category
        level_match = re.match(r"(\d+)(?:\.(\d+))?$", path.stem)
        if level_match:
            level = int(level_match.group(1))
            variant = int(level_match.group(2) or 0)
        else:
            variant = None
    else:
        variant = None
    return {
        "relative_source": relative.as_posix(),
        "category": category,
        "label": label.replace("_", " "),
        "level": level,
        "variant": variant,
    }


def trim_visible(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] != 4:
        return image
    alpha = image[:, :, 3]
    points = cv2.findNonZero((alpha > 3).astype(np.uint8))
    if points is None:
        return image
    x, y, width, height = cv2.boundingRect(points)
    return image[y:y + height, x:x + width]


def normalized_png(image: np.ndarray, canvas_size: int = 256, margin: int = 16) -> bytes:
    image = trim_visible(image)
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    elif image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    available = max(1, canvas_size - 2 * margin)
    height, width = image.shape[:2]
    scale = min(available / width, available / height, 1.0)
    if scale < 1.0:
        image = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    canvas = np.zeros((canvas_size, canvas_size, 4), dtype=np.uint8)
    y = (canvas_size - image.shape[0]) // 2
    x = (canvas_size - image.shape[1]) // 2
    canvas[y:y + image.shape[0], x:x + image.shape[1]] = image
    ok, encoded = cv2.imencode(".png", canvas)
    if not ok:
        raise ValueError("OpenCV could not encode normalized PNG")
    return encoded.tobytes()


def build_source(source_id: str, root: Path, output: Path, canvas_size: int) -> list[dict]:
    records = []
    images = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    for path in images:
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            records.append({
                "source_id": source_id,
                "relative_source": path.relative_to(root).as_posix(),
                "error": "decode_failed",
            })
            continue
        payload = normalized_png(image, canvas_size=canvas_size)
        output_hash = hashlib.sha256(payload).hexdigest()
        metadata = infer_metadata(root, path)
        category = safe_name(str(metadata["category"]).lower())
        label = safe_name(str(metadata["label"]).lower())
        target = output / safe_name(source_id) / category / label / f"{output_hash[:20]}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(payload)
        records.append({
            "source_id": source_id,
            **metadata,
            "source_sha256": file_hash(path),
            "source_dimensions": [int(image.shape[1]), int(image.shape[0])],
            "output": target.relative_to(output).as_posix(),
            "output_sha256": output_hash,
            "canvas_size": canvas_size,
        })
    return records


def parse_source(value: str) -> tuple[str, Path]:
    source_id, separator, location = value.partition("=")
    if not separator or not source_id or not location:
        raise argparse.ArgumentTypeError("source must be ID=PATH")
    return safe_name(source_id), Path(location)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", type=parse_source, required=True,
                        help="labelled image tree as ID=PATH; may be repeated")
    parser.add_argument("--output", type=Path, default=Path("assets/derived_cache/visual"))
    parser.add_argument("--canvas-size", type=int, default=256)
    args = parser.parse_args()
    if args.canvas_size < 64:
        raise SystemExit("canvas size must be at least 64")
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for source_id, root in args.source:
        if not root.is_dir():
            raise SystemExit(f"source directory does not exist: {root}")
        print(f"normalizing {source_id}: {root}")
        records.extend(build_source(source_id, root, args.output, args.canvas_size))
    valid = [record for record in records if "output" in record]
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
        "summary": {
            "source_images": len(records),
            "normalized_images": len(valid),
            "unique_outputs": len({record["output_sha256"] for record in valid}),
            "decode_failures": len(records) - len(valid),
        },
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["summary"], indent=2))
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
