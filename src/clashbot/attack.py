"""Visually guarded navigation from the home village to the Attack menu."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import vision
from .adb_client import AdbClient
from .human import HumanInput


@dataclass(frozen=True)
class OpenAttackResult:
    button_score: float
    menu_score: float | None
    opened: bool


@dataclass(frozen=True)
class FindMatchResult:
    prepared: bool
    opponent_found: bool
    returned_home: bool


class AttackUi:
    def __init__(
        self,
        button: np.ndarray | None = None,
        menu_anchor: np.ndarray | None = None,
        *,
        button_path: str = "assets/templates/attack_button.png",
        menu_path: str = "assets/templates/attack_menu_multiplayer.png",
        find_match_path: str = "assets/templates/find_match_button.png",
        army_path: str = "assets/templates/army_confirmation_anchor.png",
        confirm_path: str = "assets/templates/confirm_find_match_button.png",
        scout_path: str = "assets/templates/opponent_scout_end_battle.png",
    ):
        self.button = button if button is not None else vision.load(button_path)
        self.menu_anchor = menu_anchor if menu_anchor is not None else vision.load(menu_path)
        self.find_match = vision.load(find_match_path)
        self.army_confirmation = vision.load(army_path)
        self.confirm_match = vision.load(confirm_path)
        self.opponent_scout = vision.load(scout_path)

    @staticmethod
    def _roi(scene: np.ndarray, frac: tuple[float, float, float, float]):
        height, width = scene.shape[:2]
        x1, y1, x2, y2 = frac
        left, top = int(x1 * width), int(y1 * height)
        right, bottom = int(x2 * width), int(y2 * height)
        return scene[top:bottom, left:right], left, top

    def find_button(self, scene: np.ndarray) -> vision.Match | None:
        roi, offset_x, offset_y = self._roi(scene, (0.0, 0.68, 0.20, 1.0))
        match = vision.find(
            roi,
            self.button,
            name="attack_button",
            threshold=0.82,
            scales=[vision.scale_for(scene) * value for value in (0.94, 1.0, 1.06)],
        )
        if match is not None:
            match.x += offset_x
            match.y += offset_y
        return match

    def find_menu(self, scene: np.ndarray) -> vision.Match | None:
        roi, offset_x, offset_y = self._roi(scene, (0.0, 0.0, 0.68, 0.22))
        match = vision.find(
            roi,
            self.menu_anchor,
            name="attack_menu_multiplayer",
            threshold=0.82,
            scales=[vision.scale_for(scene) * value for value in (0.94, 1.0, 1.06)],
        )
        if match is not None:
            match.x += offset_x
            match.y += offset_y
        return match

    def _find_control(self, scene: np.ndarray, template: np.ndarray, name: str,
                      roi_frac: tuple[float, float, float, float],
                      threshold: float = 0.82) -> vision.Match | None:
        roi, offset_x, offset_y = self._roi(scene, roi_frac)
        match = vision.find(
            roi, template, name=name, threshold=threshold,
            scales=[vision.scale_for(scene) * value for value in (0.94, 1.0, 1.06)],
        )
        if match is not None:
            match.x += offset_x
            match.y += offset_y
        return match

    def find_find_match(self, scene: np.ndarray) -> vision.Match | None:
        return self._find_control(
            scene, self.find_match, "find_match", (0.0, 0.55, 0.48, 0.92)
        )

    def find_army_confirmation(self, scene: np.ndarray) -> vision.Match | None:
        return self._find_control(
            scene, self.army_confirmation, "army_confirmation", (0.25, 0.0, 0.75, 0.22)
        )

    def find_confirm_match(self, scene: np.ndarray) -> vision.Match | None:
        return self._find_control(
            scene, self.confirm_match, "confirm_find_match", (0.68, 0.72, 1.0, 1.0)
        )

    def find_opponent_scout(self, scene: np.ndarray) -> vision.Match | None:
        return self._find_control(
            scene, self.opponent_scout, "opponent_scout", (0.0, 0.60, 0.25, 0.90)
        )

    def is_home(self, scene: np.ndarray) -> bool:
        return self.find_button(scene) is not None and self.find_menu(scene) is None


class AttackNavigator:
    def __init__(self, client: AdbClient, ui: AttackUi | None = None,
                 human: HumanInput | None = None):
        self.client = client
        self.ui = ui or AttackUi()
        self.human = human or HumanInput(client)

    def open(self) -> OpenAttackResult:
        before = vision.decode(self.client.screenshot())
        button = self.ui.find_button(before)
        if button is None:
            return OpenAttackResult(0.0, None, False)
        self.human.tap(*button.center, radius=max(7.0, min(button.w, button.h) * 0.20))
        after = vision.decode(self.client.screenshot())
        menu = self.ui.find_menu(after)
        if menu is None:
            self.human.wait(0.6, 0.9)
            after = vision.decode(self.client.screenshot())
            menu = self.ui.find_menu(after)
        return OpenAttackResult(
            button_score=button.score,
            menu_score=None if menu is None else menu.score,
            opened=menu is not None,
        )


class FindMatchNavigator:
    """Advance through the learned match-search states without deploying."""

    def __init__(self, client: AdbClient, ui: AttackUi | None = None,
                 human: HumanInput | None = None):
        self.client = client
        self.ui = ui or AttackUi()
        self.human = human or HumanInput(client)

    def _screen(self) -> np.ndarray:
        return vision.decode(self.client.screenshot())

    def find(self, *, confirm: bool = False, return_home: bool = True) -> FindMatchResult:
        scene = self._screen()
        if self.ui.find_menu(scene) is None:
            opened = AttackNavigator(self.client, self.ui, self.human).open()
            if not opened.opened:
                return FindMatchResult(False, False, False)
            scene = self._screen()

        find_button = self.ui.find_find_match(scene)
        if find_button is None:
            return FindMatchResult(False, False, False)
        self.human.tap(*find_button.center,
                       radius=max(8.0, min(find_button.w, find_button.h) * 0.20))
        army_scene = self._screen()
        army = self.ui.find_army_confirmation(army_scene)
        if army is None:
            self.human.wait(0.7, 1.0)
            army_scene = self._screen()
            army = self.ui.find_army_confirmation(army_scene)
        if army is None:
            return FindMatchResult(False, False, False)
        if not confirm:
            return FindMatchResult(True, False, False)

        confirm_button = self.ui.find_confirm_match(army_scene)
        if confirm_button is None:
            return FindMatchResult(True, False, False)
        self.human.tap(*confirm_button.center,
                       radius=max(8.0, min(confirm_button.w, confirm_button.h) * 0.18))
        scout_scene = self._screen()
        scout = self.ui.find_opponent_scout(scout_scene)
        if scout is None:
            self.human.wait(1.0, 1.5)
            scout_scene = self._screen()
            scout = self.ui.find_opponent_scout(scout_scene)
        if scout is None:
            return FindMatchResult(True, False, False)
        if not return_home:
            return FindMatchResult(True, True, False)

        # During scouting this exits immediately without deploying troops.
        self.human.tap(*scout.center, radius=max(7.0, min(scout.w, scout.h) * 0.18))
        self.human.wait(2.0, 3.0)
        home = self.ui.is_home(self._screen())
        return FindMatchResult(True, True, home)
