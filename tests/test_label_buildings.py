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
