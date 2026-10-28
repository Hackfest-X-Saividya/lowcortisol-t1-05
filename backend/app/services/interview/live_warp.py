"""Smooth, fold-free warps for spoken corrections on the live sketch.

Each correction ("jaw a bit wider", "eyes further apart") becomes one or two Gaussian pushes
(or a local scale) centred on MediaPipe landmarks, sized by the face width. The displacement
of each push is capped at 0.8 x its radius, which keeps the mapping one-to-one (a Gaussian
bump's steepest slope is about 0.6 x height / radius), so a correction can never tear or fold
the face, however large the accumulated amount.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

Field = Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]

# MediaPipe face mesh indices
CHEEK_A, CHEEK_B = 234, 454
JAW_A, JAW_B = 136, 365  # lower jaw line (below the mouth corners)
CHIN = 152
IRIS_A, IRIS_B = 468, 473
NOSE_TIP = 1
ALA_A, ALA_B = 64, 294
LIP_TOP, LIP_BOTTOM = 13, 14
BROW_A, BROW_B = 105, 334


def _push(c: np.ndarray, dx: float, dy: float, s: float) -> Field:
    m = float(np.hypot(dx, dy))
    lim = 0.8 * s
    if m > lim:
        dx, dy = dx * lim / m, dy * lim / m

    def f(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        g = np.exp(-((x - c[0]) ** 2 + (y - c[1]) ** 2) / (2 * s * s))
        return g * dx, g * dy

    return f


def _scale(c: np.ndarray, ax: float, ay: float, s: float) -> Field:
    ax = float(np.clip(ax, -0.4, 0.4))
    ay = float(np.clip(ay, -0.4, 0.4))

    def f(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        g = np.exp(-((x - c[0]) ** 2 + (y - c[1]) ** 2) / (2 * s * s))
        return ax * (x - c[0]) * g, ay * (y - c[1]) * g

    return f


def fields(p: np.ndarray, adjust: dict[str, float]) -> list[Field]:
    """Displacement fields (pixels) for the corrections, landmarks ``p`` in pixels."""
    fw = float(np.linalg.norm(p[CHEEK_A] - p[CHEEK_B]))
    mid = (p[CHEEK_A][0] + p[CHEEK_B][0]) / 2

    def out(i: int) -> float:  # outward direction for a left/right landmark
        return -1.0 if p[i][0] < mid else 1.0

    fs: list[Field] = []
    for name, a in adjust.items():
        if name == "jaw_width":
            for i in (JAW_A, JAW_B):
                fs.append(_push(p[i], out(i) * a * fw * 0.45, 0.0, 0.12 * fw))
        elif name == "face_width":
            # fuller (+) / thinner (-) face: push the cheeks and the jaw line outward / inward
            for i in (CHEEK_A, CHEEK_B):
                fs.append(_push(p[i], out(i) * a * fw * 0.35, 0.0, 0.20 * fw))
            for i in (JAW_A, JAW_B):
                fs.append(_push(p[i], out(i) * a * fw * 0.40, 0.0, 0.14 * fw))
        elif name == "face_length":
            fs.append(_push(p[CHIN], 0.0, a * fw * 0.4, 0.11 * fw))
        elif name == "eye_size":
            for i in (IRIS_A, IRIS_B):
                fs.append(_scale(p[i], a * 0.8, a * 0.8, 0.07 * fw))
        elif name == "eye_spacing":
            for i in (IRIS_A, IRIS_B):
                fs.append(_push(p[i], out(i) * a * fw * 0.4, 0.0, 0.085 * fw))
        elif name == "nose_length":
            fs.append(_push(p[NOSE_TIP], 0.0, a * fw * 0.5, 0.09 * fw))
        elif name == "nose_width":
            for i in (ALA_A, ALA_B):
                fs.append(_push(p[i], out(i) * a * fw * 0.35, 0.0, 0.065 * fw))
        elif name == "lip_fullness":
            c = (p[LIP_TOP] + p[LIP_BOTTOM]) / 2
            fs.append(_scale(c, a * 0.3, a * 1.6, 0.09 * fw))
        elif name == "brow_height":
            for i in (BROW_A, BROW_B):
                fs.append(_push(p[i], 0.0, -a * fw * 0.4, 0.09 * fw))
    return fs


def warp(
    img: np.ndarray, lm: np.ndarray, adjust: dict[str, float]
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the corrections. ``lm`` is normalized (0..1); returns (image, new landmarks)."""
    if not adjust or lm.shape[0] <= max(IRIS_B, ALA_B, JAW_B):
        return img, lm
    h, w = img.shape[:2]
    p = lm * [w, h]
    fs = fields(p, adjust)
    if not fs:
        return img, lm
    step = 4
    ys, xs = np.mgrid[0:h:step, 0:w:step].astype(np.float32)
    dx = np.zeros_like(xs)
    dy = np.zeros_like(ys)
    for f in fs:
        fx, fy = f(xs, ys)
        dx += fx
        dy += fy
    dx = cv2.resize(dx, (w, h), interpolation=cv2.INTER_LINEAR)
    dy = cv2.resize(dy, (w, h), interpolation=cv2.INTER_LINEAR)
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    # backward mapping: each output pixel samples where it came from
    out = cv2.remap(img, gx - dx, gy - dy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    px, py = p[:, 0].astype(np.float32), p[:, 1].astype(np.float32)
    mx = np.zeros_like(px)
    my = np.zeros_like(py)
    for f in fs:
        fx, fy = f(px, py)
        mx += fx
        my += fy
    new = np.stack([px + mx, py + my], axis=1) / [w, h]
    return out, new.astype(np.float64)
