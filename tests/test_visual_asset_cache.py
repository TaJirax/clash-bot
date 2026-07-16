from pathlib import Path

import cv2
import numpy as np

from scripts.build_visual_asset_cache import (
    build_source,
    infer_metadata,
    normalized_png,
)


def test_normalized_png_centers_transparent_sprite() -> None:
    image = np.zeros((40, 80, 4), dtype=np.uint8)
    image[10:30, 30:50] = (10, 20, 30, 255)

    payload = normalized_png(image, canvas_size=64, margin=4)
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)

    assert decoded.shape == (64, 64, 4)
    assert cv2.boundingRect(cv2.findNonZero(decoded[:, :, 3])) == (22, 22, 20, 20)


def test_builder_accepts_jpeg_and_records_label(tmp_path: Path) -> None:
    source = tmp_path / "Characters" / "Balloon" / "Level 12"
    source.mkdir(parents=True)
    image = np.full((32, 20, 3), 180, dtype=np.uint8)
    assert cv2.imwrite(str(source / "Balloon_lvl12.jpg"), image)

    output = tmp_path / "cache"
    records = build_source("test", tmp_path, output, 64)

    assert len(records) == 1
    assert records[0]["level"] == 12
    assert records[0]["label"] == "Balloon lvl12"
    assert (output / records[0]["output"]).is_file()


def test_statscell_hall_filename_becomes_level_and_variant(tmp_path: Path) -> None:
    hall = tmp_path / "townhalls" / "14.3.png"
    hall.parent.mkdir()
    hall.write_bytes(b"not decoded in metadata test")

    metadata = infer_metadata(tmp_path, hall)

    assert metadata["label"] == "townhall"
    assert metadata["level"] == 14
    assert metadata["variant"] == 3
