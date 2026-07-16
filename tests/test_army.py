import cv2
import numpy as np

from clashbot.army import TroopRecognizer


def test_troop_recognizer_reports_learned_cards(tmp_path):
    names = ("barbarian", "goblin", "giant", "archer")
    scene = np.full((720, 1280, 3), 30, dtype=np.uint8)
    for index, name in enumerate(names):
        template = np.full((30, 25, 3), (20 + index * 30, 70, 160), dtype=np.uint8)
        cv2.circle(template, (12, 15), 8, (180, 30 + index * 40, 50), -1)
        assert cv2.imwrite(str(tmp_path / f"army_{name}.png"), template)
        x, y = 380 + index * 95, 200
        scene[y:y + template.shape[0], x:x + template.shape[1]] = template

    cards = TroopRecognizer(tmp_path, threshold=0.95).find(scene)

    assert [card.name for card in cards] == list(names)
    assert [card.x for card in cards] == [392, 487, 582, 677]
