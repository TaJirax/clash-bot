"""Behavioural tests for the GamePlayer play-loop orchestrator."""

import json
from pathlib import Path

import numpy as np
import pytest

from clashbot.attack import FindMatchResult
from clashbot.attack_execution import DeploymentResult
from clashbot.base_management import BaseManagementStatus
from clashbot.farming import SweepResult
from clashbot.player import GamePlayer


SCENE = np.zeros((720, 1280, 3), dtype=np.uint8)


class FakeClient:
    def __init__(self):
        self.taps: list[tuple[int, int]] = []
        self.backs = 0

    def tap(self, x, y):
        self.taps.append((x, y))

    def back(self):
        self.backs += 1


class FakeUi:
    def __init__(self, home=True):
        self.home = home

    def is_home(self, scene):
        return self.home


class FakeCollector:
    def __init__(self, count=2):
        self.count = count
        self.dry_runs: list[bool] = []

    def sweep(self, dry_run=False):
        self.dry_runs.append(dry_run)
        return SweepResult(collected=[object()] * self.count)


class FakeInspector:
    def __init__(self, status):
        self.status = status

    def inspect(self, scene):
        return self.status


class FakeUpgradeBot:
    def __init__(self):
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return 1


class FakeMatcher:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def find(self, **kwargs):
        self.calls += 1
        return self.result


class FakeExecutor:
    def __init__(self, error=None):
        self.error = error
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return DeploymentResult(("giant", "goblin"), Path("attacks/events.jsonl"))


def status(**overrides) -> BaseManagementStatus:
    values = dict(
        recognized_buildings=8,
        menu_state=None,
        builders_available=None,
        research_available=None,
        upgrade_affordable=None,
        boost_auras=0,
        next_step="inspect",
        collection_pending=None,
        army_ready=None,
    )
    values.update(overrides)
    return BaseManagementStatus(**values)


CLEAR_STATUS = status(
    builders_available=0,
    research_available=False,
    upgrade_affordable=False,
    collection_pending=False,
    army_ready=True,
)


def make_player(tmp_path, *, home=True, base_status=None, matcher=None, executor=None):
    client = FakeClient()
    player = GamePlayer(
        client,
        ui=FakeUi(home=home),
        collector=FakeCollector(),
        inspector=FakeInspector(base_status or status()),
        upgrade_bot=FakeUpgradeBot(),
        matcher=matcher or FakeMatcher(FindMatchResult(True, True, False)),
        executor=executor or FakeExecutor(),
        capture=lambda: SCENE,
        root=tmp_path,
        sleep=lambda seconds: None,
        log=lambda message: None,
    )
    return player, client


def test_policy_attacks_only_when_base_work_is_clear(tmp_path):
    player, _client = make_player(tmp_path, base_status=CLEAR_STATUS)
    report = player.run(session="s", cycles=1, attack_mode="policy")
    cycle = report.cycles[0]
    assert cycle.plan_action == "attack"
    assert cycle.attack_attempted
    assert cycle.troops_deployed == ("giant", "goblin")
    assert player.matcher.calls == 1


def test_policy_skips_attack_on_unverified_state(tmp_path):
    player, _client = make_player(tmp_path, base_status=status())
    report = player.run(session="s", cycles=1, attack_mode="policy")
    assert report.cycles[0].plan_action == "inspect"
    assert not report.cycles[0].attack_attempted
    assert player.matcher.calls == 0


def test_attack_mode_off_never_matches(tmp_path):
    player, _client = make_player(tmp_path, base_status=CLEAR_STATUS)
    report = player.run(session="s", cycles=1, attack_mode="off")
    assert not report.cycles[0].attack_attempted
    assert player.matcher.calls == 0


def test_dry_run_never_taps_or_attacks(tmp_path):
    player, client = make_player(tmp_path, base_status=CLEAR_STATUS)
    report = player.run(session="s", cycles=1, dry_run=True, attack_mode="always")
    assert player.collector.dry_runs == [True]
    assert player.matcher.calls == 0
    assert client.taps == [] and client.backs == 0
    assert any("dry-run" in note for note in report.cycles[0].notes)


def test_free_builder_triggers_one_upgrade_scan(tmp_path):
    player, _client = make_player(
        tmp_path,
        base_status=status(builders_available=1, upgrade_affordable=True),
    )
    report = player.run(session="s", cycles=1, attack_mode="off")
    assert report.cycles[0].plan_action == "upgrade"
    assert report.cycles[0].upgrade_scans == 1
    assert player.upgrade_bot.calls[0]["scans"] == 1
    assert player.upgrade_bot.calls[0]["dry_run"] is False


def test_unverified_upgrade_cost_stays_dry(tmp_path):
    player, _client = make_player(
        tmp_path, base_status=status(builders_available=1)
    )
    report = player.run(session="s", cycles=1, attack_mode="off")
    assert report.cycles[0].plan_action == "inspect-upgrades"
    assert player.upgrade_bot.calls[0]["dry_run"] is True


def test_not_home_skips_every_action(tmp_path):
    player, _client = make_player(tmp_path, home=False, base_status=CLEAR_STATUS)
    report = player.run(session="s", cycles=1, attack_mode="always")
    cycle = report.cycles[0]
    assert not cycle.home
    assert cycle.collected == 0
    assert not cycle.attack_attempted
    assert player.collector.dry_runs == []
    assert player.matcher.calls == 0


def test_failed_matchmaking_backs_out(tmp_path):
    matcher = FakeMatcher(FindMatchResult(True, False, False))
    player, client = make_player(
        tmp_path, base_status=CLEAR_STATUS, matcher=matcher
    )
    report = player.run(session="s", cycles=1, attack_mode="policy")
    assert not report.cycles[0].attack_attempted
    assert player.executor.calls == []
    assert client.backs == 1


def test_aborted_deployment_is_reported_not_raised(tmp_path):
    executor = FakeExecutor(error=RuntimeError("no legal boundary"))
    player, _client = make_player(
        tmp_path, base_status=CLEAR_STATUS, executor=executor
    )
    report = player.run(session="s", cycles=1, attack_mode="policy")
    cycle = report.cycles[0]
    assert cycle.attack_attempted
    assert cycle.troops_deployed == ()
    assert any("aborted safely" in note for note in cycle.notes)


def test_every_cycle_is_appended_to_the_jsonl_log(tmp_path):
    player, _client = make_player(tmp_path)
    report = player.run(session="s", cycles=2, interval=0.0, attack_mode="off")
    lines = Path(report.log_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert [record["cycle"] for record in records] == [1, 2]
    assert all("at" in record and "plan_reason" in record for record in records)


def test_invalid_attack_mode_is_rejected(tmp_path):
    player, _client = make_player(tmp_path)
    with pytest.raises(ValueError):
        player.run(session="s", attack_mode="rush")
