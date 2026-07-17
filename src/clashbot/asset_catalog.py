"""Lazy catalog for local reference art and decoded game resources.

The catalog stores paths and provenance only.  It deliberately distinguishes
labelled reference images from atlases and 3D models: an atlas or model can be
used to build training data, but it is not itself a live-game detection.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .fankit import FanKitIndex, normalize_category
from .paths import DERIVED_CACHE_DIR, FANKIT_DIR, REPOSITORY_ROOT


_NON_WORD = re.compile(r"[^a-z0-9]+")
_LEVEL = re.compile(r"(?:level|lvl)[ _.-]?(\d+)", re.IGNORECASE)


def normalize_label(value: str) -> str:
    return _NON_WORD.sub("_", value.lower()).strip("_")


def _level(value: str) -> int | None:
    match = _LEVEL.search(value)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class AssetRecord:
    source: str
    role: str
    label: str
    category: str
    path: Path
    level: int | None = None
    sha256: str | None = None
    detector_ready: bool = False
    aliases: tuple[str, ...] = ()


class AssetCatalog:
    """Query manifests without opening or decoding the underlying assets."""

    def __init__(
        self,
        derived_root: str | Path = DERIVED_CACHE_DIR,
        fankit_root: str | Path | None = FANKIT_DIR,
        repository_root: str | Path = REPOSITORY_ROOT,
    ):
        self.derived_root = Path(derived_root)
        self.repository_root = Path(repository_root)
        self._records: list[AssetRecord] = []
        self._retrieval_model = None
        self._load_visual()
        self._load_sctx()
        self._load_models()
        self._load_sc2fla()
        self._load_candidates()
        if fankit_root is not None:
            self._load_fankit(Path(fankit_root))
        self._by_label: dict[str, list[AssetRecord]] = {}
        for record in self._records:
            keys = {
                normalize_label(record.label),
                normalize_label(record.category),
                *(normalize_label(alias) for alias in record.aliases),
            }
            for key in keys:
                self._by_label.setdefault(key, []).append(record)
        # Keep the hot lookup path deterministic and level-aware.  Labelled
        # references and rendered composites are preferred over raw package
        # resources, then lower levels are adjacent for cache-friendly scans.
        role_order = {
            "labelled_reference": 0,
            "synthetic_candidate": 1,
            "vector_composition": 2,
            "texture_atlas": 3,
            "model": 4,
            "resource_sprite": 5,
        }
        for key, records in self._by_label.items():
            self._by_label[key] = sorted(
                records,
                key=lambda item: (
                    role_order.get(item.role, 99),
                    item.level is None,
                    item.level if item.level is not None else 0,
                    str(item.path),
                ),
            )

    @staticmethod
    def _manifest(path: Path) -> dict | None:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_visual(self) -> None:
        root = self.derived_root / "visual"
        manifest = self._manifest(root / "manifest.json")
        if not manifest:
            return
        for item in manifest.get("records", []):
            output = item.get("output")
            if not output:
                continue
            self._records.append(AssetRecord(
                source=str(item.get("source_id", "visual")),
                role="labelled_reference",
                label=str(item.get("label") or Path(output).stem),
                category=normalize_category(str(item.get("category", "uncategorized"))),
                level=item.get("level"),
                path=root / output,
                sha256=item.get("output_sha256"),
            ))

    def _load_sctx(self) -> None:
        root = self.derived_root / "sctx_png"
        manifest = self._manifest(root / "manifest.json")
        if not manifest:
            return
        for item in manifest.get("records", []):
            output = item.get("output")
            if not output:
                continue
            relative = Path(output)
            parent = relative.parent.name or "texture"
            self._records.append(AssetRecord(
                source="game_package_sctx",
                role="texture_atlas",
                label=relative.stem,
                category=normalize_category(parent),
                level=_level(relative.as_posix()),
                path=root / relative,
                sha256=item.get("output_sha256"),
            ))

    def _load_models(self) -> None:
        root = self.derived_root / "flat_gltf"
        manifest = self._manifest(root / "manifest.json")
        if not manifest:
            return
        for item in manifest.get("records", []):
            output = item.get("output")
            if not output:
                continue
            relative = Path(output)
            self._records.append(AssetRecord(
                source="game_package_sc3d",
                role="model",
                label=relative.stem,
                category="sc3d",
                level=_level(relative.as_posix()),
                path=root / relative,
                sha256=item.get("output_sha256"),
            ))

    def _load_sc2fla(self) -> None:
        manifest = self._manifest(self.derived_root / "sc2fla_index" / "manifest.json")
        if not manifest:
            return
        semantic = self._manifest(self.derived_root / "sorted_sc" / "semantic_index.json")
        if semantic:
            for item in semantic.get("records", []):
                output = item.get("output")
                if not output:
                    continue
                path = Path(output)
                if not path.is_absolute():
                    path = self.repository_root / path
                self._records.append(AssetRecord(
                    source="game_package_sc",
                    role="vector_composition",
                    label=str(item.get("name") or item.get("label") or path.stem),
                    category=normalize_category(str(item.get("category", "other"))),
                    level=item.get("level"),
                    path=path,
                    sha256=item.get("sha256"),
                    aliases=tuple(str(value) for value in (
                        item.get("family"), item.get("project"),
                    ) if value),
                ))
        for item in manifest.get("records", []):
            if semantic and item.get("role") == "vector_composition":
                continue
            output = item.get("output")
            if not output:
                continue
            path = Path(output)
            if not path.is_absolute():
                path = self.repository_root / path
            self._records.append(AssetRecord(
                source="game_package_sc",
                role=str(item.get("role", "resource_sprite")),
                label=str(item.get("label") or path.stem),
                category=normalize_category(str(item.get("project", "sc"))),
                level=item.get("level"),
                path=path,
                sha256=item.get("sha256"),
            ))

    def _load_fankit(self, root: Path) -> None:
        if not (root / "manifest.json").is_file():
            return
        index = FanKitIndex(root)
        for category in index.categories:
            for item in index.assets_for(category):
                self._records.append(AssetRecord(
                    source="supercell_fankit",
                    role="labelled_reference",
                    label=item.title,
                    category=item.category,
                    level=item.level,
                    path=item.path,
                ))

    def _load_candidates(self) -> None:
        root = self.derived_root / "detector_candidates"
        manifest = self._manifest(root / "manifest.json")
        if not manifest:
            return
        for item in manifest.get("records", []):
            output = item.get("output")
            if not output:
                continue
            self._records.append(AssetRecord(
                source="built_sc_composite",
                role="synthetic_candidate",
                label=str(item.get("name") or item.get("family") or Path(output).stem),
                category=normalize_category(str(item.get("category", "other"))),
                level=item.get("level"),
                path=root / output,
                sha256=item.get("output_sha256"),
                aliases=(str(item.get("family", "")),),
            ))

    @property
    def records(self) -> tuple[AssetRecord, ...]:
        return tuple(self._records)

    def find(self, label: str, *, roles: Iterable[str] | None = None) -> tuple[AssetRecord, ...]:
        allowed = set(roles) if roles is not None else None
        records = self._by_label.get(normalize_label(label), ())
        return tuple(record for record in records if allowed is None or record.role in allowed)

    def levels_for(self, label: str, *, roles: Iterable[str] | None = None) -> tuple[int, ...]:
        """Return available levels in recognition order without opening files."""
        return tuple(sorted({
            record.level for record in self.find(label, roles=roles)
            if record.level is not None
        }))

    def retrieve(self, image, *, k: int = 5):
        """Return nearest trained asset references for an image crop.

        The model is loaded lazily so ordinary manifest queries stay cheap.
        Missing models are represented by an empty tuple rather than causing
        live scanning to fail.
        """
        if self._retrieval_model is None:
            model_path = self.derived_root / "model" / "asset_retrieval.npz"
            if not model_path.is_file():
                return ()
            from .asset_model import AssetRetrievalModel
            self._retrieval_model = AssetRetrievalModel.load(model_path)
        return self._retrieval_model.predict(image, k=k)

    def summary(self) -> dict[str, object]:
        roles = Counter(record.role for record in self._records)
        sources = Counter(record.source for record in self._records)
        return {
            "assets": len(self._records),
            "roles": dict(sorted(roles.items())),
            "sources": dict(sorted(sources.items())),
            "labelled_reference_labels": len({
                normalize_label(record.label)
                for record in self._records
                if record.role == "labelled_reference"
            }),
            "detector_ready": sum(record.detector_ready for record in self._records),
        }
