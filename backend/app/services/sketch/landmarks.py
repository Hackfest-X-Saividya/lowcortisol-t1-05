"""Face landmarks: MediaPipe Face Landmarker (478 points, CPU) and the canonical template.

Landmarks are ``np.ndarray`` of shape (478, 2) in normalized image coordinates. In mock
mode the template landmarks are used directly (the mock face is drawn at the template
geometry) and MediaPipe is never loaded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

N_LANDMARKS = 478


@dataclass(frozen=True)
class Template:
    size: int
    landmarks: np.ndarray  # (478, 2) normalized
    right_eye_center: np.ndarray  # subject's right eye (image left)
    left_eye_center: np.ndarray
    mouth_center: np.ndarray

    @property
    def targets(self) -> np.ndarray:
        return np.stack([self.right_eye_center, self.left_eye_center, self.mouth_center])


@lru_cache(maxsize=4)
def load_template(path: str | None = None) -> Template:
    p = (
        Path(path)
        if path
        else Path(__file__).resolve().parents[3] / "assets" / "templates" / "canonical_face.json"
    )
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    lm = np.asarray(data["landmarks"], dtype=np.float64)[:, :2]
    if lm.shape != (N_LANDMARKS, 2):
        raise ValueError(f"template has {lm.shape[0]} landmarks, expected {N_LANDMARKS}")
    return Template(
        size=int(data.get("size", 1024)),
        landmarks=lm,
        right_eye_center=np.asarray(data["right_eye_center"], dtype=np.float64),
        left_eye_center=np.asarray(data["left_eye_center"], dtype=np.float64),
        mouth_center=np.asarray(data["mouth_center"], dtype=np.float64),
    )


RIGHT_EYE_IDS = (33, 133, 160, 159, 158, 144, 145, 153)
LEFT_EYE_IDS = (362, 263, 387, 386, 385, 373, 374, 380)
MOUTH_IDS = (61, 291, 13, 14)


def eye_mouth_points(lm: np.ndarray) -> np.ndarray:
    """(3, 2): right eye centre, left eye centre, mouth centre (normalized)."""
    return np.stack(
        [
            lm[list(RIGHT_EYE_IDS)].mean(axis=0),
            lm[list(LEFT_EYE_IDS)].mean(axis=0),
            lm[list(MOUTH_IDS)].mean(axis=0),
        ]
    )


def landmarks_to_json(lm: np.ndarray) -> list[list[float]]:
    return [[round(float(x), 6), round(float(y), 6)] for x, y in lm]


def landmarks_from_json(data: list[Any]) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] != N_LANDMARKS:
        raise ValueError("invalid landmark array")
    return arr[:, :2]


class Landmarker:
    """Lazy MediaPipe wrapper. ``detect`` returns a list of (478, 2) arrays, one per face."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_path = settings.assets_path / "models" / "face_landmarker.task"
        self._detector: Any = None
        self._error: str | None = None

    @property
    def available(self) -> bool:
        return self.model_path.exists() and self._error is None

    def status(self) -> str:
        if self.settings.mock_mode:
            return "template (mock mode)"
        if not self.model_path.exists():
            return "model missing - run scripts/download_assets.py (using template fallback)"
        if self._error:
            return f"error: {self._error}"
        return "ready" if self._detector is not None else "available (lazy)"

    def _ensure(self) -> Any:
        if self._detector is not None:
            return self._detector
        try:
            import mediapipe as mp
            from mediapipe.tasks.python.core import base_options as bo
            from mediapipe.tasks.python.vision import face_landmarker as fl

            opts = fl.FaceLandmarkerOptions(
                base_options=bo.BaseOptions(model_asset_path=str(self.model_path)),
                num_faces=3,
                running_mode=mp.tasks.vision.RunningMode.IMAGE,
            )
            self._detector = fl.FaceLandmarker.create_from_options(opts)
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"[:200]
            log.warning("MediaPipe landmarker unavailable: %s", type(exc).__name__)
            raise
        return self._detector

    def detect(self, img_bgr: np.ndarray) -> list[np.ndarray]:
        import cv2
        import mediapipe as mp

        det = self._ensure()
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        faces = []
        for face in res.face_landmarks:
            arr = np.asarray([[p.x, p.y] for p in face], dtype=np.float64)
            if arr.shape[0] == N_LANDMARKS:
                faces.append(arr)
        return faces
