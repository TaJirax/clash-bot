import json

from clashbot.fankit import FanKitIndex, normalize_category


def test_fankit_manifest_indexes_home_village_building_levels(tmp_path):
    root = tmp_path / "fankit"
    relative = "Asset Types/Buildings/Cannon/Level 3/Building_HV_Cannon_level_3.png"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    (root / "manifest.json").write_text(json.dumps({
        "assets": {
            "7": {"file": relative, "is_image": True, "title": "Cannon 3"},
            "8": {
                "file": "Asset Types/Buildings/Cannon/Level 3/Building_BB_Cannon_level_3.png",
                "is_image": True,
                "title": "Builder cannon",
            },
        }
    }), encoding="utf-8")

    index = FanKitIndex(root)

    assert index.asset_count == 1
    assert index.levels_for("cannon") == (3,)
    assert normalize_category("Elixir Collector") == "elixir_collector"

