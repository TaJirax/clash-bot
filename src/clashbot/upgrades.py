"""Building recognition and conservative automatic upgrades.

The recognizer is deliberately data driven.  ``assets/buildings.json`` points
at clean in-game reference images and rectangular crops within those images;
adding another building level therefore does not require a code change.

An upgrade attempt is a small state machine:

1. recognise a building on the home-village screen and select it;
2. find the hammer in the selected-building toolbar;
3. open the upgrade details and click only a green resource-cost button;
4. leave any remaining details/modal before considering another building.

It never follows a second dialog.  In particular, an insufficient-resource
dialog cannot turn into a gem purchase because the bot immediately backs out
instead of clicking anything in that dialog.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np

from . import vision
from .adb_client import AdbClient
from .human import HumanInput


PRIORITY = (
    "town_hall",
    "gold_mine",
    "elixir_collector",
    "dark_elixir_drill",
    "gold_storage",
    "elixir_storage",
    "dark_elixir_storage",
    "wall",
)

# Avoid the player badge, resource bars, side buttons, shop, and attack button.
VILLAGE_FRAC = (0.10, 0.08, 0.84, 0.82)
TOOLBAR_FRAC = (0.16, 0.64, 0.84, 0.94)


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    category: str
    source: str
    crop: tuple[int, int, int, int]
    threshold: float = 0.82
    max_matches: int = 20


@dataclass(frozen=True)
class UiSpec:
    source: str
    crop: tuple[int, int, int, int]
    threshold: float = 0.48
    scales: tuple[float, ...] = (0.62, 0.72, 0.82, 0.92, 1.02)


@dataclass
class BuildingTarget:
    category: str
    name: str
    x: int
    y: int
    score: float
    radius: float = 10.0
    camera_scale: float = 1.0


@dataclass
class ScanResult:
    found: dict[str, int] = field(default_factory=dict)
    attempted: list[BuildingTarget] = field(default_factory=list)
    unavailable: list[BuildingTarget] = field(default_factory=list)

    @property
    def attempts(self) -> int:
        return len(self.attempted)


class ReferenceCatalog:
    """Loads building/UI crops described by a JSON catalog."""

    def __init__(self, path: str = "assets/buildings.json"):
        self.path = Path(path)
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self.base_dir = self.path.resolve().parent
        self.reference_size = tuple(data.get("reference_size", vision.REFERENCE_SIZE))
        self.camera_scales = tuple(float(value) for value in data.get(
            "camera_scales", (0.35, 0.45, 0.55, 0.65, 0.75, 0.85,
                              0.95, 1.05, 1.15, 1.25, 1.35)
        ))
        if not self.camera_scales or any(value <= 0 for value in self.camera_scales):
            raise ValueError("camera_scales must contain positive values")
        self.specs = [self._building_spec(item) for item in data.get("templates", [])]
        if not self.specs:
            raise ValueError(f"no building templates configured in {path!r}")
        ui = data.get("ui", {}).get("upgrade_hammer")
        if not ui:
            raise ValueError(f"no ui.upgrade_hammer configured in {path!r}")
        self.ui_spec = UiSpec(
            source=self._resolve(ui["source"]),
            crop=self._crop(ui["crop"]),
            threshold=float(ui.get("threshold", 0.48)),
            scales=tuple(float(s) for s in ui.get(
                "scales", (0.62, 0.72, 0.82, 0.92, 1.02))),
        )
        self._sources: dict[str, np.ndarray] = {}

    def _resolve(self, value: str) -> str:
        p = Path(os.path.expandvars(os.path.expanduser(value)))
        if not p.is_absolute():
            p = self.base_dir / p
        return str(p.resolve())

    @staticmethod
    def _crop(value: Iterable[int]) -> tuple[int, int, int, int]:
        crop = tuple(int(v) for v in value)
        if len(crop) != 4:
            raise ValueError(f"crop must be [x1,y1,x2,y2], got {crop!r}")
        x1, y1, x2, y2 = crop
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"invalid crop {crop!r}")
        return crop

    def _building_spec(self, item: dict) -> TemplateSpec:
        return TemplateSpec(
            name=str(item["name"]),
            category=str(item["category"]),
            source=self._resolve(item["source"]),
            crop=self._crop(item["crop"]),
            threshold=float(item.get("threshold", 0.82)),
            max_matches=int(item.get("max_matches", 20)),
        )

    def crop(self, source: str, box: tuple[int, int, int, int]) -> np.ndarray:
        image = self._sources.get(source)
        if image is None:
            image = vision.load(source)
            self._sources[source] = image
        x1, y1, x2, y2 = box
        if x1 < 0 or y1 < 0 or x2 > image.shape[1] or y2 > image.shape[0]:
            raise ValueError(f"crop {box!r} lies outside {source!r} ({image.shape[1]}x{image.shape[0]})")
        return image[y1:y2, x1:x2].copy()


class BuildingRecognizer:
    def __init__(self, catalog: ReferenceCatalog):
        self.catalog = catalog
        self.templates = [(spec, catalog.crop(spec.source, spec.crop)) for spec in catalog.specs]

    def find(self, scene: np.ndarray) -> list[BuildingTarget]:
        h, w = scene.shape[:2]
        resolution_scale = min(
            w / self.catalog.reference_size[0],
            h / self.catalog.reference_size[1],
        )
        scales = [resolution_scale * value for value in self.catalog.camera_scales]
        vx1, vy1, vx2, vy2 = VILLAGE_FRAC
        bounds = (vx1 * w, vy1 * h, vx2 * w, vy2 * h)

        candidates: list[tuple[TemplateSpec, vision.Match]] = []
        for spec, template in self.templates:
            hits = vision.find_all(
                scene,
                template,
                name=spec.name,
                threshold=spec.threshold,
                scales=scales,
            )
            accepted = []
            for hit in hits:
                cx, cy = hit.center
                if bounds[0] <= cx <= bounds[2] and bounds[1] <= cy <= bounds[3]:
                    accepted.append(hit)
            candidates.extend((spec, hit) for hit in accepted[:spec.max_matches])

        # De-duplicate overlapping reference crops, including two templates for
        # adjacent levels of the same physical building.
        candidates.sort(key=lambda pair: pair[1].score, reverse=True)
        kept: list[tuple[TemplateSpec, vision.Match]] = []
        for spec, hit in candidates:
            cx, cy = hit.center
            gap = max(12, min(hit.w, hit.h) // 2)
            if any((cx - old.center[0]) ** 2 + (cy - old.center[1]) ** 2 < gap ** 2
                   for _old_spec, old in kept):
                continue
            kept.append((spec, hit))

        return [
            BuildingTarget(
                category=spec.category,
                name=spec.name,
                x=hit.center[0],
                y=hit.center[1],
                score=hit.score,
                radius=max(7.0, min(hit.w, hit.h) * 0.18),
                camera_scale=hit.scale / resolution_scale,
            )
            for spec, hit in kept
        ]


class UpgradeUi:
    """Recognises only the two controls needed by the upgrade state machine."""

    def __init__(self, catalog: ReferenceCatalog):
        self.catalog = catalog
        spec = catalog.ui_spec
        self.hammer = catalog.crop(spec.source, spec.crop)
        self.spec = spec

    @staticmethod
    def _roi(scene: np.ndarray, frac: tuple[float, float, float, float]):
        h, w = scene.shape[:2]
        fx1, fy1, fx2, fy2 = frac
        x1, y1, x2, y2 = int(fx1 * w), int(fy1 * h), int(fx2 * w), int(fy2 * h)
        return scene[y1:y2, x1:x2], x1, y1

    def find_hammer(self, scene: np.ndarray) -> vision.Match | None:
        roi, ox, oy = self._roi(scene, TOOLBAR_FRAC)
        base_scale = scene.shape[1] / self.catalog.reference_size[0]
        match = vision.find(
            roi,
            self.hammer,
            name="upgrade_hammer",
            threshold=self.spec.threshold,
            scales=[base_scale * s for s in self.spec.scales],
        )
        if match is None:
            return None
        match.x += ox
        match.y += oy
        return match

    @staticmethod
    def find_resource_confirm(scene: np.ndarray) -> vision.Match | None:
        """Find the green cost button on the upgrade-details screen.

        The search is intentionally limited to the lower central screen.  It
        rejects tiny green badges and large panels.  This method is called only
        immediately after a positively matched hammer, never on arbitrary UI.
        """
        h, w = scene.shape[:2]
        x1, x2 = int(0.18 * w), int(0.82 * w)
        y1, y2 = int(0.52 * h), int(0.92 * h)
        roi = scene[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(hsv, (35, 75, 55), (95, 255, 255))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        choices: list[vision.Match] = []
        for contour in contours:
            rx, ry, rw, rh = cv2.boundingRect(contour)
            if not (0.07 * w <= rw <= 0.36 * w and 0.045 * h <= rh <= 0.18 * h):
                continue
            area = max(1, rw * rh)
            fill = cv2.contourArea(contour) / area
            if fill < 0.32:
                continue
            choices.append(vision.Match(
                name="resource_upgrade_confirm",
                x=x1 + rx,
                y=y1 + ry,
                w=rw,
                h=rh,
                score=min(1.0, float(fill)),
            ))
        if not choices:
            return None
        # Upgrade cost button is normally the widest lower-centre candidate.
        return max(choices, key=lambda m: (m.w * m.h, m.y))


class SafeIdleTouch:
    """Chooses a visually uniform grass patch, away from game controls."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()

    def point(self, scene: np.ndarray) -> tuple[int, int] | None:
        h, w = scene.shape[:2]
        hsv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)
        # Home-village grass: broad enough for seasonal greens, but only accept
        # places whose whole local neighbourhood is grass-like.
        grass = cv2.inRange(hsv, (28, 45, 45), (92, 255, 255))
        radius = max(8, round(min(w, h) * 0.018))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
        safe = cv2.erode(grass, kernel)

        allowed = np.zeros_like(safe)
        allowed[int(0.13 * h):int(0.77 * h), int(0.13 * w):int(0.84 * w)] = 255
        safe = cv2.bitwise_and(safe, allowed)
        ys, xs = np.where(safe > 0)
        if not len(xs):
            return None
        index = self.rng.randrange(len(xs))
        return int(xs[index]), int(ys[index])


class UpgradeBot:
    def __init__(self, client: AdbClient, *, catalog_path: str = "assets/buildings.json",
                 human: HumanInput | None = None, rng: random.Random | None = None):
        self.client = client
        self.rng = rng or random.Random()
        self.human = human or HumanInput(client, rng=self.rng)
        self.catalog = ReferenceCatalog(catalog_path)
        self.recognizer = BuildingRecognizer(self.catalog)
        self.ui = UpgradeUi(self.catalog)
        self.idle = SafeIdleTouch(self.rng)
        self._known: dict[str, list[BuildingTarget]] = {}

    def _targets(self, scene: np.ndarray) -> list[BuildingTarget]:
        fresh = self.recognizer.find(scene)
        by_category: dict[str, list[BuildingTarget]] = {}
        for target in fresh:
            by_category.setdefault(target.category, []).append(target)
        # Keep coordinates during this run after a building changes appearance
        # at the end of an upgrade.  A fresh positive match always replaces the
        # remembered coordinates for that category.
        for category, targets in by_category.items():
            self._known[category] = targets
        out = []
        for category in PRIORITY:
            out.extend(sorted(self._known.get(category, []), key=lambda t: (-t.score, t.y, t.x)))
        return out

    def _deselect(self, scene: np.ndarray | None = None) -> None:
        scene = scene if scene is not None else vision.capture(self.client)
        point = self.idle.point(scene)
        if point is not None:
            self.human.tap(*point, radius=4.0)

    def scan_once(self, *, dry_run: bool = False,
                  log: Callable[[str], None] = print) -> ScanResult:
        scene = vision.capture(self.client)
        targets = self._targets(scene)
        result = ScanResult()
        for target in targets:
            result.found[target.category] = result.found.get(target.category, 0) + 1
        summary = ", ".join(f"{name}={count}" for name, count in result.found.items()) or "none"
        log(f"buildings: {summary}")
        if dry_run:
            return result

        for target in targets:
            self.human.tap(target.x, target.y, radius=target.radius)
            selected = vision.capture(self.client)
            hammer = self.ui.find_hammer(selected)
            if hammer is None:
                # Lower-end or busy emulators occasionally return a frame from
                # the toolbar's opening animation. Recheck once without
                # issuing another tap; a second tap could toggle game UI.
                self.human.wait(0.6, 0.9)
                selected = vision.capture(self.client)
                hammer = self.ui.find_hammer(selected)
            if hammer is None:
                result.unavailable.append(target)
                log(f"{target.category}/{target.name}: no upgrade hammer")
                self._deselect(selected)
                continue

            self.human.tap(*hammer.center, radius=max(5.0, min(hammer.w, hammer.h) * 0.22))
            details = vision.capture(self.client)
            confirm = self.ui.find_resource_confirm(details)
            if confirm is None:
                result.unavailable.append(target)
                log(f"{target.category}/{target.name}: upgrade is not currently affordable/available")
                self.client.back()
                self.human.wait()
                continue

            # This is the only tap issued on the details screen.  Whether the
            # game starts the upgrade or opens an insufficient-resource dialog,
            # gem offers are never followed.
            self.human.tap(*confirm.center, radius=max(5.0, min(confirm.w, confirm.h) * 0.20))
            result.attempted.append(target)
            log(f"{target.category}/{target.name}: pressed resource upgrade")
            after = vision.capture(self.client)
            if self.ui.find_resource_confirm(after) is not None:
                # Still on details or an insufficient-resource/gem offer modal.
                # BACK is safe here and, crucially, we never click that offer.
                self.client.back()
                self.human.wait()
            else:
                # A successful upgrade normally returns directly to the base.
                # Do not press Android BACK there: it opens the quit-game dialog.
                self._deselect(after)

        return result

    def idle_touch(self, log: Callable[[str], None] = print) -> bool:
        scene = vision.capture(self.client)
        point = self.idle.point(scene)
        if point is None:
            log("anti-idle: no safe grass patch found; skipped")
            return False
        self.human.tap(*point, radius=5.0, settle=False)
        log(f"anti-idle: touched safe grass near ({point[0]}, {point[1]})")
        return True

    def run(self, *, scans: int = 0, scan_interval: float = 600.0,
            idle_range: tuple[float, float] = (30.0, 60.0), dry_run: bool = False,
            log: Callable[[str], None] = print,
            clock: Callable[[], float] = time.monotonic,
            sleep: Callable[[float], None] = time.sleep) -> int:
        """Run scheduled scans; ``scans=0`` means until interrupted."""
        if scan_interval <= 0:
            raise ValueError("scan_interval must be positive")
        idle_min, idle_max = idle_range
        if idle_min <= 0 or idle_max < idle_min:
            raise ValueError("idle range must satisfy 0 < min <= max")

        completed = 0
        while scans == 0 or completed < scans:
            self.scan_once(dry_run=dry_run, log=log)
            completed += 1
            if scans and completed >= scans:
                break

            next_scan = clock() + scan_interval
            while True:
                remaining = next_scan - clock()
                if remaining <= 0:
                    break
                delay = min(remaining, self.rng.uniform(idle_min, idle_max))
                sleep(delay)
                if not dry_run and delay < remaining:
                    self.idle_touch(log=log)
        return completed
