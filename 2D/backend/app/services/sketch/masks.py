"""Edit masks: convex hull of region landmarks, dilated, minus locked regions, feathered.

Locked regions are subtracted *after* feathering so the mask is exactly zero inside them.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.services.sketch.regions import (
    CHEEK_LEFT,
    CHEEK_RIGHT,
    FOREHEAD,
    face_width,
    feature_regions,
)


def _hull_mask(lm_px: np.ndarray, idxs: list[int], size: tuple[int, int]) -> np.ndarray:
    h, w = size
    m = np.zeros((h, w), np.uint8)
    if len(idxs) >= 3:
        pts = np.round(lm_px[idxs]).astype(np.int32)
        hull = cv2.convexHull(pts)
        cv2.fillConvexPoly(m, hull, 255)
    return m


def _dilate(m: np.ndarray, radius_px: int) -> np.ndarray:
    if radius_px <= 0:
        return m
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius_px + 1, 2 * radius_px + 1))
    return cv2.dilate(m, k)


def region_binary(
    lm: np.ndarray, region: str, size: tuple[int, int], dilate_frac: float = 0.06
) -> np.ndarray:
    """Binary (0/255) dilated hull for a region; hair/skin/marks use synthetic areas."""
    h, w = size
    lm_px = lm * [w, h]
    fw = face_width(lm_px)
    regions = feature_regions()
    if region == "hair":
        m = np.zeros((h, w), np.uint8)
        top = int(max(0, lm_px[FOREHEAD][1] - 0.9 * fw))
        bottom = int(lm_px[FOREHEAD][1] + 0.12 * fw)
        left = int(max(0, lm_px[CHEEK_RIGHT][0] - 0.2 * fw))
        right = int(min(w - 1, lm_px[CHEEK_LEFT][0] + 0.2 * fw))
        cv2.ellipse(
            m,
            ((left + right) // 2, (top + bottom) // 2),
            ((right - left) // 2, (bottom - top) // 2),
            0,
            0,
            360,
            255,
            -1,
        )
        return m
    if region in ("skin", "marks"):
        face = _hull_mask(lm_px, regions["face_shape"], size)
        for sub in ("eyes", "brows", "nose", "mouth"):
            face = cv2.subtract(
                face, _dilate(_hull_mask(lm_px, regions[sub], size), int(0.03 * fw))
            )
        return face
    idxs = regions.get(region, [])
    return _dilate(_hull_mask(lm_px, idxs, size), int(dilate_frac * fw))


def region_mask(
    lm: np.ndarray,
    region: str,
    locked: set[str],
    size: tuple[int, int],
    feather_frac: float = 0.03,
) -> np.ndarray:
    """Float32 mask in [0, 1]; exactly 0 inside every locked region."""
    h, w = size
    fw = face_width(lm * [w, h])
    base = region_binary(lm, region, size).astype(np.float32) / 255.0
    sigma = max(1.0, feather_frac * fw)
    feathered = cv2.GaussianBlur(base, (0, 0), sigma)
    keep = np.ones((h, w), np.float32)
    for feat in locked:
        if feat == region:
            continue
        lk = region_binary(lm, feat, size, dilate_frac=0.04)
        keep[lk > 0] = 0.0
    out = np.clip(feathered * keep, 0.0, 1.0)
    return out.astype(np.float32)


def exclude_locked(
    mask: np.ndarray, lm: np.ndarray, locked: set[str], size: tuple[int, int]
) -> np.ndarray:
    """Force the mask to exactly zero inside every locked region."""
    out = mask.astype(np.float32).copy()
    for feat in locked:
        lk = region_binary(lm, feat, size, dilate_frac=0.04)
        out[lk > 0] = 0.0
    return out


def mask_to_png_bytes(mask: np.ndarray) -> bytes:
    m8 = np.clip(mask * 255.0, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", m8)
    return buf.tobytes() if ok else b""


def mask_bbox(mask: np.ndarray, pad_frac: float = 0.15) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of the mask's non-zero area with padding, clamped to the image."""
    h, w = mask.shape[:2]
    ys, xs = np.nonzero(mask > 0.01)
    if xs.size == 0:
        return 0, 0, w, h
    x0, x1 = int(np.min(xs)), int(np.max(xs)) + 1
    y0, y1 = int(np.min(ys)), int(np.max(ys)) + 1
    pw, ph = int((x1 - x0) * pad_frac), int((y1 - y0) * pad_frac)
    return max(0, x0 - pw), max(0, y0 - ph), min(w, x1 + pw), min(h, y1 + ph)
