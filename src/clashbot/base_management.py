"""Read-only base-management inspection used before any attack handoff."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .menus import MenuRecognizer
from .upgrades import BuildingRecognizer, ReferenceCatalog
from . import vision
from .paths import TEMPLATES_DIR
from .boosts import BoostRecognizer


@dataclass(frozen=True)
class BaseManagementStatus:
    recognized_buildings: int
    menu_state: str | None
    builders_available: int | None
    research_available: bool | None
    upgrade_affordable: bool | None
    boost_auras: int
    next_step: str
    collection_pending: bool | None = None
    army_ready: bool | None = None
    # The verified detections behind recognized_buildings, for layout tracking.
    targets: tuple = ()


@dataclass(frozen=True)
class BaseManagementPlan:
    """One safe, ordered scheduler decision; execution is a separate layer."""

    action: str
    reason: str
    phases: tuple[str, ...] = ()


def plan_base_management(status: BaseManagementStatus) -> BaseManagementPlan:
    """Choose the next base action using only verified evidence.

    The order mirrors normal progression: recover UI, collect, start research,
    spend builders on affordable upgrades, keep the army ready, and attack only
    when every higher-priority state is explicitly known to be clear.
    """
    if status.menu_state == "inactivity_dialog":
        return BaseManagementPlan("recover", "inactivity dialog blocks all base actions")
    if status.collection_pending is True:
        return BaseManagementPlan("collect", "verified resource bubbles are waiting")
    if status.research_available is True:
        return BaseManagementPlan("research", "laboratory research is idle and ready")
    if status.builders_available is not None and status.builders_available > 0:
        if status.upgrade_affordable is True:
            return BaseManagementPlan("upgrade", "free builder and affordable upgrade are verified")
        return BaseManagementPlan("inspect-upgrades", "free builder is verified; upgrade cost needs checking")
    if status.army_ready is False:
        return BaseManagementPlan("train", "army readiness is verified as incomplete")
    if any(value is None for value in (
        status.collection_pending, status.builders_available,
        status.research_available, status.upgrade_affordable, status.army_ready,
    )):
        return BaseManagementPlan("inspect", "base state is incomplete; do not attack on assumptions")
    return BaseManagementPlan(
        "attack", "verified base work is clear and army is ready",
        ("collect", "research", "upgrade", "train", "attack"),
    )


class BaseManagementInspector:
    """Return a fail-closed status for the base-to-attack scheduler.

    Builder availability, laboratory idle state, and resource affordability are
    deliberately ``None`` until their own live UI readers are trained.  The
    coordinator must not infer those values from decorative/game art.
    """

    def __init__(self, catalog: ReferenceCatalog | None = None,
                 menus: MenuRecognizer | None = None):
        self.buildings = BuildingRecognizer(catalog or ReferenceCatalog())
        self.menus = menus or MenuRecognizer()
        self.boosts = BoostRecognizer()
        self.builder_free = vision.load(str(TEMPLATES_DIR / "builder_free_1of1.png"))
        self.research_ready = vision.load(str(TEMPLATES_DIR / "laboratory_research_ready.png"))

    @staticmethod
    def _find(scene: np.ndarray, template: np.ndarray,
              roi: tuple[float, float, float, float], threshold: float) -> bool:
        h, w = scene.shape[:2]
        x1, y1, x2, y2 = roi
        left, top = int(x1 * w), int(y1 * h)
        part = scene[top:int(y2 * h), left:int(x2 * w)]
        return vision.find(
            part, template, threshold=threshold,
            scales=[vision.scale_for(scene) * value for value in (0.94, 1.0, 1.06)],
        ) is not None

    def inspect(self, scene: np.ndarray) -> BaseManagementStatus:
        matches = self.buildings.find(scene)
        menu = self.menus.classify(scene)
        builders = 1 if self._find(scene, self.builder_free, (0.28, 0.0, 0.55, 0.13), 0.90) else None
        research = True if self._find(scene, self.research_ready, (0.50, 0.12, 0.75, 0.30), 0.90) else None
        if menu is not None and menu.name == "inactivity_dialog":
            next_step = "recover: inactivity dialog is blocking the base"
        elif builders and research:
            next_step = "manage: free builder and idle laboratory are verified"
        elif menu is not None and menu.name in {"laboratory_menu", "research_list"}:
            next_step = "inspect: laboratory is open; research availability needs its learned control"
        else:
            next_step = "inspect: train builder, research, and upgrade UI readers before attack handoff"
        return BaseManagementStatus(
            recognized_buildings=len(matches),
            menu_state=None if menu is None else menu.name,
            builders_available=builders,
            research_available=research,
            upgrade_affordable=None,
            boost_auras=len(self.boosts.find(scene)),
            next_step=next_step,
            targets=tuple(matches),
        )
