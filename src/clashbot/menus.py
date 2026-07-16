"""Visual classification for the learned Laboratory and Barracks menu states."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import vision


@dataclass(frozen=True)
class MenuState:
    name: str
    score: float


class MenuRecognizer:
    """Classify only known, captured menu states; unknown screens stay unknown."""

    TEMPLATES = {
        "inactivity_dialog": "inactivity_dialog_anchor.png",
        "laboratory_menu": "laboratory_menu_anchor.png",
        "research_list": "research_list_anchor.png",
        "barracks_menu": "barracks_menu_anchor.png",
        "troop_list": "troop_list_anchor.png",
    }

    def __init__(self, template_dir: str | Path = "assets/templates", *, threshold: float = 0.86):
        root = Path(template_dir)
        self.threshold = threshold
        self.templates = {
            name: vision.load(str(root / filename))
            for name, filename in self.TEMPLATES.items()
        }

    def classify(self, scene: np.ndarray) -> MenuState | None:
        scale = vision.scale_for(scene)
        best: MenuState | None = None
        for name, template in self.templates.items():
            match = vision.find(
                scene, template, name=name, threshold=self.threshold,
                scales=[scale * value for value in (0.94, 1.0, 1.06)],
            )
            # A blocking inactivity dialog takes precedence over the dimmed
            # menu behind it.  Callers must never act on a hidden screen.
            if match is not None and name == "inactivity_dialog":
                return MenuState(name, match.score)
            if match is not None and (best is None or match.score > best.score):
                best = MenuState(name, match.score)
        return best
