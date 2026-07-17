"""Lightweight retrieval model trained from the local asset candidates.

This intentionally uses only NumPy/OpenCV so the bot can run in the existing
environment. It is a family/identity retrieval index, not a claim of robust
object detection; live click decisions still require screen-state and spatial
verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


FEATURE_SIZE = 64


def feature(image: np.ndarray) -> np.ndarray:
    """Return a normalized grayscale-HOG plus color-histogram signature."""
    if image.ndim == 3 and image.shape[2] == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        base = np.full(image[:, :, :3].shape, 128, dtype=np.float32)
        image = (image[:, :, :3].astype(np.float32) * alpha + base * (1 - alpha)).astype(np.uint8)
    elif image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    resized = cv2.resize(image, (FEATURE_SIZE, FEATURE_SIZE), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude, angle = cv2.cartToPolar(gx, gy, angleInDegrees=False)
    cells = []
    for y in range(0, FEATURE_SIZE, 8):
        for x in range(0, FEATURE_SIZE, 8):
            hist, _ = np.histogram(
                angle[y:y + 8, x:x + 8], bins=9, range=(0, 2 * np.pi),
                weights=magnitude[y:y + 8, x:x + 8],
            )
            cells.append(hist)
    hog = np.concatenate(cells).astype(np.float32)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    color = np.concatenate([
        np.histogram(hsv[:, :, channel], bins=16, range=(0, 256), density=True)[0]
        for channel in range(3)
    ]).astype(np.float32)
    vector = np.concatenate([hog, color])
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-8 else vector


@dataclass(frozen=True)
class AssetPrediction:
    label: str
    similarity: float
    source: str


class AssetRetrievalModel:
    def __init__(self, matrix: np.ndarray, labels: tuple[str, ...], sources: tuple[str, ...]):
        if matrix.ndim != 2 or len(matrix) != len(labels) or len(labels) != len(sources):
            raise ValueError("model matrix and metadata lengths do not agree")
        self.matrix = np.asarray(matrix, dtype=np.float32)
        self.labels = labels
        self.sources = sources

    def predict(self, image: np.ndarray, *, k: int = 5) -> tuple[AssetPrediction, ...]:
        if k < 1:
            raise ValueError("k must be positive")
        query = feature(image)
        scores = self.matrix @ query
        indexes = np.argsort(scores)[::-1][:min(k, len(scores))]
        return tuple(AssetPrediction(
            label=self.labels[index], similarity=float(scores[index]), source=self.sources[index]
        ) for index in indexes)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, matrix=self.matrix,
                            labels=np.asarray(self.labels), sources=np.asarray(self.sources))

    @classmethod
    def load(cls, path: str | Path) -> "AssetRetrievalModel":
        with np.load(path, allow_pickle=False) as data:
            return cls(data["matrix"], tuple(data["labels"].tolist()), tuple(data["sources"].tolist()))
