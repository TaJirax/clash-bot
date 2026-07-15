"""Real two-pointer pinch/spread gestures through an Android input device."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import vision
from .adb_client import AdbClient


class MultiTouchError(RuntimeError):
    pass


def find_multitouch_device(getevent_output: str) -> str | None:
    blocks = re.split(r"(?=add device \d+: )", getevent_output)
    for block in blocks:
        match = re.search(r"(/dev/input/event\d+)", block)
        if match and "ABS_MT_SLOT" in block and "ABS_MT_POSITION_X" in block:
            return match.group(1)
    return None


@dataclass
class AdbPinchZoom:
    client: AdbClient
    frames: int = 7

    def _event_device(self) -> str:
        output = self.client.shell_text("getevent", "-pl")
        device = find_multitouch_device(output)
        if device is None:
            raise MultiTouchError("no Android multi-touch input device was found")
        return device

    @staticmethod
    def _send(device: str, event_type: int, code: int, value: int) -> str:
        return f"sendevent {device} {event_type} {code} {value}"

    def zoom(self, direction: str) -> None:
        if direction not in ("in", "out"):
            raise ValueError("direction must be 'in' or 'out'")
        scene = vision.decode(self.client.screenshot())
        height, width = scene.shape[:2]
        device = self._event_device()
        center_x, center_y = width // 2, height // 2
        # A narrow distance change behaves like one Ctrl+wheel notch. A large
        # pinch jumps directly between the game's camera limits and makes
        # stable mapping unnecessarily difficult.
        near = max(45, int(width * 0.14))
        far = max(near + 35, int(width * 0.17))
        start, end = (near, far) if direction == "in" else (far, near)

        commands: list[str] = []
        # Linux multi-touch protocol B: create two tracking slots.
        for slot, tracking_id, x in ((0, 700, center_x - start),
                                     (1, 701, center_x + start)):
            commands.extend((
                self._send(device, 3, 47, slot),       # ABS_MT_SLOT
                self._send(device, 3, 57, tracking_id),# ABS_MT_TRACKING_ID
                self._send(device, 3, 53, x),          # ABS_MT_POSITION_X
                self._send(device, 3, 54, center_y),   # ABS_MT_POSITION_Y
                self._send(device, 3, 48, 8),          # ABS_MT_TOUCH_MAJOR
                self._send(device, 3, 58, 10),         # ABS_MT_PRESSURE
            ))
        commands.append(self._send(device, 0, 0, 0))   # SYN_REPORT

        for frame in range(1, self.frames + 1):
            distance = round(start + (end - start) * frame / self.frames)
            for slot, x in ((0, center_x - distance), (1, center_x + distance)):
                commands.extend((
                    self._send(device, 3, 47, slot),
                    self._send(device, 3, 53, x),
                    self._send(device, 3, 54, center_y),
                ))
            commands.extend((self._send(device, 0, 0, 0), "sleep 0.04"))

        for slot in (0, 1):
            commands.extend((
                self._send(device, 3, 47, slot),
                self._send(device, 3, 57, -1),
            ))
        commands.append(self._send(device, 0, 0, 0))
        self.client.shell_text("; ".join(commands))
