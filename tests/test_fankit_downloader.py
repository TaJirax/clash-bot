from pathlib import Path

from scripts.download_supercell_fankit import (
    add_category_file,
    asset_path,
    building_group,
    ensure_png,
    extract_level,
    safe_name,
    search_url,
)


def test_safe_name_removes_windows_reserved_characters() -> None:
    assert safe_name('Town Hall/Builder: "Level 1"') == "Town Hall_Builder_ _Level 1"


def test_asset_path_is_category_scoped_and_collision_proof(tmp_path: Path) -> None:
    path = asset_path(tmp_path, "Seasonal/Temporary Units", {
        "id": 42,
        "title": "Ice Wizard",
    }, "Asset Types")
    assert path == tmp_path / "Asset Types" / "Seasonal_Temporary Units" / "Ice Wizard__42.png"


def test_character_and_building_paths_are_sorted_by_level(tmp_path: Path) -> None:
    balloon = asset_path(tmp_path, "Balloon", {
        "id": 1,
        "title": "Troop_HV_Balloon_lvl13",
    }, "Characters")
    tesla = asset_path(tmp_path, "Buildings", {
        "id": 2,
        "title": "Building_HV_Hidden_Tesla_level_15",
    }, "Asset Types")

    assert balloon.parent == tmp_path / "Characters" / "Balloon" / "Level 13"
    assert tesla.parent == tmp_path / "Asset Types" / "Buildings" / "Hidden Tesla" / "Level 15"
    assert extract_level("Troop_HV_Balloon_12") == 12
    assert building_group("Building_HV_Gold_Mine_level_16") == "Gold Mine"


def test_search_url_encodes_category_and_page() -> None:
    url = search_url("Clash-A-Rama!", page=3, page_size=25)
    assert "page=3" in url
    assert "limit=25" in url
    assert "asset-type97=Clash-A-Rama%21" in url

    character_url = search_url("Balloon", page=1, page_size=100,
                               facet_key="characters16")
    assert "characters16=Balloon" in character_url


def test_add_category_file_exposes_existing_bytes(tmp_path: Path) -> None:
    source = tmp_path / "Buildings" / "hut.png"
    destination = tmp_path / "Home Village" / "hut.png"
    source.parent.mkdir()
    source.write_bytes(b"png-data")

    add_category_file(source, destination)

    assert destination.read_bytes() == b"png-data"


def test_ensure_png_preserves_real_png() -> None:
    body = b"\x89PNG\r\n\x1a\nrest"
    assert ensure_png(body, "image/png") == (body, None)
