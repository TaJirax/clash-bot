import json

from scripts.await_sc2fla_sort import group_pending


def test_waiter_counts_only_requested_queued_group(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"records": [
        {"group": "units", "status": "queued"},
        {"group": "units", "status": "complete"},
        {"group": "heroes", "status": "queued"},
    ]}), encoding="utf-8")

    assert group_pending(manifest, "units") == 1
    assert group_pending(manifest, "heroes") == 1
    assert group_pending(manifest, "buildings") == 0
