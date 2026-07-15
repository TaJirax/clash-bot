import cv2
import numpy as np

from clashbot.camera import CameraZoomController, estimate_camera_scale
from clashbot.upgrades import BuildingTarget


def _png():
    ok, encoded = cv2.imencode(".png", np.zeros((72, 128, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


class FakeClient:
    def __init__(self, scale=1.0, responds=True):
        self.scale = scale
        self.responds = responds
        self.keys = []

    def screenshot(self):
        return _png()

    def keyevent(self, keycode):
        self.keys.append(keycode)
        if self.responds:
            self.scale += 0.1 if keycode == "KEYCODE_ZOOM_IN" else -0.1


class FakeRecognizer:
    def __init__(self, client):
        self.client = client

    def find(self, _scene):
        return [BuildingTarget("town_hall", "th", 10, 10, 0.95,
                               camera_scale=self.client.scale)]


class FakeActuator:
    def __init__(self, client):
        self.client = client
        self.directions = []

    def zoom(self, direction):
        self.directions.append(direction)
        self.client.scale += 0.1 if direction == "in" else -0.1


def _controller(client):
    return CameraZoomController(client, FakeRecognizer(client), settle_seconds=0,
                                sleep=lambda _seconds: None)


def test_estimate_camera_scale_uses_confidence_weighted_median():
    targets = [
        BuildingTarget("x", "a", 0, 0, 0.9, camera_scale=0.8),
        BuildingTarget("x", "b", 0, 0, 0.2, camera_scale=1.3),
    ]
    assert estimate_camera_scale(targets) == 0.8


def test_zoom_in_is_verified_from_recognized_scale_change():
    client = FakeClient()
    result = _controller(client).adjust("in", steps=2)
    assert result.verified
    assert result.before_scale == 1.0
    assert abs(result.after_scale - 1.2) < 1e-9
    assert client.keys == ["KEYCODE_ZOOM_IN", "KEYCODE_ZOOM_IN"]


def test_unsupported_zoom_does_not_verify():
    client = FakeClient(responds=False)
    result = _controller(client).adjust("out")
    assert not result.verified
    assert result.before_scale == result.after_scale


def test_external_actuator_is_used_instead_of_android_keyevent():
    client = FakeClient(responds=False)
    actuator = FakeActuator(client)
    controller = CameraZoomController(
        client, FakeRecognizer(client), actuator=actuator,
        settle_seconds=0, sleep=lambda _seconds: None,
    )
    result = controller.adjust("out")
    assert result.verified
    assert actuator.directions == ["out"]
    assert client.keys == []


def test_normalize_moves_one_verified_step_at_a_time():
    client = FakeClient(scale=1.2)
    results = _controller(client).normalize(0.8, max_steps=6)
    assert len(results) == 4
    assert all(result.verified for result in results)
    assert abs(client.scale - 0.8) < 1e-9
