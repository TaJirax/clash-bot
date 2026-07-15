import json

import cv2
import numpy as np
import pytest

from clashbot.menu_capture import MenuDataset


def _png(color=(20, 40, 60)):
    image = np.full((72, 128, 3), color, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_capture_builds_state_and_transition_manifest(tmp_path):
    dataset = MenuDataset(tmp_path, "th2_menus")

    first = dataset.capture(_png(), state="home", description="main village")
    second = dataset.capture(
        _png((30, 50, 70)),
        state="army",
        after="home",
        action="tap Army button",
    )

    manifest = json.loads(dataset.manifest_path.read_text(encoding="utf-8"))
    assert first["id"] == 1 and second["id"] == 2
    assert manifest["captures"][1]["state"] == "army"
    assert manifest["transitions"] == [{
        "from_state": "home",
        "action": "tap Army button",
        "to_state": "army",
        "evidence_capture_id": 2,
    }]
    assert (dataset.directory / second["file"]).exists()


def test_transition_requires_both_after_and_action(tmp_path):
    dataset = MenuDataset(tmp_path, "menus")
    with pytest.raises(ValueError, match="supplied together"):
        dataset.capture(_png(), state="army", after="home")


def test_rejects_unsafe_names_and_invalid_images(tmp_path):
    with pytest.raises(ValueError, match="session"):
        MenuDataset(tmp_path, "../outside")
    dataset = MenuDataset(tmp_path, "menus")
    with pytest.raises(ValueError, match="valid PNG"):
        dataset.capture(b"not an image", state="home")
