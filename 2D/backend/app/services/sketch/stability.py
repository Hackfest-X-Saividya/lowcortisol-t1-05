"""Stability metrics between a parent and child version (no AI).

- ``locked_drift_px``: mean movement of locked-region landmarks at 1024 px.
- ``ssim_outside_mask``: SSIM between parent and child outside the edit mask.
- ``geometry_similarity``: similarity of normalized distances between ~30 key landmarks.
  This is a cheap face-shape signature, not an identity model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from app.services.sketch.regions import face_width, feature_regions

KEY_LANDMARKS = [
    10,
    152,
    172,
    397,
    234,
    454,
    33,
    133,
    362,
    263,
    1,
    6,
    98,
    327,
    61,
    291,
    0,
    17,
    105,
    334,
    159,
    145,
    386,
    374,
    4,
    2,
    13,
    14,
    93,
    323,
]


@dataclass
class Stability:
    locked_drift_px: float
    ssim_outside_mask: float
    geometry_similarity: float
    warning: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "locked_drift_px": round(self.locked_drift_px, 3),
            "ssim_outside_mask": round(self.ssim_outside_mask, 4),
            "geometry_similarity": round(self.geometry_similarity, 4),
            "warning": self.warning,
            "reasons": list(self.reasons),
        }


def locked_drift(
    parent_lm: np.ndarray, child_lm: np.ndarray, locked: set[str], size_px: int = 1024
) -> float:
    regions = feature_regions()
    idxs = sorted({i for f in locked for i in regions.get(f, [])})
    if not idxs:
        return 0.0
    d = np.linalg.norm((child_lm[idxs] - parent_lm[idxs]) * size_px, axis=1)
    return float(d.mean())


def ssim_outside(parent: np.ndarray, child: np.ndarray, mask: np.ndarray | None) -> float:
    g1 = cv2.cvtColor(parent, cv2.COLOR_BGR2GRAY) if parent.ndim == 3 else parent
    g2 = cv2.cvtColor(child, cv2.COLOR_BGR2GRAY) if child.ndim == 3 else child
    if g1.shape != g2.shape:
        g2 = cv2.resize(g2, (g1.shape[1], g1.shape[0]))
    score, smap = structural_similarity(g1, g2, data_range=255, full=True)
    if mask is None:
        return float(score)
    if mask.shape[:2] != g1.shape:
        mask = cv2.resize(mask, (g1.shape[1], g1.shape[0]), interpolation=cv2.INTER_LINEAR)
    outside = mask <= 0.0
    if outside.sum() == 0:
        return float(score)
    return float(smap[outside].mean())


def geometry_signature(lm: np.ndarray) -> np.ndarray:
    pts = lm[KEY_LANDMARKS]
    fw = max(face_width(lm), 1e-6)
    diff = pts[:, None, :] - pts[None, :, :]
    d = np.sqrt((diff**2).sum(axis=-1)) / fw
    iu = np.triu_indices(len(KEY_LANDMARKS), k=1)
    return d[iu]


def geometry_similarity(parent_lm: np.ndarray, child_lm: np.ndarray) -> float:
    a = geometry_signature(parent_lm)
    b = geometry_signature(child_lm)
    denom = max(float(np.abs(a).mean()), 1e-6)
    return float(np.clip(1.0 - float(np.abs(a - b).mean()) / denom, 0.0, 1.0))


def evaluate(
    parent_img: np.ndarray,
    child_img: np.ndarray,
    parent_lm: np.ndarray,
    child_lm: np.ndarray,
    mask: np.ndarray | None,
    locked: set[str],
    *,
    max_drift_px: float,
    min_ssim: float,
) -> Stability:
    drift = locked_drift(parent_lm, child_lm, locked)
    ssim = ssim_outside(parent_img, child_img, mask)
    geo = geometry_similarity(parent_lm, child_lm)
    reasons = []
    if drift > max_drift_px:
        reasons.append(f"locked landmarks moved {drift:.1f}px (> {max_drift_px}px)")
    if ssim < min_ssim:
        reasons.append(f"image changed outside the edit area (SSIM {ssim:.3f} < {min_ssim})")
    return Stability(drift, ssim, geo, bool(reasons), reasons)
