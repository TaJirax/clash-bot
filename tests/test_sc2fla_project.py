from scripts.extract_sc2fla_project import find_family, stage_family


def test_sc2fla_staging_uses_sanitized_texture_without_touching_source(tmp_path):
    input_root = tmp_path / "input"
    package = input_root / "apk" / "assets" / "sc"
    package.mkdir(parents=True)
    (package / "buildings.sc").write_bytes(b"original-sc")
    (package / "buildings_0.sctx").write_bytes(b"new-header")
    (package / "buildings_extra.sc").write_bytes(b"related")
    (package / "buildingstone.sc").write_bytes(b"not-related")
    (package / "other.sc").write_bytes(b"unrelated")
    sanitized_root = tmp_path / "sanitized"
    sanitized = sanitized_root / "apk" / "assets" / "sc" / "buildings_0.sctx"
    sanitized.parent.mkdir(parents=True)
    sanitized.write_bytes(b"compatible-header")

    source, related = find_family(input_root, "buildings")
    records = stage_family(input_root, "buildings", sanitized_root, tmp_path / "stage")

    assert source == package / "buildings.sc"
    assert {path.name for path in related} == {"buildings.sc", "buildings_0.sctx", "buildings_extra.sc"}
    assert (tmp_path / "stage" / "buildings_0.sctx").read_bytes() == b"compatible-header"
    assert (package / "buildings_0.sctx").read_bytes() == b"new-header"
    assert sum(record["sanitized_header"] for record in records) == 1


def test_sc2fla_family_does_not_capture_a_longer_name_prefix(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    (root / "chr_bat.sc").write_bytes(b"bat")
    (root / "chr_battle_blimp.sc").write_bytes(b"blimp")
    (root / "chr_bat_0.sctx").write_bytes(b"texture")

    _, related = find_family(root, "chr_bat")

    assert [path.name for path in related] == ["chr_bat.sc", "chr_bat_0.sctx"]
