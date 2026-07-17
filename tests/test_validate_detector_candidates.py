import cv2
import numpy as np

from scripts.validate_detector_candidates import inspect


def test_candidate_validation_reports_visible_bounds(tmp_path):
    image = np.zeros((20, 30, 4), dtype=np.uint8)
    image[4:12, 8:18] = (0, 0, 255, 255)
    path = tmp_path / "candidate.png"
    assert cv2.imwrite(str(path), image)

    result = inspect(path)

    assert result["status"] == "ok"
    assert result["visible_box"] == [8, 4, 10, 8]
