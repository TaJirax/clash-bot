"""Tests for the persistent base-layout tracker."""

import json

from clashbot.layout import BaseLayout
from clashbot.upgrades import BuildingTarget


def target(category="cannon", x=400, y=300, score=0.9, scale=1.0, name=None):
    return BuildingTarget(
        category=category, name=name or f"{category}_lv1",
        x=x, y=y, score=score, camera_scale=scale, verified=True,
    )


def test_repeated_sightings_confirm_one_building():
    layout = BaseLayout()
    first = layout.update([target(x=400, y=300)])
    second = layout.update([target(x=408, y=294)])
    assert first.new == 1 and first.stable_total == 0
    assert second.confirmed == 1 and second.new == 0
    assert second.total == 1 and second.stable_total == 1


def test_same_category_far_apart_stays_two_buildings():
    layout = BaseLayout()
    update = layout.update([target(x=300, y=300), target(x=700, y=420)])
    assert update.new == 2 and update.total == 2
    assert layout.counts() == {"cannon": 2}


def test_zoom_difference_still_matches_the_same_building():
    layout = BaseLayout()
    layout.update([target(x=400, y=300, scale=1.0)])
    update = layout.update([target(x=480, y=360, scale=1.2)])
    assert update.confirmed == 1 and update.total == 1


def test_two_detections_in_one_frame_never_merge():
    layout = BaseLayout()
    layout.update([target(x=400, y=300)])
    update = layout.update([target(x=395, y=302), target(x=410, y=310)])
    # Both frame detections are near the record, but one physical building
    # cannot absorb two simultaneous detections.
    assert update.confirmed == 1 and update.new == 1
    assert update.total == 2


def test_best_scoring_level_name_wins():
    layout = BaseLayout()
    layout.update([target(score=0.82, name="cannon_lv1")])
    layout.update([target(score=0.95, name="cannon_lv2")])
    layout.update([target(score=0.70, name="cannon_lv1")])
    assert layout.buildings[0].name == "cannon_lv2"
    assert layout.buildings[0].score == 0.95


def test_layout_persists_and_reloads(tmp_path):
    path = tmp_path / "layout.json"
    layout = BaseLayout(path)
    layout.update([target(), target(category="gold_mine", x=800, y=500)])
    layout.update([target()])

    reloaded = BaseLayout(path)
    assert reloaded.counts() == {"cannon": 1, "gold_mine": 1}
    assert reloaded.counts(stable_only=True) == {"cannon": 1}
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["buildings"]) == 2
