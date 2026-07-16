from pathlib import Path

import pytest

from scripts.convert_supercell_flat import clear_files


def test_clear_files_only_removes_flat_staging_files(tmp_path: Path) -> None:
    (tmp_path / "input.glb").write_bytes(b"glb")
    clear_files(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_clear_files_refuses_unexpected_directory(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    with pytest.raises(RuntimeError, match="unexpected directory"):
        clear_files(tmp_path)
