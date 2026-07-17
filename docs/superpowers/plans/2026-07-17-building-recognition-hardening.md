# Building Recognition Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `BuildingRecognizer` fall back to the trained asset-retrieval
model as a second opinion on borderline matches, and add a held-out
precision/recall harness so "the detector generalizes" becomes a rerunnable
measurement instead of an assumption.

**Architecture:** `BuildingRecognizer` gains an optional `asset_catalog`
dependency. When its normal full-resolution verification (`_verify_local`)
finds no match at a template's own threshold, it now retries once in a
narrow "ambiguous band" just below threshold, and only accepts that weaker
match if `AssetCatalog.retrieve()` (an existing HOG+color-histogram
retrieval model) independently agrees on the building's category. Separately,
a small annotation format + labelling CLI + evaluation CLI are added so
real held-out screenshots can be scored against the recognizer's output.

**Tech Stack:** Python 3.12, OpenCV (`cv2`), NumPy, pytest. No new
dependencies.

## Global Constraints

- Never accept a detection on appearance alone without either clearing its
  template's own threshold or getting independent agreement from the
  retrieval model (`docs/universal-bot-blueprint.md` rule 3 and rule "confirm
  questionable objects from at least two views or with a second model").
- No behavior change for matches that already clear a template's full
  threshold — the ambiguous-band path only recovers matches that would
  otherwise be dropped.
- No new third-party dependencies; use only `cv2`/`numpy`/stdlib, consistent
  with the rest of `src/clashbot`.
- All new scripts are importable as `scripts.<module>` for testing, matching
  the existing pattern (see `tests/test_validate_detector_candidates.py`
  importing `from scripts.validate_detector_candidates import inspect`) —
  no `scripts/__init__.py` is needed; pytest's rootdir-based import already
  makes this work.

---

### Task 1: Ambiguous-band second opinion in `BuildingRecognizer`

**Files:**
- Modify: `src/clashbot/upgrades.py`
- Test: `tests/test_detection_verification.py`

**Interfaces:**
- Consumes: `clashbot.asset_catalog.normalize_label(value: str) -> str`
  (already exists).
- Produces: `BuildingRecognizer.__init__(catalog, *, refine=True,
  asset_catalog=None)` — `asset_catalog` is any object exposing
  `.retrieve(image: np.ndarray, *, k: int = 5) -> Sequence[object]` where
  each item has a `.label` attribute formatted as `"category:name"` (this is
  exactly `AssetCatalog.retrieve`'s existing contract). `BuildingTarget`
  objects produced via this path have `verified=True`, same as today's
  fully-confirmed matches.

- [ ] **Step 1: Write the failing tests**

Open `tests/test_detection_verification.py` and add these tests (and the
`_FakePrediction`/`_FakeCatalog` helpers) after the existing imports, using
the existing `catalog` fixture already defined in that file:

```python
class _FakePrediction:
    def __init__(self, label: str):
        self.label = label


class _FakeCatalog:
    def __init__(self, labels: list[str]):
        self._labels = labels

    def retrieve(self, image, *, k: int = 5):
        return tuple(_FakePrediction(label) for label in self._labels)


def _stub_ambiguous_hit(recognizer, spec, *, score: float = 0.65):
    """Make the primary full-threshold lookup miss and the ambiguous-band
    retry return one fixed candidate hit for `spec`, regardless of the real
    pixel data in the region. This isolates the ambiguous-band branching
    logic from exact matchTemplate correlation values."""
    hit = vision.Match(name=spec.name, x=10, y=10, w=40, h=40, score=score)

    def fake_best_in_region(region, templates, scales, threshold_offset=0.0):
        if threshold_offset == 0.0:
            return None
        return (spec, hit)

    recognizer._best_in_region = fake_best_in_region


def test_ambiguous_match_is_accepted_when_catalog_agrees(catalog):
    scene = _scene((_patch_beta(), 500, 350))
    beta_spec = next(spec for spec in catalog.specs if spec.category == "beta")
    recognizer = BuildingRecognizer(
        catalog, asset_catalog=_FakeCatalog(["beta:beta_lv1"])
    )
    _stub_ambiguous_hit(recognizer, beta_spec)
    hit = vision.Match(name="beta_lv1", x=500, y=350, w=64, h=64, score=0.0)

    target = recognizer._verify_local(scene, beta_spec, hit, 1.0)

    assert target is not None
    assert target.category == "beta"
    assert target.verified


def test_ambiguous_match_is_rejected_when_catalog_disagrees(catalog):
    scene = _scene((_patch_beta(), 500, 350))
    beta_spec = next(spec for spec in catalog.specs if spec.category == "beta")
    recognizer = BuildingRecognizer(
        catalog, asset_catalog=_FakeCatalog(["alpha:alpha_lv1"])
    )
    _stub_ambiguous_hit(recognizer, beta_spec)
    hit = vision.Match(name="beta_lv1", x=500, y=350, w=64, h=64, score=0.0)

    target = recognizer._verify_local(scene, beta_spec, hit, 1.0)

    assert target is None


def test_ambiguous_band_needs_a_catalog(catalog):
    scene = _scene((_patch_beta(), 500, 350))
    beta_spec = next(spec for spec in catalog.specs if spec.category == "beta")
    recognizer = BuildingRecognizer(catalog)  # no asset_catalog
    _stub_ambiguous_hit(recognizer, beta_spec)
    hit = vision.Match(name="beta_lv1", x=500, y=350, w=64, h=64, score=0.0)

    target = recognizer._verify_local(scene, beta_spec, hit, 1.0)

    assert target is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_detection_verification.py -v`
Expected: the three new tests fail — `BuildingRecognizer.__init__() got an
unexpected keyword argument 'asset_catalog'` (or `AttributeError` once that's
fixed, since `_ambiguous_band_target` does not exist yet). The four
pre-existing tests in this file still pass.

- [ ] **Step 3: Implement the ambiguous-band second opinion**

In `src/clashbot/upgrades.py`, add the import near the top (with the other
local imports):

```python
from .asset_catalog import normalize_label
```

In the `BuildingRecognizer` class, add a class constant next to the existing
`CONFIDENT_SCORE`/`CORRECT_MARGIN` constants:

```python
    # A below-threshold match this close to its template's own threshold may
    # still be accepted if a second model (the asset-retrieval catalog)
    # independently agrees on category.
    AMBIGUOUS_BAND = 0.08
```

Change the constructor:

```python
    def __init__(self, catalog: ReferenceCatalog, *, refine: bool = True,
                 asset_catalog=None):
        self.catalog = catalog
        self.templates = [(spec, catalog.crop(spec.source, spec.crop)) for spec in catalog.specs]
        self.refine = refine
        self.asset_catalog = asset_catalog
```

(keep the rest of the existing `__init__` body — `_by_category` and
`_last_camera_scales` setup — unchanged below this).

Replace the `same is None` branch in `_verify_local` and add the two new
helper methods right after it:

```python
        same = self._best_in_region(
            region, self._by_category.get(spec.category, []), scales
        )
        if same is None:
            return self._ambiguous_band_target(
                region, ox, oy, spec, scales, resolution_scale
            )
```

```python
    def _ambiguous_band_target(
        self,
        region: np.ndarray,
        ox: int,
        oy: int,
        spec: TemplateSpec,
        scales: list[float],
        resolution_scale: float,
    ) -> BuildingTarget | None:
        """Recover a below-threshold match only when a second model agrees.

        See docs/universal-bot-blueprint.md: "confirm questionable objects
        from at least two views or with a second model."
        """
        if self.asset_catalog is None:
            return None
        candidate = self._best_in_region(
            region, self._by_category.get(spec.category, []), scales,
            threshold_offset=-self.AMBIGUOUS_BAND,
        )
        if candidate is None:
            return None
        best_spec, best_hit = candidate
        if not self._confirmed_by_catalog(region, best_spec.category):
            return None
        return BuildingTarget(
            category=best_spec.category,
            name=best_spec.name,
            x=ox + best_hit.center[0],
            y=oy + best_hit.center[1],
            score=best_hit.score,
            radius=max(7.0, min(best_hit.w, best_hit.h) * 0.18),
            camera_scale=best_hit.scale / resolution_scale,
            verified=True,
        )

    def _confirmed_by_catalog(self, region: np.ndarray, category: str) -> bool:
        predictions = self.asset_catalog.retrieve(region, k=5)
        target = normalize_label(category)
        return any(
            normalize_label(prediction.label.split(":", 1)[0]) == target
            for prediction in predictions
        )
```

Leave the rest of `_verify_local` (the `best_spec, best_hit = same` branch
onward) exactly as it is today.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest tests/test_detection_verification.py -v`
Expected: all 7 tests pass (4 pre-existing + 3 new).

Then run the full suite to confirm no regressions:

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all tests pass (133 pre-existing + 3 new = 136).

- [ ] **Step 5: Commit**

```bash
git add src/clashbot/upgrades.py tests/test_detection_verification.py
git commit -m "feat: confirm ambiguous building matches with the asset-retrieval model"
```

---

### Task 2: Wire the asset catalog into the live autonomous scan

**Files:**
- Modify: `src/clashbot/cli.py`

**Interfaces:**
- Consumes: `BuildingRecognizer(catalog, *, refine=True, asset_catalog=None)`
  from Task 1.
- Produces: nothing new consumed by later tasks — this is a leaf wiring
  change.

- [ ] **Step 1: Make the change**

In `src/clashbot/cli.py`, in `cmd_scan_base` (around line 294-310), build the
`AssetCatalog` once and pass it to both `BuildingRecognizer` and
`AutonomousBaseScanner` instead of leaving the recognizer without one:

```python
    client = adb_client.AdbClient(args.serial)
    catalog = ReferenceCatalog(args.catalog)
    asset_catalog = AssetCatalog(args.derived_assets, args.fankit)
    recognizer = BuildingRecognizer(catalog, asset_catalog=asset_catalog)
    zoom = controller_from_catalog(
        client, args.catalog, actuator=AdbPinchZoom(client)
    )
    # Share recognition state so a measured scale is reused by capture, zoom,
    # and subsequent panned views.
    zoom.recognizer = recognizer
    scanner = AutonomousBaseScanner(
        client,
        recognizer,
        zoom=zoom,
        fankit=FanKitIndex(args.fankit),
        asset_catalog=asset_catalog,
        root=args.root,
    )
```

This replaces the previous two separate lines (`recognizer =
BuildingRecognizer(catalog)` and the inline `asset_catalog=AssetCatalog(...)`
inside the `AutonomousBaseScanner(...)` call) — the catalog is now built once
and shared, instead of loaded twice.

- [ ] **Step 2: Verify no import/syntax regressions**

There is no existing test coverage for `cli.py`'s command wiring (it needs a
live ADB connection). Verify the module still imports cleanly and the full
suite still passes:

Run: `./.venv/Scripts/python -c "from clashbot import cli"`
Expected: no output, exit code 0.

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all 136 tests still pass (unchanged count — this task adds no
tests).

- [ ] **Step 3: Commit**

```bash
git add src/clashbot/cli.py
git commit -m "feat: share the asset catalog between the recognizer and the autonomous scanner"
```

---

### Task 3: Held-out annotation format + labelling helper

**Files:**
- Create: `scripts/label_buildings.py`
- Create: `assets/eval/held_out/README.md`
- Test: `tests/test_label_buildings.py`

**Interfaces:**
- Produces: `save_annotation(image: Path, buildings: list[dict], output_dir:
  Path) -> Path` and `annotation_path(image: Path, output_dir: Path) ->
  Path`, both consumed by Task 4's evaluation script indirectly (Task 4 reads
  the JSON files these write, not the functions directly, but the schema
  must match: `{"image": str, "buildings": [{"category": str, "level":
  int | None, "x": int, "y": int}, ...]}`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_label_buildings.py`:

```python
"""Tests for the held-out annotation writer used by the labelling CLI."""

import json

from scripts.label_buildings import annotation_path, save_annotation


def test_save_annotation_writes_expected_schema(tmp_path):
    image = tmp_path / "shots" / "base1.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fake-png")
    buildings = [{"category": "town_hall", "level": 11, "x": 640, "y": 360}]

    path = save_annotation(image, buildings, tmp_path / "held_out")

    assert path == tmp_path / "held_out" / "base1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"image": str(image), "buildings": buildings}


def test_annotation_path_uses_image_stem(tmp_path):
    image = tmp_path / "shots" / "zoomed_out.png"

    result = annotation_path(image, tmp_path / "held_out")

    assert result == tmp_path / "held_out" / "zoomed_out.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_label_buildings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.label_buildings'`.

- [ ] **Step 3: Implement the labelling script**

Create `scripts/label_buildings.py`:

```python
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
```

Create `assets/eval/held_out/README.md`:

```markdown
# Held-out building recognition annotations

Each `*.json` file here is a hand-labelled screenshot used only for
measuring `BuildingRecognizer` accuracy — never for training. Create one with:

    python scripts/label_buildings.py path/to/screenshot.png

Schema:

    {
      "image": "path/to/screenshot.png",
      "buildings": [
        {"category": "town_hall", "level": 11, "x": 640, "y": 360}
      ]
    }

Run `python scripts/evaluate_building_recognizer.py` to score the current
recognizer against every annotation in this directory. For the report to
say anything about universality (not just this account), label screenshots
from more than one account, zoom level, and layout.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest tests/test_label_buildings.py -v`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/label_buildings.py assets/eval/held_out/README.md tests/test_label_buildings.py
git commit -m "feat: add a held-out building annotation format and labelling CLI"
```

---

### Task 4: Held-out precision/recall evaluation script

**Files:**
- Create: `scripts/evaluate_building_recognizer.py`
- Test: `tests/test_evaluate_building_recognizer.py`

**Interfaces:**
- Consumes: annotation JSON schema from Task 3
  (`{"image": str, "buildings": [{"category", "level", "x", "y"}, ...]}`);
  `BuildingRecognizer.find(scene) -> list[BuildingTarget]` (existing, from
  `clashbot.upgrades`).
- Produces: `match_detections(detections: list[dict], ground_truth:
  list[dict], *, radius: float) -> tuple[list[tuple[dict, dict]], list[dict],
  list[dict]]` and `evaluate(recognizer, annotations: list[dict], *,
  radius: float = 24.0) -> dict` — both used only by this script's `main()`
  and by its own tests; no other task depends on them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evaluate_building_recognizer.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python -m pytest tests/test_evaluate_building_recognizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.evaluate_building_recognizer'`.

- [ ] **Step 3: Implement the evaluation script**

Create `scripts/evaluate_building_recognizer.py`:

```python
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
        detected_counts = Counter(item["category"] for item in detections)
        truth_counts = Counter(item["category"] for item in ground_truth)
        if detected_counts == truth_counts:
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
    args = parser.parse_args()
    annotations = load_annotations(args.held_out_dir)
    if not annotations:
        raise SystemExit(f"no annotations found under {args.held_out_dir}")
    recognizer = BuildingRecognizer(ReferenceCatalog(args.catalog))
    report = evaluate(recognizer, annotations, radius=args.radius)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python -m pytest tests/test_evaluate_building_recognizer.py -v`
Expected: all 3 tests pass.

Then run the full suite one more time:

Run: `./.venv/Scripts/python -m pytest -q`
Expected: all tests pass (136 from Task 1 + 2 from Task 3 + 3 from this task
= 141).

- [ ] **Step 5: Commit**

```bash
git add scripts/evaluate_building_recognizer.py tests/test_evaluate_building_recognizer.py
git commit -m "feat: add held-out precision/recall evaluation for BuildingRecognizer"
```

---

## After this plan

This closes the code-side gap (second-opinion confirmation + a measurement
harness) using only what already exists in the repo. It does **not** yet
prove cross-account universality — that requires running
`scripts/label_buildings.py` against screenshots from accounts, zoom levels,
and layouts beyond the one `assets/buildings.json` was built from, then
running `scripts/evaluate_building_recognizer.py` and checking the reported
precision/recall against the Phase 2 exit gate in
`docs/universal-bot-blueprint.md` (precision >= 98%, recall >= 95%, exact
count on >= 95% of test bases). That data collection is the natural next
slice.
