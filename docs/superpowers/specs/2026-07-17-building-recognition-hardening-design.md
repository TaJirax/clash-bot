# Universal building recognition hardening

## Problem

`BuildingRecognizer` (`src/clashbot/upgrades.py`) only matches against 52
hand-cropped templates taken from one account's screenshots
(`assets/buildings.json`, all sourced from `base_now.png`). Separately,
`AssetCatalog` indexes 72,917 reference assets (Fan Kit, decoded game
package resources, a trained `AssetRetrievalModel`), none of which the live
detector uses (`detector_ready: 0` for all of them per
`scripts/report_asset_coverage.py`). No held-out accuracy measurement
exists anywhere in the repo, so "works on an unseen base" is currently an
assumption, not a verified property, contradicting the Phase 2 exit gate in
`docs/universal-bot-blueprint.md` ("no category is called supported without
real held-out examples").

## Goal

Close the gap between the two systems and make generalization measurable,
without requiring new data collection to start seeing results.

## Design

### 1. Second-opinion confirmation in `BuildingRecognizer`

`ReferenceCatalog`/`BuildingRecognizer.find()` currently accepts a template
match once its correlation score clears `TemplateSpec.threshold`. Add a
lower "ambiguous band": `threshold - 0.08` to `threshold`. A match landing
in that band is cropped from the current frame and passed to
`AssetCatalog.retrieve()` (already lazy-loaded, already optional on the
recognizer). If the retrieval model's top-k predictions agree on
`category` (and `level` when both are known), the match is accepted and its
`BuildingTarget.verified` flag is set `True`. If they disagree, or no
catalog is configured, the match is dropped rather than guessed.

Matches already at or above `threshold` are unaffected — this only recovers
borderline detections and enforces the blueprint rule "confirm questionable
objects from at least two views or with a second model." `BuildingRecognizer`
already accepts an `asset_catalog` constructor argument path through
`AutonomousBaseScanner`; this only needs to be threaded into
`BuildingRecognizer` itself (currently it is not).

### 2. Held-out annotation format + labelling helper

No ground-truth-labelled screenshot exists in the repo (only template
source crops and unlabelled raw captures under the git-ignored `captures/`
directory). Add:

- **Format**: one JSON file per labelled screenshot, stored under
  `assets/eval/held_out/` (small, hand-labelled, git-tracked — unlike
  `captures/`):

  ```json
  {
    "image": "relative/path/to/screenshot.png",
    "buildings": [
      {"category": "town_hall", "level": 11, "x": 640, "y": 360}
    ]
  }
  ```

- **Labelling helper** (`scripts/label_buildings.py`): opens an image in an
  OpenCV window, click a building center, type its category and optional
  level in the terminal, repeat, then write the JSON file. No GUI
  framework — a `cv2.setMouseCallback` loop is sufficient for the volume of
  labelling this needs.

### 3. Evaluation script (`scripts/evaluate_building_recognizer.py`)

Loads every annotation file under `assets/eval/held_out/`, runs
`BuildingRecognizer.find()` against the referenced image, and matches
detections to ground-truth points by nearest neighbor within a fixed pixel
radius (scaled by the detected `camera_scale`, consistent with how
`AutonomousBaseScanner` already reasons about scale). Reports, in the same
style as `report_asset_coverage.py`:

- per-category precision and recall,
- exact-count-match rate (detected count == ground-truth count) per
  category,
- an overall summary.

This turns the Phase 2 exit gate (precision >= 98%, recall >= 95%, exact
count on >= 95% of test bases) from an assumption into a rerunnable number.

## Explicitly out of scope

- The synthetic-data training pipeline (splitting sprite sheets, padding
  removal, synthetic backgrounds) — a separate, larger effort (option C
  from the design discussion), deferred.
- A GUI annotation tool — the CLI clicker is sufficient for this volume.
- Collecting new screenshots from other accounts/zoom levels/resolutions —
  the harness will report honestly on whatever is labelled. Proving
  cross-account universality requires the user to capture and label
  screenshots from accounts other than the one `base_now.png` came from;
  that data-collection step is follow-up work, not part of this
  implementation.

## Testing

- Unit test for the second-opinion merge logic in `BuildingRecognizer`:
  fake `AssetCatalog.retrieve()` returning agreeing/disagreeing/absent
  predictions, verify accept/drop/`verified` behavior at each band.
- Unit test for the evaluation script's matching and precision/recall math:
  synthetic detections vs. synthetic ground truth, no live emulator or real
  screenshots required.
- Existing `tests/test_asset_catalog.py` and building-recognition tests
  continue to pass unchanged (no behavior change above `threshold`).

## Follow-up (not this slice)

- Capture and label held-out screenshots from additional accounts, zoom
  levels, and resolutions to actually exercise the new evaluation harness
  and drive the Phase 2 exit gate to green.
- Once precision/recall are measured and tracked, revisit whether the
  synthetic-data pipeline (option C) is worth building to close remaining
  category/level gaps.
