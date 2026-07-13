"""Known default ADB ports for the emulators we need to support.

Each emulator exposes ADB on 127.0.0.1 at a fixed port for its first
instance. Multi-instance setups increment from there, which is why we
probe a small range instead of a single port.
"""

from __future__ import annotations

from . import adb_client

KNOWN_PORT_RANGES = {
    "bluestacks": range(5555, 5575, 2),
    "memu": range(21503, 21563, 10),
    "nox": range(62001, 62025, 4),
}


def discover() -> list[adb_client.Device]:
    """Try connecting to every known emulator port, then return whatever
    ADB currently reports as attached."""
    for ports in KNOWN_PORT_RANGES.values():
        for port in ports:
            try:
                adb_client.connect(f"127.0.0.1:{port}")
            except adb_client.AdbError:
                pass
    return [d for d in adb_client.list_devices() if d.state == "device"]
