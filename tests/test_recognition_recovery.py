import cv2

from clashbot.upgrades import BuildingRecognizer, ReferenceCatalog


def test_building_recognizer_recovers_from_extreme_wide_scale():
    scene = cv2.imread("base_now.png", cv2.IMREAD_COLOR)
    assert scene is not None
    wide = cv2.resize(scene, (0, 0), fx=0.38, fy=0.38)
    canvas = cv2.resize(scene, (1280, 720))
    canvas[:] = (70, 145, 70)
    y = (720 - wide.shape[0]) // 2
    x = (1280 - wide.shape[1]) // 2
    canvas[y:y + wide.shape[0], x:x + wide.shape[1]] = wide
    assert BuildingRecognizer(ReferenceCatalog()).find(canvas)
