import cv2
import numpy as np
from pathlib import Path

from clashbot.attack_execution import AttackLog, LootAttackExecutor


def test_deployment_point_is_left_of_the_verified_red_boundary():
    scene = np.full((720, 1280, 3), (80, 150, 80), dtype=np.uint8)
    # The game renders its forbidden boundary orange-red, not pure red.
    cv2.line(scene, (420, 180), (420, 520), (68, 166, 181), 4)
    point = LootAttackExecutor.deployment_point(scene)
    assert point is not None
    assert abs(point[0] - 420) > 20
    assert 0 <= point[1] < scene.shape[0]


def test_deployment_point_rejects_a_scene_without_boundary():
    assert LootAttackExecutor.deployment_point(np.zeros((720, 1280, 3), dtype=np.uint8)) is None


def test_attack_log_resumes_without_overwriting_existing_events(tmp_path: Path):
    first = AttackLog(tmp_path, "session")
    first.record("first", np.zeros((8, 8, 3), dtype=np.uint8))
    resumed = AttackLog(tmp_path, "session")
    resumed.record("second", np.zeros((8, 8, 3), dtype=np.uint8))
    assert (tmp_path / "session" / "002_second.png").is_file()
