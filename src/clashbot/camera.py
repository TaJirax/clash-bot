"""Verified game-camera zoom control.

Android defines ZOOM_IN and ZOOM_OUT key events. Some emulators forward them
to games and some do not, so every operation measures building scale before
and after the event. Unsupported controls therefore fail visibly instead of
silently leaving the mapper at an unexpected camera scale.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from . import vision
from .adb_client import AdbClient
from .upgrades import BuildingRecognizer, BuildingTarget


class Recognizer(Protocol):
    def find(self, scene): ...


class ZoomActuator(Protocol):
    def zoom(self, direction: str) -> None: ...


@dataclass(frozen=True)
class ZoomResult:
    direction: str
    requested_steps: int
    before_scale: float | None
    after_scale: float | None
    verified: bool


def estimate_camera_scale(targets: list[BuildingTarget]) -> float | None:
    """Return a confidence-weighted median camera scale from recognized items."""
    usable = sorted(
        (target.camera_scale, max(0.0, target.score))
        for target in targets
        if target.camera_scale > 0 and target.score > 0
    )
    if not usable:
        return None
    total = sum(weight for _scale, weight in usable)
    midpoint = total / 2
    accumulated = 0.0
    for scale, weight in usable:
        accumulated += weight
        if accumulated >= midpoint:
            return scale
    return usable[-1][0]


class CameraZoomController:
    KEYCODES = {
        "in": "KEYCODE_ZOOM_IN",
        "out": "KEYCODE_ZOOM_OUT",
    }

    def __init__(
        self,
        client: AdbClient,
        recognizer: Recognizer,
        *,
        settle_seconds: float = 0.8,
        sleep: Callable[[float], None] = time.sleep,
        actuator: ZoomActuator | None = None,
    ):
        self.client = client
        self.recognizer = recognizer
        self.settle_seconds = settle_seconds
        self.sleep = sleep
        self.actuator = actuator

    def measure(self) -> float | None:
        scene = vision.decode(self.client.screenshot())
        return estimate_camera_scale(self.recognizer.find(scene))

    def adjust(self, direction: str, *, steps: int = 1) -> ZoomResult:
        if direction not in self.KEYCODES:
            raise ValueError("direction must be 'in' or 'out'")
        if not 1 <= steps <= 10:
            raise ValueError("steps must be between 1 and 10")

        before = self.measure()
        for _ in range(steps):
            if self.actuator is None:
                self.client.keyevent(self.KEYCODES[direction])
            else:
                self.actuator.zoom(direction)
            self.sleep(0.12)
        self.sleep(self.settle_seconds)
        after = self.measure()

        tolerance = 0.02
        verified = (
            before is not None
            and after is not None
            and (
                after > before + tolerance
                if direction == "in"
                else after < before - tolerance
            )
        )
        return ZoomResult(direction, steps, before, after, verified)

    def normalize(
        self,
        target: float,
        *,
        tolerance: float = 0.06,
        max_steps: int = 6,
    ) -> list[ZoomResult]:
        """Move toward ``target`` one verified step at a time."""
        if target <= 0:
            raise ValueError("target must be positive")
        if tolerance <= 0:
            raise ValueError("tolerance must be positive")
        if not 1 <= max_steps <= 20:
            raise ValueError("max_steps must be between 1 and 20")

        results: list[ZoomResult] = []
        current = self.measure()
        if current is None:
            return results
        for _ in range(max_steps):
            if abs(current - target) <= tolerance:
                break
            direction = "in" if current < target else "out"
            result = self.adjust(direction)
            results.append(result)
            if not result.verified or result.after_scale is None:
                break
            current = result.after_scale
        return results


def controller_from_catalog(
    client: AdbClient,
    catalog_path: str,
    *,
    actuator: ZoomActuator | None = None,
) -> CameraZoomController:
    """Construct a controller using the normal building reference catalog."""
    from .upgrades import ReferenceCatalog

    catalog = ReferenceCatalog(catalog_path)
    # Mapping scans use a coarser sweep for speed. Camera verification needs a
    # finer scale ruler because a single Ctrl+wheel/MEmu notch is only a small
    # visual change.
    catalog.camera_scales = (
        0.25, 0.30, 0.38, 0.46, 0.55, 0.65, 0.75, 0.85,
        0.95, 1.00, 1.05, 1.15, 1.25, 1.35, 1.45, 1.60,
        1.80, 2.00,
    )
    return CameraZoomController(
        client,
        BuildingRecognizer(catalog),
        actuator=actuator,
    )
