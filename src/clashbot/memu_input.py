"""MEmu's official multi-touch zoom command adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path


class MEmuInputError(RuntimeError):
    pass


def infer_instance(serial: str) -> int | None:
    """Infer MEmu index from its standard 21503, 21513, ... ADB ports."""
    try:
        port = int(serial.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None
    offset = port - 21503
    if offset < 0 or offset % 10:
        return None
    return offset // 10


class MEmuZoom:
    def __init__(
        self,
        instance: int,
        executable: str = r"C:\Program Files\Microvirt\MEmu\memuc.exe",
    ):
        if instance < 0:
            raise ValueError("MEmu instance must be non-negative")
        if not Path(executable).is_file():
            raise MEmuInputError(f"memuc executable was not found: {executable}")
        self.instance = instance
        self.executable = executable

    def zoom(self, direction: str) -> None:
        command = {"in": "zoomin", "out": "zoomout"}.get(direction)
        if command is None:
            raise ValueError("direction must be 'in' or 'out'")
        result = subprocess.run(
            [self.executable, command, "-i", str(self.instance)],
            capture_output=True,
            text=True,
        )
        combined = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0 or "ERROR" in combined.upper():
            detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
            raise MEmuInputError(f"MEmu {command} failed: {detail}")
