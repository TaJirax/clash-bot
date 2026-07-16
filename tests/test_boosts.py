import cv2
import numpy as np

from clashbot.boosts import BoostRecognizer


def test_boost_recognizer_reports_a_bright_lime_aura():
    scene = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.circle(scene, (100, 100), 35, (0, 255, 100), 8)
    assert BoostRecognizer().find(scene)
