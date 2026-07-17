"""Coarse-to-fine verification and asset-correction tests.

A tiny synthetic catalog with two visually related buildings ("alpha" and
"beta") drives the recognizer end to end: the half-resolution pass proposes
candidates and the full-resolution local re-match must confirm, relabel, or
reject them.
"""

import json

import cv2
import numpy as np
import pytest

from clashbot import vision
from clashbot.upgrades import BuildingRecognizer, ReferenceCatalog


def _patch_alpha() -> np.ndarray:
    patch = np.zeros((64, 64, 3), dtype=np.uint8)
    patch[:32, :32] = (40, 60, 200)
    patch[:32, 32:] = (200, 60, 40)
    patch[32:, :32] = (60, 200, 60)
    patch[32:, 32:] = (200, 200, 40)
    cv2.circle(patch, (32, 32), 12, (255, 255, 255), -1)
    return patch


def _patch_beta() -> np.ndarray:
    # Same structure as alpha with one recolored quadrant: similar enough
    # that alpha's template still fires on it, distinct enough that beta's
    # own template must win the closer full-resolution look.
    patch = _patch_alpha()
    patch[32:, 32:] = (200, 40, 200)
    return patch


@pytest.fixture()
def catalog(tmp_path) -> ReferenceCatalog:
    source = np.zeros((720, 1280, 3), dtype=np.uint8)
    source[:] = (70, 145, 70)
    source[100:164, 200:264] = _patch_alpha()
    source[100:164, 400:464] = _patch_beta()
    hammer = np.full((40, 40, 3), (30, 90, 160), dtype=np.uint8)
    source[600:640, 600:640] = hammer
    cv2.imwrite(str(tmp_path / "reference.png"), source)
    (tmp_path / "catalog.json").write_text(json.dumps({
        "reference_size": [1280, 720],
        "camera_scales": [1.0],
        "templates": [
            {"name": "alpha_lv1", "category": "alpha",
             "source": "reference.png", "crop": [200, 100, 264, 164],
             "threshold": 0.70},
            {"name": "beta_lv1", "category": "beta",
             "source": "reference.png", "crop": [400, 100, 464, 164],
             "threshold": 0.70},
        ],
        "ui": {"upgrade_hammer": {"source": "reference.png",
                                  "crop": [600, 600, 640, 640]}},
    }), encoding="utf-8")
    return ReferenceCatalog(tmp_path / "catalog.json")


def _scene(*patches: tuple[np.ndarray, int, int]) -> np.ndarray:
    scene = np.zeros((720, 1280, 3), dtype=np.uint8)
    scene[:] = (70, 145, 70)
    for patch, x, y in patches:
        scene[y:y + patch.shape[0], x:x + patch.shape[1]] = patch
    return scene


def test_genuine_buildings_are_found_and_verified(catalog):
    scene = _scene((_patch_alpha(), 300, 300), (_patch_beta(), 700, 400))
    targets = BuildingRecognizer(catalog).find(scene)
    assert {t.category for t in targets} == {"alpha", "beta"}
    assert all(t.verified for t in targets)
    by_category = {t.category: t for t in targets}
    assert abs(by_category["alpha"].x - 332) <= 4
    assert abs(by_category["beta"].y - 432) <= 4


def test_closer_look_corrects_a_mislabelled_building(catalog):
    # Only beta exists in the scene. Alpha's template fires on it (they share
    # three quadrants), but full-resolution verification must relabel the
    # detection to beta rather than trust the first template that matched.
    scene = _scene((_patch_beta(), 500, 350))
    targets = BuildingRecognizer(catalog).find(scene)
    assert len(targets) == 1
    assert targets[0].category == "beta"
    assert targets[0].verified


def test_correction_can_be_disabled(catalog):
    scene = _scene((_patch_beta(), 500, 350))
    recognizer = BuildingRecognizer(catalog, refine=False)
    targets = recognizer.find(scene)
    # Even without cross-category correction the detection is still verified
    # locally; beta's own template simply wins the dedupe by score.
    assert len(targets) == 1
    assert targets[0].verified


def test_verification_rejects_candidates_without_local_support(catalog):
    scene = _scene((_patch_alpha(), 300, 300))
    recognizer = BuildingRecognizer(catalog)
    fake_hit = vision.Match(name="beta_lv1", x=900, y=500, w=64, h=64,
                            score=0.99, scale=1.0)
    beta_spec = next(spec for spec in catalog.specs if spec.category == "beta")
    assert recognizer._verify_local(scene, beta_spec, fake_hit, 1.0) is None
