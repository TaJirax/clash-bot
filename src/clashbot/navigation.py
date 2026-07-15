"""Verified village camera panning and multi-view base mapping."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from . import vision
from .adb_client import AdbClient
from .human import HumanInput
from .upgrades import BuildingRecognizer, BuildingTarget


DIRECTION_CONTENT_SIGN = {
    # Moving the camera up means dragging map content down, and so on.
    "up": (0, 1),
    "down": (0, -1),
    "left": (1, 0),
    "right": (-1, 0),
}


@dataclass(frozen=True)
class PanResult:
    direction: str
    content_dx: float
    content_dy: float
    response: float
    verified: bool


def estimate_translation(before: np.ndarray, after: np.ndarray) -> tuple[float, float, float]:
    """Estimate map-content translation while excluding static edge controls."""
    if before.shape != after.shape:
        raise ValueError("before and after screenshots must have the same shape")
    height, width = before.shape[:2]
    x1, x2 = int(width * 0.14), int(width * 0.86)
    y1, y2 = int(height * 0.13), int(height * 0.78)

    def features(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        return cv2.magnitude(gx, gy)

    first, second = features(before), features(after)
    window = cv2.createHanningWindow((first.shape[1], first.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(first, second, window)
    return float(dx), float(dy), float(response)


class CameraPanController:
    def __init__(self, client: AdbClient, human: HumanInput | None = None):
        self.client = client
        self.human = human or HumanInput(client)

    def pan(self, direction: str, *, distance: float = 0.22) -> PanResult:
        if direction not in DIRECTION_CONTENT_SIGN:
            raise ValueError("direction must be up, down, left, or right")
        if not 0.06 <= distance <= 0.40:
            raise ValueError("distance must be between 0.06 and 0.40")

        before = vision.decode(self.client.screenshot())
        height, width = before.shape[:2]
        center_x, center_y = width // 2, height // 2
        sign_x, sign_y = DIRECTION_CONTENT_SIGN[direction]
        travel_x = round(width * distance) * sign_x
        travel_y = round(height * distance) * sign_y
        self.human.swipe(
            center_x,
            center_y,
            center_x + travel_x,
            center_y + travel_y,
            duration_ms=420,
        )
        after = vision.decode(self.client.screenshot())
        dx, dy, response = estimate_translation(before, after)

        expected = dx * sign_x if sign_x else dy * sign_y
        minimum = (width if sign_x else height) * 0.025
        verified = expected >= minimum and response >= 0.05
        return PanResult(direction, dx, dy, response, verified)


@dataclass
class MappedBuilding:
    category: str
    name: str
    map_x: float
    map_y: float
    score: float
    camera_scale: float
    view_id: int
    screen_x: int
    screen_y: int


_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class BaseMapper:
    """Scan a route and merge detections into one camera-independent map."""

    def __init__(
        self,
        client: AdbClient,
        recognizer: BuildingRecognizer,
        pan: CameraPanController,
        *,
        root: str | Path = "captures/maps",
        session: str = "base_map",
    ):
        if not _SAFE_NAME.fullmatch(session):
            raise ValueError("session must contain only letters, numbers, _ or -")
        self.client = client
        self.recognizer = recognizer
        self.pan_controller = pan
        self.directory = Path(root) / session
        self.views_directory = self.directory / "views"

    @staticmethod
    def _merge(buildings: list[MappedBuilding], target: MappedBuilding) -> None:
        gap = max(24.0, 55.0 * target.camera_scale)
        for index, existing in enumerate(buildings):
            if existing.category != target.category:
                continue
            distance_sq = ((existing.map_x - target.map_x) ** 2
                           + (existing.map_y - target.map_y) ** 2)
            if distance_sq <= gap ** 2:
                if target.score > existing.score:
                    buildings[index] = target
                return
        buildings.append(target)

    def scan(self, route: Iterable[str]) -> dict:
        self.views_directory.mkdir(parents=True, exist_ok=True)
        cumulative_x = cumulative_y = 0.0
        mapped: list[MappedBuilding] = []
        views: list[dict] = []

        directions: list[str | None] = [None, *list(route)]
        for view_index, direction in enumerate(directions, start=1):
            pan_record = None
            if direction is not None:
                result = self.pan_controller.pan(direction)
                pan_record = asdict(result)
                if result.verified:
                    cumulative_x += result.content_dx
                    cumulative_y += result.content_dy

            scene = vision.decode(self.client.screenshot())
            targets = self.recognizer.find(scene)
            filename = f"{view_index:03d}.png"
            cv2.imwrite(str(self.views_directory / filename), scene)
            for target in targets:
                self._merge(mapped, MappedBuilding(
                    category=target.category,
                    name=target.name,
                    map_x=target.x - cumulative_x,
                    map_y=target.y - cumulative_y,
                    score=target.score,
                    camera_scale=target.camera_scale,
                    view_id=view_index,
                    screen_x=target.x,
                    screen_y=target.y,
                ))
            views.append({
                "id": view_index,
                "file": f"views/{filename}",
                "requested_pan": direction,
                "pan": pan_record,
                "cumulative_content_offset": [cumulative_x, cumulative_y],
                "detections": len(targets),
            })

        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "views": views,
            "buildings": [asdict(building) for building in mapped],
        }
        path = self.directory / "map.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return manifest
