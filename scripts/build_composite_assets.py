"""Rasterize static SC2FLA/XFL exports into transparent detector candidates.

This is deliberately a candidate builder, not a live detector.  It resolves
XFL symbol/bitmap references recursively, renders frame zero onto a stable
canvas, and records exact source provenance for later review/training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


MATRIX = np.eye(3, dtype=np.float64)
SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe(value: str) -> str:
    return SAFE.sub("_", value).strip("._-") or "unknown"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def child(element: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in element.iter() if tag(item) == name), None)


def local_matrix(element: ET.Element) -> np.ndarray:
    matrix = child(element, "Matrix")
    if matrix is None:
        return MATRIX
    values = {key: float(matrix.attrib.get(key, default)) for key, default in (
        ("a", 1), ("b", 0), ("c", 0), ("d", 1), ("tx", 0), ("ty", 0),
    )}
    return np.array([
        [values["a"], values["c"], values["tx"]],
        [values["b"], values["d"], values["ty"]],
        [0, 0, 1],
    ], dtype=np.float64)


class XflRenderer:
    def __init__(self, library: Path, *, canvas: int = 512):
        self.library = library
        self.canvas = canvas
        self.center = canvas / 2
        self._xml: dict[str, ET.Element] = {}
        self._images: dict[str, np.ndarray] = {}

    def _symbol(self, item: str) -> ET.Element | None:
        if item in self._xml:
            return self._xml[item]
        path = self.library / f"{item}.xml"
        if not path.is_file():
            return None
        root = ET.parse(path).getroot()
        self._xml[item] = root
        return root

    def _bitmap(self, name: str) -> np.ndarray | None:
        if name not in self._images:
            path = self.library / f"{name}.png"
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is None:
                return None
            if image.ndim == 2:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
            elif image.shape[2] == 3:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
            self._images[name] = image
        return self._images[name]

    @staticmethod
    def _frame_elements(root: ET.Element) -> list[ET.Element]:
        elements: list[ET.Element] = []
        for layer in (item for item in root.iter() if tag(item) == "DOMLayer"):
            frames = [item for item in layer if tag(item) == "frames"]
            if not frames:
                continue
            frame_nodes = [item for item in frames[0] if tag(item) == "DOMFrame"]
            if not frame_nodes:
                continue
            # Frame zero is a stable pose. If it is empty, choose the first
            # populated frame instead of emitting a blank candidate.
            selected = frame_nodes[0]
            for frame in frame_nodes:
                bucket = child(frame, "elements")
                if bucket is not None and list(bucket):
                    selected = frame
                    break
            bucket = child(selected, "elements")
            if bucket is not None:
                elements.extend(list(bucket))
        return elements

    def _blend(self, canvas: np.ndarray, image: np.ndarray, transform: np.ndarray) -> None:
        placement = transform.copy()
        placement[0, 2] += self.center
        placement[1, 2] += self.center
        warped = cv2.warpAffine(
            image, placement[:2], (self.canvas, self.canvas),
            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        alpha = warped[:, :, 3:4].astype(np.float32) / 255.0
        canvas[:, :, :3] = (warped[:, :, :3] * alpha + canvas[:, :, :3] * (1 - alpha)).astype(np.uint8)
        canvas[:, :, 3] = np.maximum(canvas[:, :, 3], warped[:, :, 3])

    def _render(self, root: ET.Element, canvas: np.ndarray, transform: np.ndarray,
                visiting: set[str], depth: int) -> None:
        if depth > 32:
            return
        for element in self._frame_elements(root):
            item = element.attrib.get("libraryItemName")
            if not item:
                continue
            composed = transform @ local_matrix(element)
            if tag(element) == "DOMBitmapInstance":
                image = self._bitmap(item)
                if image is not None:
                    self._blend(canvas, image, composed)
                continue
            if tag(element) != "DOMSymbolInstance" or item in visiting:
                continue
            symbol = self._symbol(item)
            if symbol is not None:
                self._render(symbol, canvas, composed, visiting | {item}, depth + 1)

    def render(self, export: Path) -> np.ndarray:
        root = ET.parse(export).getroot()
        canvas = np.zeros((self.canvas, self.canvas, 4), dtype=np.uint8)
        self._render(root, canvas, MATRIX, set(), 0)
        return canvas


def build_record(item: dict, output: Path, *, canvas: int) -> dict | None:
    source = Path(item["output"])
    if not source.is_file():
        return None
    source_hash = digest(source)
    relative = Path("composites") / safe(item["category"]) / safe(item["family"]) / (
        f"level_{item['level']}" if item.get("level") is not None else "unlevelled"
    ) / f"{source_hash[:20]}.png"
    target = output / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        library = source.parents[1]
        image = XflRenderer(library, canvas=canvas).render(source)
        if not np.any(image[:, :, 3]):
            return None
        if not cv2.imwrite(str(target), image):
            raise RuntimeError(f"failed to write {target}")
    return {
        "source_export": str(source),
        "source_sha256": source_hash,
        "category": item["category"],
        "family": item["family"],
        "name": item["name"],
        "level": item.get("level"),
        "output": target.relative_to(output).as_posix(),
        "output_sha256": digest(target),
        "canvas_size": canvas,
        "kind": "synthetic_candidate",
    }


def representative(records: list[dict], variants: int) -> list[dict]:
    """Keep varied stable poses without filling the dataset with animation frames."""
    groups: dict[tuple[str, str, int | None], list[dict]] = {}
    for item in records:
        groups.setdefault((item["category"], item["family"], item.get("level")), []).append(item)

    def rank(item: dict) -> tuple[int, str]:
        name = str(item.get("name", "")).lower()
        preference = 0 if "idle" in name else 1 if "ready" in name else 2 if "attack" in name else 3
        return preference, name

    return [item for items in groups.values() for item in sorted(items, key=rank)[:variants]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=Path("assets/derived_cache/sorted_sc/semantic_index.json"))
    parser.add_argument("--output", type=Path,
                        default=Path("assets/derived_cache/detector_candidates"))
    parser.add_argument("--category", action="append", choices=("buildings", "units"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--canvas", type=int, default=512)
    parser.add_argument("--all-exports", action="store_true",
                        help="render every animation/export instead of representative poses")
    parser.add_argument("--variants-per-level", type=int, default=3)
    args = parser.parse_args()
    if args.canvas < 64:
        raise SystemExit("canvas must be at least 64")
    source = json.loads(args.input.read_text(encoding="utf-8"))
    wanted = set(args.category or ("buildings", "units"))
    records = [item for item in source.get("records", []) if item.get("category") in wanted]
    if not args.all_exports:
        records = representative(records, args.variants_per_level)
    if args.limit is not None:
        records = records[:args.limit]
    built, skipped = [], []
    for index, item in enumerate(records, start=1):
        try:
            record = build_record(item, args.output, canvas=args.canvas)
            (built if record else skipped).append(record or item.get("output"))
        except (ET.ParseError, OSError, ValueError) as error:
            skipped.append({"output": item.get("output"), "error": str(error)})
        if index % 100 == 0:
            print(f"built {len(built)}/{index}", flush=True)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(args.input),
        "selection": "all_exports" if args.all_exports else "representative_poses",
        "built": len(built),
        "skipped": len(skipped),
        "records": built,
        "skipped_records": skipped,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"built": len(built), "skipped": len(skipped)}, indent=2))


if __name__ == "__main__":
    main()
