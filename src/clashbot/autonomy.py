"""Autonomous, evidence-producing base scan with camera recovery."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np

from . import vision
from .adb_client import AdbClient
from .camera import CameraZoomController
from .asset_catalog import AssetCatalog
from .fankit import FanKitIndex
from .navigation import CameraPanController
from .upgrades import BuildingRecognizer, BuildingTarget


@dataclass(frozen=True)
class AutonomousView:
    id: int
    file: str
    action: str
    detections: int
    categories: int
    camera_scale: float | None


@dataclass(frozen=True)
class AutonomousScanReport:
    created_at: str
    views: tuple[AutonomousView, ...]
    best_view: int
    counts: dict[str, int]
    reference_assets: dict[str, int]
    reference_levels: dict[str, tuple[int, ...]]
    asset_roles: dict[str, dict[str, int]]
    recovery_actions: tuple[str, ...]
    blocked_reason: str | None
    unresolved_categories: tuple[str, ...]


def find_connection_retry(scene: np.ndarray) -> tuple[int, int] | None:
    """Return the retry label center only for the verified dark connection modal."""
    height, width = scene.shape[:2]
    hsv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)
    # The Android/Supercell modal uses a large charcoal panel and one cyan text
    # action. Requiring both prevents arbitrary blue HUD text from becoming a
    # click target.
    center = hsv[int(0.28 * height):int(0.70 * height),
                 int(0.18 * width):int(0.82 * width)]
    dark_fraction = float(np.mean(center[:, :, 2] < 75))
    if dark_fraction < 0.58:
        return None
    cyan = cv2.inRange(hsv, (80, 30, 110), (115, 255, 255))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(cyan)
    letters = []
    for x, y, w, h, area in stats[1:count]:
        if not (0.15 * width <= x <= 0.55 * width):
            continue
        if not (0.50 * height <= y <= 0.72 * height):
            continue
        if 2 <= w <= 0.04 * width and 6 <= h <= 0.05 * height and area >= 8:
            letters.append((x, y, w, h, area))
    if len(letters) < 4 or sum(item[4] for item in letters) < 120:
        return None
    x1 = min(item[0] for item in letters)
    y1 = min(item[1] for item in letters)
    x2 = max(item[0] + item[2] for item in letters)
    y2 = max(item[1] + item[3] for item in letters)
    return int((x1 + x2) // 2), int((y1 + y2) // 2)


class AutonomousBaseScanner:
    """Capture, recognize, and recover without user-supplied screenshots.

    A weak frame triggers one verified zoom attempt, followed by verified pans.
    The best observed view is reported; every raw frame is retained as evidence.
    No building is clicked during scanning.
    """

    def __init__(
        self,
        client: AdbClient,
        recognizer: BuildingRecognizer,
        *,
        pan: CameraPanController | None = None,
        zoom: CameraZoomController | None = None,
        fankit: FanKitIndex | None = None,
        asset_catalog: AssetCatalog | None = None,
        root: str | Path = "captures/autonomous",
        sleep=time.sleep,
        is_home: Callable[[np.ndarray], bool] | None = None,
    ):
        self.client = client
        self.recognizer = recognizer
        self.pan = pan or CameraPanController(client)
        self.zoom = zoom
        self.fankit = fankit or FanKitIndex()
        # The unified package cache is optional for tests/portable installs,
        # but a live CLI scan supplies it. It is manifest-only: no 3D model,
        # atlas or 17 GB image tree is decoded during a scan.
        self.asset_catalog = asset_catalog
        self.root = Path(root)
        self.sleep = sleep
        if is_home is None:
            from .attack import AttackUi
            is_home = AttackUi().is_home
        self.is_home = is_home

    @staticmethod
    def _strength(targets: list[BuildingTarget]) -> tuple[int, int, float]:
        return (
            len({target.category for target in targets}),
            len(targets),
            sum(target.score for target in targets),
        )

    def run(
        self,
        session: str,
        *,
        route: Iterable[str] = ("right", "left", "up", "down"),
        min_detections: int = 14,
        min_categories: int = 8,
    ) -> AutonomousScanReport:
        directory = self.root / session
        views_dir = directory / "views"
        views_dir.mkdir(parents=True, exist_ok=True)
        observations: list[tuple[AutonomousView, list[BuildingTarget]]] = []
        recovery: list[str] = []
        blocked_reason: str | None = None
        zoomed_in = False

        def observe(action: str) -> list[BuildingTarget]:
            nonlocal blocked_reason
            scene = vision.capture(self.client)
            retry = find_connection_retry(scene)
            retried = False
            for _attempt in range(2):
                if retry is None:
                    break
                self.client.tap(*retry)
                recovery.append("connection_retry")
                retried = True
                self.sleep(1.5)
                scene = vision.capture(self.client)
                retry = find_connection_retry(scene)
            if retry is not None:
                blocked_reason = "connection_lost"
            else:
                # A retry enters the full-screen loading artwork. Poll the
                # lightweight Attack-button home anchor before doing expensive
                # building recognition or camera input.
                attempts = 10 if retried else 1
                for attempt in range(attempts):
                    if self.is_home(scene):
                        break
                    if attempt + 1 < attempts:
                        self.sleep(1.0)
                        scene = vision.capture(self.client)
                blocked_reason = None if self.is_home(scene) else "not_home"
            targets = [] if blocked_reason else self.recognizer.find(scene)
            view_id = len(observations) + 1
            filename = f"{view_id:03d}.png"
            cv2.imwrite(str(views_dir / filename), scene)
            scales = sorted(target.camera_scale for target in targets)
            camera_scale = scales[len(scales) // 2] if scales else None
            record = AutonomousView(
                id=view_id,
                file=f"views/{filename}",
                action=action,
                detections=len(targets),
                categories=len({target.category for target in targets}),
                camera_scale=camera_scale,
            )
            observations.append((record, targets))
            return targets

        current = observe("capture")
        catalog = getattr(self.recognizer, "catalog", None)
        expected_categories = {
            spec.category for spec in getattr(catalog, "specs", ())
        }
        current_categories = {target.category for target in current}
        if blocked_reason:
            weak = False
            route = ()
        else:
            weak = (
                len(current) < min_detections
                or len(current_categories) < min_categories
                or (
                    expected_categories
                    and len(current_categories & expected_categories)
                    < 0.75 * len(expected_categories)
                )
            )
        if weak and self.zoom is not None:
            result = self.zoom.adjust("in")
            recovery.append(f"zoom_in:{'verified' if result.verified else 'failed'}")
            if result.verified:
                zoomed_in = True
                current = observe("zoom_in")

        # Camera movement is useful both for recovery and for buildings hidden
        # by dense layouts. Stop repeating a direction when the game itself
        # does not verify movement.
        for direction in route:
            result = self.pan.pan(direction)
            recovery.append(f"pan_{direction}:{'verified' if result.verified else 'failed'}")
            if result.verified:
                observe(f"pan_{direction}")

        seen_categories = {
            target.category
            for _record, targets in observations
            for target in targets
        }
        if (
            self.zoom is not None
            and (
                zoomed_in
                or (
                    expected_categories
                    and len(seen_categories & expected_categories)
                    < 0.75 * len(expected_categories)
                )
            )
        ):
            result = self.zoom.adjust("out")
            recovery.append(f"zoom_out:{'verified' if result.verified else 'failed'}")
            if result.verified:
                observe("zoom_out")

        best_record, best_targets = max(
            observations,
            key=lambda item: self._strength(item[1]),
        )
        # A pan can hide an edge building. The maximum count seen for each
        # category is safer than summing duplicate views or trusting only one.
        per_view_counts = [Counter(target.category for target in targets)
                           for _record, targets in observations]
        counts = {
            category: max(view.get(category, 0) for view in per_view_counts)
            for category in sorted({key for view in per_view_counts for key in view})
        }
        reference_assets = {}
        reference_levels = {}
        asset_roles: dict[str, dict[str, int]] = {}
        for category in counts:
            if self.asset_catalog is None:
                reference_assets[category] = len(self.fankit.assets_for(category))
                reference_levels[category] = self.fankit.levels_for(category)
                asset_roles[category] = {"labelled_reference": reference_assets[category]}
                continue
            records = self.asset_catalog.find(
                category, roles={"labelled_reference", "vector_composition"}
            )
            role_counts = Counter(record.role for record in records)
            reference_assets[category] = len(records)
            reference_levels[category] = tuple(sorted({
                record.level for record in records if record.level is not None
            }))
            asset_roles[category] = dict(sorted(role_counts.items()))
        report = AutonomousScanReport(
            created_at=datetime.now(timezone.utc).isoformat(),
            views=tuple(record for record, _targets in observations),
            best_view=best_record.id,
            counts=counts,
            reference_assets=reference_assets,
            reference_levels=reference_levels,
            asset_roles=asset_roles,
            recovery_actions=tuple(recovery),
            blocked_reason=blocked_reason,
            unresolved_categories=tuple(sorted(expected_categories - set(counts))),
        )
        temporary = directory / "report.json.tmp"
        final = directory / "report.json"
        temporary.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
        temporary.replace(final)
        return report
