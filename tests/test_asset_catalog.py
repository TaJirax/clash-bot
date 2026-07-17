import json

from clashbot.asset_catalog import AssetCatalog


def write_manifest(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_catalog_keeps_references_atlases_and_models_separate(tmp_path):
    derived = tmp_path / "derived"
    write_manifest(derived / "visual" / "manifest.json", {"records": [{
        "source_id": "statscell",
        "label": "Town Hall",
        "category": "townhalls",
        "level": 10,
        "output": "statscell/townhall.png",
        "output_sha256": "visual-hash",
    }]})
    write_manifest(derived / "sctx_png" / "manifest.json", {"records": [{
        "output": "apk/assets/sc/buildings_0.png",
        "output_sha256": "atlas-hash",
    }]})
    write_manifest(derived / "flat_gltf" / "manifest.json", {"records": [{
        "output": "apk/assets/sc3d/archer_default_geo.glb",
        "output_sha256": "model-hash",
    }]})

    catalog = AssetCatalog(derived, fankit_root=None, repository_root=tmp_path)

    assert catalog.summary()["roles"] == {
        "labelled_reference": 1,
        "model": 1,
        "texture_atlas": 1,
    }
    match = catalog.find("town hall")
    assert len(match) == 1
    assert match[0].level == 10
    assert not match[0].detector_ready


def test_catalog_loads_sc2fla_workspace_paths(tmp_path):
    derived = tmp_path / "derived"
    write_manifest(derived / "sc2fla_index" / "manifest.json", {"records": [{
        "project": "buildings",
        "role": "vector_composition",
        "label": "buildings/resource_42",
        "output": "assets/derived_cache/sc2fla_staging/buildings/42.png",
        "sha256": "sprite-hash",
    }]})

    catalog = AssetCatalog(derived, fankit_root=None, repository_root=tmp_path)

    record = catalog.records[0]
    assert record.role == "vector_composition"
    assert record.path == tmp_path / "assets/derived_cache/sc2fla_staging/buildings/42.png"


def test_catalog_can_find_reference_by_category(tmp_path):
    root = tmp_path / "fankit"
    relative = "Asset Types/Buildings/Cannon/Level 7/Building_HV_Cannon_level_7.png"
    asset = root / relative
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"png")
    write_manifest(root / "manifest.json", {"assets": {"9": {
        "file": relative,
        "is_image": True,
        "title": "Building HV Cannon level 7",
    }}})

    catalog = AssetCatalog(tmp_path / "derived", fankit_root=root, repository_root=tmp_path)

    matches = catalog.find("Cannon", roles={"labelled_reference"})
    assert len(matches) == 1
    assert matches[0].level == 7


def test_catalog_prefers_semantic_sc2fla_index_for_unit_lookup(tmp_path):
    derived = tmp_path / "derived"
    write_manifest(derived / "sc2fla_index" / "manifest.json", {"records": [{
        "project": "chr_archer",
        "role": "vector_composition",
        "label": "chr_archer_lvl12",
        "output": "assets/staging/archer.xml",
    }]})
    write_manifest(derived / "sorted_sc" / "semantic_index.json", {"records": [{
        "role": "vector_composition",
        "category": "units",
        "family": "archer",
        "name": "archer",
        "level": 12,
        "output": "assets/staging/archer.xml",
    }]})

    catalog = AssetCatalog(derived, fankit_root=None, repository_root=tmp_path)

    matches = catalog.find("archer", roles={"vector_composition"})
    assert len(matches) == 1
    assert matches[0].category == "units"
    assert matches[0].level == 12


def test_catalog_loads_built_composite_candidates(tmp_path):
    derived = tmp_path / "derived"
    write_manifest(derived / "detector_candidates" / "manifest.json", {"records": [{
        "category": "units", "family": "archer", "name": "archer_idle",
        "level": 5, "output": "composites/units/archer/level_5/a.png",
        "output_sha256": "candidate-hash",
    }]})

    catalog = AssetCatalog(derived, fankit_root=None, repository_root=tmp_path)

    record = catalog.find("archer", roles={"synthetic_candidate"})[0]
    assert record.level == 5
    assert record.source == "built_sc_composite"
