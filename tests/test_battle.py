import numpy as np

from clashbot.army import BattleTroopRecognizer


def test_battle_recognizer_ignores_an_empty_battle_bar():
    scene = np.zeros((720, 1280, 3), dtype=np.uint8)
    assert BattleTroopRecognizer().find(scene) == []
