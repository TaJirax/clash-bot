"""Thin wrapper around the `adb` command line tool.

Works against any Android emulator that exposes an ADB endpoint
(BlueStacks, MEmu, Nox, ...) since they all speak the same protocol.
"""

from __future__ import annotations

import subprocess
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class AdbError(RuntimeError):
    pass


@dataclass
class Device:
    serial: str
    state: str


def adb_executable() -> str:
    """Find ADB on PATH or in common Windows emulator installations."""
    configured = os.environ.get("CLASHBOT_ADB")
    if configured:
        if not Path(configured).is_file():
            raise AdbError(f"CLASHBOT_ADB does not point to a file: {configured}")
        return configured
    on_path = shutil.which("adb")
    if on_path:
        return on_path
    if os.name == "nt":
        candidates = (
            r"C:\Program Files\Microvirt\MEmu\adb.exe",
            r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
            r"C:\Program Files\Nox\bin\nox_adb.exe",
            r"C:\LDPlayer\LDPlayer9\adb.exe",
            r"C:\Program Files\ldplayerbox\adb.exe",
        )
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
    raise AdbError(
        "adb was not found; add it to PATH or set CLASHBOT_ADB to its executable"
    )


def _run(args: list[str], input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [adb_executable(), *args],
        input=input_bytes,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AdbError(result.stderr.decode(errors="replace").strip())
    return result


def connect(address: str) -> bool:
    """Connect to an emulator listening at host:port, e.g. '127.0.0.1:5555'."""
    result = _run(["connect", address])
    output = result.stdout.decode(errors="replace")
    return "connected" in output or "already connected" in output


def list_devices() -> list[Device]:
    result = _run(["devices"])
    lines = result.stdout.decode(errors="replace").splitlines()[1:]
    devices = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        serial, _, state = line.partition("\t")
        devices.append(Device(serial=serial, state=state))
    return devices


class AdbClient:
    """Controls a single connected device by serial."""

    def __init__(self, serial: str):
        self.serial = serial

    def _run(self, args: list[str], input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
        return _run(["-s", self.serial, *args], input_bytes=input_bytes)

    def screenshot(self) -> bytes:
        """Returns raw PNG bytes of the current device screen."""
        result = self._run(["exec-out", "screencap", "-p"])
        return result.stdout

    def shell_text(self, *args: str) -> str:
        """Run a shell command and return decoded stdout."""
        result = self._run(["shell", *args])
        return result.stdout.decode(errors="replace")

    def tap(self, x: int, y: int) -> None:
        self._run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._run(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])

    def keyevent(self, keycode: int | str) -> None:
        """Send an Android key event, e.g. 4 / 'KEYCODE_BACK' to close a menu."""
        self._run(["shell", "input", "keyevent", str(keycode)])

    def back(self) -> None:
        """Press BACK — dismisses the building info panel / any open menu."""
        self.keyevent(4)
