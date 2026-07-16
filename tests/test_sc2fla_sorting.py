from scripts.batch_extract_sc2fla import group_for
from scripts.sort_sc2fla_assets import semantic_name, sort_records


def test_groups_source_families_for_resumable_extraction():
    assert group_for("chr_archer.sc") == "units"
    assert group_for("hero_aq_default.sc") == "heroes"
    assert group_for("buildings_cc.sc") == "buildings"
    assert group_for("info_archer.sc") == "unit_ui"


def test_sorter_preserves_named_level_and_unlabelled_components():
    groups, components = sort_records([
        {"project": "buildings", "role": "vector_composition", "label": "cannon_lvl7", "output": "x"},
        {"project": "chr_archer", "role": "vector_composition", "label": "chr_archer_lvl12", "output": "y"},
        {"project": "buildings", "role": "resource_sprite", "label": "buildings/resource_42", "output": "z"},
    ])

    assert groups["buildings"][0]["name"] == "cannon"
    assert groups["buildings"][0]["level"] == 7
    assert groups["units"][0]["name"] == "archer"
    assert groups["units"][0]["level"] == 12
    assert groups["units"][0]["family"] == "archer"
    assert components["buildings"][0]["label"] == "buildings/resource_42"


def test_semantic_name_removes_non_identity_export_suffixes():
    assert semantic_name("barracks_lvl10_upgrade", "buildings") == ("barracks", 10)
    assert semantic_name("archer10_attack1_1", "chr_archer") == ("archer_attack1_1", 10)
