import json
from pathlib import Path

import pytest

from scripts.acquire_asset_sources import load_sources
from scripts.extract_game_package_assets import safe_member
from scripts.pull_memu_game_assets import safe_relative


def test_asset_source_config_only_accepts_safe_github_sources(tmp_path: Path) -> None:
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({
        "schema_version": 1,
        "sources": [{
            "id": "labelled_assets",
            "url": "https://github.com/example/assets.git",
        }],
    }), encoding="utf-8")

    assert load_sources(config)[0]["id"] == "labelled_assets"


def test_asset_source_config_rejects_path_escape_id(tmp_path: Path) -> None:
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({
        "schema_version": 1,
        "sources": [{
            "id": "../outside",
            "url": "https://github.com/example/assets.git",
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe source id"):
        load_sources(config)


def test_zip_and_android_paths_cannot_escape_cache() -> None:
    assert safe_member("assets/sc/ui_tex.sc") == Path("assets/sc/ui_tex.sc")
    assert safe_member("../secret") is None
    assert safe_member("/absolute/file.sc") is None
    assert safe_relative("/data/app/base.apk") == Path("data/app/base.apk")
    with pytest.raises(ValueError, match="unsafe remote path"):
        safe_relative("/sdcard/../data/file.sc")
