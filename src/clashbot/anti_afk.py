"""Conservative anti-AFK activity for the home village."""

from __future__ import annotations

import random
import time
from typing import Callable

from . import vision
from .adb_client import AdbClient
from .attack import AttackUi
from .human import HumanInput
from .upgrades import SafeIdleTouch


class AntiAfk:
    def __init__(self, client: AdbClient, *, human: HumanInput | None = None,
                 ui: AttackUi | None = None, rng: random.Random | None = None):
        self.client = client
        self.rng = rng or random.Random()
        self.human = human or HumanInput(client, rng=self.rng)
        self.ui = ui or AttackUi()
        self.safe_touch = SafeIdleTouch(self.rng)

    def tick(self, *, dry_run: bool = False, log: Callable[[str], None] = print) -> bool:
        scene = vision.decode(self.client.screenshot())
        if not self.ui.is_home(scene):
            log("anti-afk: home village not verified; skipped")
            return False
        point = self.safe_touch.point(scene)
        if point is None:
            log("anti-afk: no uniform grass patch found; skipped")
            return False
        if dry_run:
            log(f"anti-afk: safe grass near ({point[0]}, {point[1]}); dry run")
            return True
        self.human.tap(*point, radius=5.0, settle=False)
        log(f"anti-afk: touched safe grass near ({point[0]}, {point[1]})")
        return True

    def run(self, *, loops: int = 0, interval: tuple[float, float] = (35.0, 65.0),
            dry_run: bool = False, log: Callable[[str], None] = print,
            sleep: Callable[[float], None] = time.sleep) -> int:
        low, high = interval
        if loops < 0:
            raise ValueError("loops cannot be negative")
        if low <= 0 or high < low:
            raise ValueError("interval must satisfy 0 < min <= max")
        completed = 0
        while loops == 0 or completed < loops:
            self.tick(dry_run=dry_run, log=log)
            completed += 1
            if loops and completed >= loops:
                break
            sleep(self.rng.uniform(low, high))
        return completed
