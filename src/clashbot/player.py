"""One orchestrator that plays the game: collect, manage, upgrade, attack.

Each cycle reuses the existing verified building blocks (Collector,
BaseManagementInspector, UpgradeBot, FindMatchNavigator, LootAttackExecutor).
Nothing here taps the screen without a visual verification path in the
underlying module, and every cycle is appended to a replayable JSONL log.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import vision
from .adb_client import AdbClient
from .attack import AttackUi, FindMatchNavigator
from .attack_execution import LootAttackExecutor
from .autonomy import find_connection_retry
from .base_management import BaseManagementInspector, plan_base_management
from .farming import Collector
from .layout import BaseLayout
from .resources import ResourceReader
from .upgrades import UpgradeBot

ATTACK_MODES = ("off", "policy", "always")

_LEVEL_PATTERN = re.compile(r"(?:lv|level)[_ ]?(\d+)", re.IGNORECASE)


def town_hall_status(targets) -> tuple[bool, int | None]:
    """Whether a town hall is visible and, if its template encodes one, its level."""
    for target in targets:
        if target.category == "town_hall":
            match = _LEVEL_PATTERN.search(target.name)
            return True, int(match.group(1)) if match else None
    return False, None


@dataclass(frozen=True)
class CycleReport:
    cycle: int
    home: bool
    collected: int
    plan_action: str
    plan_reason: str
    buildings_seen: int
    building_counts: dict[str, int]
    town_hall_seen: bool
    town_hall_level: int | None
    resources: dict[str, int | None]
    layout_total: int
    layout_stable: int
    upgrade_scans: int
    attack_attempted: bool
    troops_deployed: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class PlayReport:
    session: str
    dry_run: bool
    attack_mode: str
    cycles: tuple[CycleReport, ...]
    log_path: str


class GamePlayer:
    """Run the full base loop in ordered, individually verified phases.

    ``attack_mode`` controls the only irreversible phase:
      - ``off``: never search for an opponent.
      - ``policy``: attack only when :func:`plan_base_management` reports that
        all verified base work is clear (fail-closed on unknown state).
      - ``always``: attempt an attack every cycle; deployment itself still
        requires a verified battle HUD and legal deployment boundary.
    """

    def __init__(
        self,
        client: AdbClient,
        *,
        ui: AttackUi | None = None,
        collector: Collector | None = None,
        inspector: BaseManagementInspector | None = None,
        upgrade_bot: UpgradeBot | None = None,
        matcher: FindMatchNavigator | None = None,
        executor: LootAttackExecutor | None = None,
        resources: ResourceReader | None = None,
        capture: Callable[[], "vision.np.ndarray"] | None = None,
        root: str | Path = "captures/play",
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
    ):
        self.client = client
        self.ui = ui or AttackUi()
        self.collector = collector or Collector(client)
        self.inspector = inspector or BaseManagementInspector()
        self.upgrade_bot = upgrade_bot or UpgradeBot(client)
        self.matcher = matcher or FindMatchNavigator(client, self.ui)
        self.executor = executor or LootAttackExecutor(client, self.ui)
        if resources is None:
            try:
                resources = ResourceReader()
            except FileNotFoundError:
                resources = None
        self.resources = resources
        self.capture = capture or (lambda: vision.capture(client))
        self.root = Path(root)
        self.sleep = sleep
        self.log = log

    def run(
        self,
        *,
        session: str = "play",
        cycles: int = 1,
        interval: float = 60.0,
        dry_run: bool = False,
        attack_mode: str = "policy",
        upgrade: bool = True,
        battle_timeout: float = 180.0,
    ) -> PlayReport:
        if attack_mode not in ATTACK_MODES:
            raise ValueError(f"attack_mode must be one of {ATTACK_MODES}")
        if cycles < 1:
            raise ValueError("cycles must be at least 1")
        serial = getattr(self.client, "serial", "device")
        self.log(f"connecting to the game on {serial} "
                 f"(session={session}, dry_run={dry_run}, attack={attack_mode})")
        directory = self.root / session
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / "play_log.jsonl"
        layout = BaseLayout(directory / "layout.json")
        reports: list[CycleReport] = []
        for index in range(1, cycles + 1):
            report = self._cycle(
                index,
                directory,
                layout,
                dry_run=dry_run,
                attack_mode=attack_mode,
                upgrade=upgrade,
                battle_timeout=battle_timeout,
            )
            reports.append(report)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(
                    {"at": datetime.now(timezone.utc).isoformat(), **asdict(report)}
                ) + "\n")
            self.log(
                f"cycle {index}/{cycles}: home={report.home} "
                f"collected={report.collected} plan={report.plan_action} "
                f"attacked={report.attack_attempted}"
            )
            if index < cycles:
                self.sleep(interval)
        return PlayReport(session, dry_run, attack_mode, tuple(reports), str(log_path))

    def _cycle(
        self,
        index: int,
        directory: Path,
        layout: BaseLayout,
        *,
        dry_run: bool,
        attack_mode: str,
        upgrade: bool,
        battle_timeout: float,
    ) -> CycleReport:
        notes: list[str] = []
        scene = self._recover(self.capture(), notes, dry_run)
        home = self.ui.is_home(scene)
        self.log("connected to the game: home village verified" if home
                 else "connected, but the home village is not verified yet")
        collected = 0
        if home:
            collected = self.collector.sweep(dry_run=dry_run).count
            if collected and not dry_run:
                scene = self.capture()
        else:
            notes.append("home village was not verified; only recovery ran this cycle")
        status = self.inspector.inspect(scene)
        plan = plan_base_management(status)
        building_counts: dict[str, int] = {}
        for target in status.targets:
            building_counts[target.category] = building_counts.get(target.category, 0) + 1
        building_counts = dict(sorted(building_counts.items()))
        if building_counts:
            self.log("buildings: " + ", ".join(
                f"{name} x{count}" for name, count in building_counts.items()
            ))
        else:
            self.log("buildings: none recognized this cycle")
        town_hall_seen, town_hall_level = town_hall_status(status.targets)
        if town_hall_seen:
            self.log("town hall: " + (f"level {town_hall_level}"
                                      if town_hall_level else "seen (level unknown)"))
        else:
            self.log("town hall: not visible this cycle")
        resource_values: dict[str, int | None] = {"gold": None, "elixir": None, "gems": None}
        if home and self.resources is not None:
            reading = self.resources.read(scene)
            resource_values = {"gold": reading.gold, "elixir": reading.elixir,
                               "gems": reading.gems}
            self.log("resources: " + ", ".join(
                f"{name}={value:,}" if value is not None else f"{name}=unreadable"
                for name, value in resource_values.items()
            ))
        layout_change = None
        if home and status.targets:
            layout_change = layout.update(status.targets)
            notes.append(
                f"layout: {layout_change.total} known buildings "
                f"({layout_change.stable_total} stable, {layout_change.new} new this cycle)"
            )
        if plan.action == "recover" and not dry_run:
            self.client.back()
            notes.append("pressed back to dismiss the blocking dialog")
        upgrade_scans = 0
        if home and upgrade and plan.action in ("upgrade", "inspect-upgrades"):
            # "inspect-upgrades" means the cost is unverified, so it stays a
            # dry scan even in a live session.
            upgrade_scans = self.upgrade_bot.run(
                scans=1,
                scan_interval=1.0,
                dry_run=dry_run or plan.action == "inspect-upgrades",
                log=self.log,
            )
        attack_attempted = False
        deployed: tuple[str, ...] = ()
        wants_attack = attack_mode == "always" or (
            attack_mode == "policy" and plan.action == "attack"
        )
        if wants_attack and home:
            if dry_run:
                notes.append("dry-run: attack requested but skipped")
            else:
                attack_attempted, deployed = self._attack(directory, index, notes)
                if attack_attempted:
                    self._await_home(battle_timeout, notes)
        return CycleReport(
            cycle=index,
            home=home,
            collected=collected,
            plan_action=plan.action,
            plan_reason=plan.reason,
            buildings_seen=len(status.targets),
            building_counts=building_counts,
            town_hall_seen=town_hall_seen,
            town_hall_level=town_hall_level,
            resources=resource_values,
            layout_total=layout_change.total if layout_change else len(layout.buildings),
            layout_stable=(layout_change.stable_total if layout_change
                           else sum(1 for record in layout.buildings if record.stable)),
            upgrade_scans=upgrade_scans,
            attack_attempted=attack_attempted,
            troops_deployed=deployed,
            notes=tuple(notes),
        )

    def _recover(self, scene, notes: list[str], dry_run: bool):
        """Clear the verified connection-lost modal before any phase runs."""
        for _attempt in range(2):
            retry = find_connection_retry(scene)
            if retry is None:
                return scene
            if dry_run:
                self.log("connection-lost dialog is open; dry-run leaves it alone")
                notes.append("dry-run: connection retry dialog seen; not tapped")
                return scene
            self.log("connection-lost dialog detected; tapping TRY AGAIN")
            self.client.tap(*retry)
            notes.append("tapped connection retry")
            self.sleep(2.0)
            scene = self.capture()
        return scene

    def _attack(self, directory: Path, index: int,
                notes: list[str]) -> tuple[bool, tuple[str, ...]]:
        match = self.matcher.find(confirm=True, return_home=False)
        if not match.opponent_found:
            notes.append("matchmaking was not verified; no attack this cycle")
            if match.prepared:
                # Stopped on My Army or an unverified scouting screen; back out
                # instead of leaving a half-open menu for the next cycle.
                self.client.back()
            return False, ()
        try:
            result = self.executor.run(
                session=f"cycle_{index:03d}", root=directory / "attacks"
            )
        except RuntimeError as error:
            notes.append(f"attack aborted safely: {error}")
            return True, ()
        notes.append(f"deployed {len(result.deployed)} troops; evidence at {result.log_path}")
        return True, tuple(result.deployed)

    def _await_home(self, timeout: float, notes: list[str]) -> bool:
        attempts = max(1, int(timeout / 5.0))
        for attempt in range(attempts):
            self.sleep(5.0)
            scene = self._recover(self.capture(), notes, False)
            if self.ui.is_home(scene):
                notes.append("returned home after battle")
                return True
            if attempt == attempts // 2:
                # By mid-timeout the battle has ended for a small loot wave;
                # BACK activates Return Home on the end screen.
                self.client.back()
                notes.append("pressed back to leave the battle end screen")
        notes.append("home was not verified after battle; next cycle will recover")
        return False
