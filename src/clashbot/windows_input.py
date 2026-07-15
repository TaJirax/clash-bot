"""Small, dependency-free Windows input adapter for emulator camera zoom."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes


class WindowsInputError(RuntimeError):
    pass


class WindowsCtrlWheel:
    """Send Ctrl+wheel to the centre of a specifically named window."""

    VK_CONTROL = 0x11
    KEYEVENTF_KEYUP = 0x0002
    MOUSEEVENTF_WHEEL = 0x0800
    WHEEL_DELTA = 120

    def __init__(self, window_title: str = "MEmu", *, pause_seconds: float = 0.12):
        if os.name != "nt":
            raise WindowsInputError("Ctrl+wheel zoom is only available on Windows")
        if not window_title.strip():
            raise ValueError("window_title cannot be empty")
        self.window_title = window_title.strip()
        self.pause_seconds = pause_seconds
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

    def _find_window(self) -> int:
        matches: list[tuple[int, str]] = []
        needle = self.window_title.casefold()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _lparam):
            if not self.user32.IsWindowVisible(hwnd):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
            title = buffer.value
            if needle in title.casefold():
                matches.append((int(hwnd), title))
            return True

        callback = callback_type(visit)
        self.user32.EnumWindows(callback, 0)
        if not matches:
            raise WindowsInputError(
                f"no visible window title contains {self.window_title!r}"
            )
        if len(matches) > 1:
            titles = ", ".join(repr(title) for _hwnd, title in matches)
            raise WindowsInputError(
                f"window title is ambiguous ({titles}); use --window-title more precisely"
            )
        return matches[0][0]

    def zoom(self, direction: str) -> None:
        if direction not in ("in", "out"):
            raise ValueError("direction must be 'in' or 'out'")
        hwnd = self._find_window()

        rect = wintypes.RECT()
        if not self.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise WindowsInputError("could not read emulator client area")
        point = wintypes.POINT((rect.right - rect.left) // 2,
                               (rect.bottom - rect.top) // 2)
        if not self.user32.ClientToScreen(hwnd, ctypes.byref(point)):
            raise WindowsInputError("could not locate emulator client area")

        previous = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(previous))
        if not self.user32.SetForegroundWindow(hwnd):
            raise WindowsInputError("Windows refused to focus the emulator window")
        self.user32.SetCursorPos(point.x, point.y)
        self.user32.keybd_event(self.VK_CONTROL, 0, 0, 0)
        try:
            delta = self.WHEEL_DELTA if direction == "in" else -self.WHEEL_DELTA
            self.user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
            time.sleep(self.pause_seconds)
        finally:
            self.user32.keybd_event(self.VK_CONTROL, 0, self.KEYEVENTF_KEYUP, 0)
            self.user32.SetCursorPos(previous.x, previous.y)
