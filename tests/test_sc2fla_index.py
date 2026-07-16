from scripts.index_sc2fla_dump import build_index


def test_sc2fla_index_keeps_components_separate_from_named_exports(tmp_path):
    library = tmp_path / "staging" / "buildings" / "buildings" / "LIBRARY"
    resource = library / "resources" / "42.png"
    export = library / "exports" / "cannon_lvl7.xml"
    resource.parent.mkdir(parents=True)
    export.parent.mkdir(parents=True)
    resource.write_bytes(b"png")
    export.write_bytes(b"xml")

    records = build_index(tmp_path / "staging", tmp_path)

    assert [(item["role"], item["label"], item["level"]) for item in records] == [
        ("resource_sprite", "buildings/resource_42", None),
        ("vector_composition", "cannon_lvl7", 7),
    ]
