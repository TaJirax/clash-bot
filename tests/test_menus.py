import cv2
import numpy as np

from clashbot.menus import MenuRecognizer


def test_menu_recognizer_returns_only_a_learned_state(tmp_path):
    templates = {
        "inactivity_dialog_anchor.png": (20, 20, 20),
        "laboratory_menu_anchor.png": (30, 80, 180),
        "research_list_anchor.png": (80, 180, 30),
        "barracks_menu_anchor.png": (180, 30, 80),
        "troop_list_anchor.png": (120, 150, 20),
    }
    for filename, color in templates.items():
        image = np.full((20, 60, 3), color, dtype=np.uint8)
        image[:, 25:35] = (255, 255, 255)
        assert cv2.imwrite(str(tmp_path / filename), image)
    scene = np.zeros((720, 1280, 3), dtype=np.uint8)
    template = cv2.imread(str(tmp_path / "troop_list_anchor.png"))
    scene[80:100, 200:260] = template

    state = MenuRecognizer(tmp_path, threshold=0.95).classify(scene)

    assert state is not None
    assert state.name == "troop_list"
