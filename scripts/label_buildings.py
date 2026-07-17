"""Interactively label building positions on a screenshot for the held-out
evaluation set used by scripts/evaluate_building_recognizer.py.

Click each building, answer the category/level prompts in the terminal, then
press 'q' in the image window to finish and write the annotation JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


def annotation_path(image: Path, output_dir: Path) -> Path:
    return output_dir / f"{image.stem}.json"


def save_annotation(image: Path, buildings: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = annotation_path(image, output_dir)
    payload = {"image": str(image), "buildings": buildings}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def collect_buildings(image_path: Path) -> list[dict]:
    scene = cv2.imread(str(image_path))
    if scene is None:
        raise FileNotFoundError(image_path)
    buildings: list[dict] = []

    def on_click(event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        category = input(f"category at ({x},{y}): ").strip()
        if not category:
            return
        level_raw = input("level (blank if unknown): ").strip()
        level = int(level_raw) if level_raw else None
        buildings.append({"category": category, "level": level, "x": x, "y": y})
        cv2.circle(scene, (x, y), 6, (0, 255, 0), 2)
        cv2.imshow("label", scene)

    cv2.imshow("label", scene)
    cv2.setMouseCallback("label", on_click)
    print("Click each building, answer the prompts. Press 'q' in the window to finish.")
    while cv2.waitKey(50) & 0xFF != ord("q"):
        pass
    cv2.destroyAllWindows()
    return buildings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("assets/eval/held_out"))
    args = parser.parse_args()
    buildings = collect_buildings(args.image)
    if not buildings:
        print("no buildings labelled; nothing written")
        return
    path = save_annotation(args.image, buildings, args.output_dir)
    print(f"wrote {len(buildings)} building(s) to {path}")


if __name__ == "__main__":
    main()
