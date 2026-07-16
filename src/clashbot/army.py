"""Read-only recognition of troop portraits in the Barracks army screen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import vision
from .paths import TEMPLATES_DIR


@dataclass(frozen=True)
class TroopCard:
    """A visually matched troop portrait in the currently visible army row."""

    name: str
    x: int
    y: int
    score: float


class TroopRecognizer:
    """Recognise learned troop portraits without tapping or changing the army.

    Templates are cropped from an actual Barracks screen.  The search is
    intentionally limited to the top army row, which prevents unrelated game
    art from being mistaken for a troop card.
    """

    NAMES = ("barbarian", "goblin", "giant", "archer")

    def __init__(self, template_dir: str | Path | None = None, *, threshold: float = 0.86):
        self.template_dir = Path(template_dir) if template_dir is not None else TEMPLATES_DIR
        self.threshold = threshold
        self.templates = {
            name: vision.load_template(str(self.template_dir / f"army_{name}.png"))
            for name in self.NAMES
        }

    def find(self, scene: np.ndarray) -> list[TroopCard]:
        height, width = scene.shape[:2]
        x1, x2 = int(0.27 * width), int(0.90 * width)
        y1, y2 = int(0.20 * height), int(0.43 * height)
        row = scene[y1:y2, x1:x2]
        base_scale = vision.scale_for(scene)
        cards: list[TroopCard] = []
        for name, (template, mask) in self.templates.items():
            match = vision.find(
                row,
                template,
                name=name,
                threshold=self.threshold,
                mask=mask,
                scales=[base_scale * value for value in (0.90, 0.95, 1.00, 1.05, 1.10)],
            )
            if match is not None:
                cards.append(TroopCard(name, match.center[0] + x1, match.center[1] + y1, match.score))
        return sorted(cards, key=lambda card: card.x)


class BattleTroopRecognizer(TroopRecognizer):
    """Recognise deployable troops in the bottom battle bar without tapping.

    The Barracks menu and the battle HUD use the same portrait art but place
    it in different screen regions.  Keeping the regions separate avoids a
    card being mistaken for a deployable troop while a menu is open.
    """

    def __init__(self, template_dir: str | Path | None = None, *, threshold: float = 0.78):
        super().__init__(template_dir, threshold=threshold)

    def find(self, scene: np.ndarray) -> list[TroopCard]:
        height, width = scene.shape[:2]
        x1, x2 = int(0.06 * width), int(0.55 * width)
        y1, y2 = int(0.78 * height), height
        row = scene[y1:y2, x1:x2]
        base_scale = vision.scale_for(scene)
        cards: list[TroopCard] = []
        for name, (template, mask) in self.templates.items():
            match = vision.find(
                row,
                template,
                name=name,
                threshold=self.threshold,
                mask=mask,
                scales=[base_scale * value for value in (0.90, 0.95, 1.00, 1.05, 1.10)],
            )
            if match is not None:
                cards.append(TroopCard(name, match.center[0] + x1, match.center[1] + y1, match.score))
        return sorted(cards, key=lambda card: card.x)
