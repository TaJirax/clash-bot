import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "capture_coc_wiki.py"
SPEC = importlib.util.spec_from_file_location("capture_coc_wiki", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_safe_name_is_stable_and_path_safe():
    first = MODULE.safe_name("P.E.K.K.A/Home Village")
    second = MODULE.safe_name("P.E.K.K.A/Home Village")
    assert first == second
    assert "/" not in first and "\\" not in first
    assert first.endswith("_" + first.rsplit("_", 1)[1])


def test_json_save_is_atomic_and_roundtrips(tmp_path):
    path = tmp_path / "data.json"
    MODULE.save_json(path, {"unit": "Ruin Witch"})
    assert MODULE.load_json(path, {}) == {"unit": "Ruin Witch"}
    assert not path.with_suffix(".json.tmp").exists()
