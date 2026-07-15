"""Capture labeled game-menu states and the actions between them.

This module intentionally records demonstrations; it does not guess what a
button does from one screenshot.  Repeated captures build a small state graph
that can later drive conservative menu recognition and automation.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _safe_name(value: str, field: str) -> str:
    if not _SAFE_NAME.fullmatch(value):
        raise ValueError(
            f"{field} must be 1-64 letters, numbers, underscores, or hyphens"
        )
    return value


class MenuDataset:
    """Append-only labeled screenshots plus observed menu transitions."""

    def __init__(self, root: str | Path, session: str):
        self.root = Path(root)
        self.session = _safe_name(session, "session")
        self.directory = self.root / self.session
        self.screens = self.directory / "screens"
        self.manifest_path = self.directory / "manifest.json"

    def _load(self) -> dict:
        if not self.manifest_path.exists():
            return {
                "schema_version": 1,
                "session": self.session,
                "captures": [],
                "transitions": [],
            }
        with self.manifest_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("session") != self.session:
            raise ValueError("manifest session does not match its directory")
        return data

    def _save(self, data: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        temporary.replace(self.manifest_path)

    def capture(
        self,
        png_bytes: bytes,
        *,
        state: str,
        description: str = "",
        after: str | None = None,
        action: str | None = None,
    ) -> dict:
        """Store the current screen and optionally an observed transition.

        ``after`` names the previous state and requires an ``action``.  The
        screenshot is evidence of the resulting ``state``.
        """
        state = _safe_name(state, "state")
        if (after is None) != (action is None):
            raise ValueError("after and action must be supplied together")
        if after is not None:
            after = _safe_name(after, "after")
            if not action or not action.strip():
                raise ValueError("action cannot be empty")

        image = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("screenshot is not a valid PNG image")

        data = self._load()
        capture_id = len(data["captures"]) + 1
        filename = f"{capture_id:04d}_{state}.png"
        self.screens.mkdir(parents=True, exist_ok=True)
        path = self.screens / filename
        path.write_bytes(png_bytes)

        height, width = image.shape[:2]
        record = {
            "id": capture_id,
            "state": state,
            "file": f"screens/{filename}",
            "description": description.strip(),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(png_bytes).hexdigest(),
        }
        data["captures"].append(record)
        if after is not None:
            data["transitions"].append({
                "from_state": after,
                "action": action.strip(),
                "to_state": state,
                "evidence_capture_id": capture_id,
            })
        self._save(data)
        return record
