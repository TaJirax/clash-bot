from pathlib import Path

from clashbot import adb_client


def test_adb_executable_honors_configured_path(tmp_path, monkeypatch):
    executable = tmp_path / "adb.exe"
    executable.write_bytes(b"")
    monkeypatch.setenv("CLASHBOT_ADB", str(executable))
    assert Path(adb_client.adb_executable()) == executable
