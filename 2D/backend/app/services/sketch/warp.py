"""Shape edits without AI: Gaussian handle displacement + piecewise-affine warp.

The warp is computed as an inverse map over the Delaunay triangulation of the control
points (478 landmarks + 8 pinned border points) at ``WARP_INTERNAL_PX`` (default 512),
then the map is upscaled and applied to the full-resolution image with a single
``cv2.remap``. This keeps a 1024 px edit well under one second on a laptop CPU; triangles
whose vertices do not move map to the identity, so pixels inside locked regions are
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.services.sketch.regions import HANDLES, face_width, feature_regions


@dataclass
class Displacement:
    delta: np.ndarray  # (478, 2) normalized displacement
    moved: set[int] = field(default_factory=set)
    pinned: set[int] = field(default_factory=set)


def compute_displacement(
    lm: np.ndarray,
    moves: list[dict[str, float | str]],
    locked_features: set[str],
    symmetric: bool = False,
) -> Displacement:
    """Build a per-landmark displacement from handle moves.

    ``moves`` items: ``{"handle": name, "dx": fraction_of_face_width, "dy": ...}``.
    Each move displaces the handle's region landmarks with a Gaussian falloff from the
    anchor; locked regions are pinned (zero displacement).
    """
    fw = face_width(lm)
    regions = feature_regions()
    delta = np.zeros_like(lm)
    moved: set[int] = set()
    expanded = list(moves)
    if symmetric:
        for m in moves:
            h = HANDLES.get(str(m["handle"]))
            if h and h.mirror and not any(str(x["handle"]) == h.mirror for x in moves):
                expanded.append({"handle": h.mirror, "dx": -float(m["dx"]), "dy": float(m["dy"])})
    for m in expanded:
        h = HANDLES.get(str(m["handle"]))
        if h is None:
            continue
        d = np.array([float(m["dx"]) * fw, float(m["dy"]) * fw])
        if not np.any(d):
            continue
        idxs = sorted(set(regions.get(h.region, [])) | {h.anchor})
        anchor = lm[h.anchor]
        sigma = max(h.sigma * fw, 1e-6)
        for i in idxs:
            w = float(np.exp(-np.sum((lm[i] - anchor) ** 2) / (2 * sigma**2)))
            if w < 1e-3:
                continue
            delta[i] += w * d
            moved.add(i)
        moved.add(h.anchor)
    pinned: set[int] = set()
    for feat in locked_features:
        for i in regions.get(feat, []):
            pinned.add(i)
    for i in pinned:
        delta[i] = 0.0
    moved -= pinned
    return Displacement(delta=delta, moved=moved, pinned=pinned)


def border_points(w: int, h: int) -> np.ndarray:
    return np.array(
        [
            [0, 0],
            [w / 2, 0],
            [w - 1, 0],
            [w - 1, h / 2],
            [w - 1, h - 1],
            [w / 2, h - 1],
            [0, h - 1],
            [0, h / 2],
        ],
        dtype=np.float64,
    )


def _delaunay(points: np.ndarray, w: int, h: int) -> np.ndarray:
    """Triangle index triples for ``points`` (pixel coords inside [0,w)x[0,h))."""
    rect = (0, 0, int(w) + 2, int(h) + 2)
    subdiv = cv2.Subdiv2D(rect)
    pts = np.clip(points, 0, [w - 1e-3, h - 1e-3]).astype(np.float32)
    for p in pts:
        subdiv.insert((float(p[0]), float(p[1])))
    tris = subdiv.getTriangleList()
    # Map triangle vertex coordinates back to point indices (nearest).
    lookup: dict[tuple[int, int], int] = {}
    for i, p in enumerate(pts):
        lookup.setdefault((int(round(p[0] * 10)), int(round(p[1] * 10))), i)
    out = []
    for t in tris:
        idx = []
        ok = True
        for k in range(3):
            key = (int(round(t[2 * k] * 10)), int(round(t[2 * k + 1] * 10)))
            j = lookup.get(key)
            if j is None:
                d = np.sum((pts - np.array([t[2 * k], t[2 * k + 1]], np.float32)) ** 2, axis=1)
                j = int(np.argmin(d))
                if d[j] > 4.0:
                    ok = False
                    break
            idx.append(j)
        if ok and len(set(idx)) == 3:
            out.append(idx)
    return np.asarray(out, dtype=np.int32)


def piecewise_affine_maps(
    src: np.ndarray, dst: np.ndarray, w: int, h: int
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse maps (map_x, map_y) of shape (h, w): for each dst pixel, the src pixel."""
    map_x, map_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    tris = _delaunay(dst, w, h)
    for tri in tris:
        d = dst[tri]
        s = src[tri]
        if np.allclose(d, s, atol=1e-6):
            continue  # identity triangle: keep identity map
        x0, y0 = np.floor(d.min(axis=0)).astype(int)
        x1, y1 = np.ceil(d.max(axis=0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1 + 1, w), min(y1 + 1, h)
        if x1 <= x0 or y1 <= y0:
            continue
        A = cv2.getAffineTransform(d.astype(np.float32), s.astype(np.float32))
        mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillConvexPoly(mask, np.round(d - [x0, y0]).astype(np.int32), 1, lineType=cv2.LINE_8)
        ys, xs = np.nonzero(mask)
        if xs.size == 0:
            continue
        gx = xs + x0
        gy = ys + y0
        sx = A[0, 0] * gx + A[0, 1] * gy + A[0, 2]
        sy = A[1, 0] * gx + A[1, 1] * gy + A[1, 2]
        map_x[gy, gx] = sx
        map_y[gy, gx] = sy
    return map_x, map_y


def warp_image_ex(
    img: np.ndarray,
    lm: np.ndarray,
    delta: np.ndarray,
    internal_px: int = 512,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Warp ``img`` so that landmarks ``lm`` move to ``lm + delta`` (both normalized).

    Returns (warped image, new landmarks, moved mask). The moved mask is a float32 HxW
    map that is 1 where pixels were resampled from somewhere else and 0 where the
    mapping is the identity (feathered at its edge). Border points are pinned.
    """
    h, w = img.shape[:2]
    scale = min(1.0, internal_px / max(h, w))
    iw, ih = max(8, int(round(w * scale))), max(8, int(round(h * scale)))
    src = np.vstack([lm * [iw, ih], border_points(iw, ih)])
    dst = np.vstack([(lm + delta) * [iw, ih], border_points(iw, ih)])
    if not np.any(delta):
        return img.copy(), lm.copy(), np.zeros((h, w), np.float32)
    map_x, map_y = piecewise_affine_maps(src, dst, iw, ih)
    gx_s, gy_s = np.meshgrid(np.arange(iw, dtype=np.float32), np.arange(ih, dtype=np.float32))
    dx_s, dy_s = map_x - gx_s, map_y - gy_s
    if (iw, ih) != (w, h):
        # Upscale the *displacement* (zero where nothing moves) so unmoved pixels keep an
        # exact identity mapping after interpolation.
        dx = cv2.resize(dx_s, (w, h), interpolation=cv2.INTER_LINEAR) * (w / iw)
        dy = cv2.resize(dy_s, (w, h), interpolation=cv2.INTER_LINEAR) * (h / ih)
        gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        map_x = gx + dx
        map_y = gy + dy
    else:
        dx, dy = dx_s, dy_s
    warped = cv2.remap(
        img, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT
    )
    moved = ((np.abs(dx) + np.abs(dy)) > 1e-3).astype(np.uint8)
    radius = max(2, int(0.01 * max(h, w)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    moved = cv2.dilate(moved, kernel).astype(np.float32)
    moved = cv2.GaussianBlur(moved, (0, 0), max(1.0, radius / 2))
    return warped, lm + delta, np.clip(moved, 0.0, 1.0).astype(np.float32)


def warp_image(
    img: np.ndarray,
    lm: np.ndarray,
    delta: np.ndarray,
    internal_px: int = 512,
) -> tuple[np.ndarray, np.ndarray]:
    """``warp_image_ex`` without the moved mask."""
    warped, new_lm, _ = warp_image_ex(img, lm, delta, internal_px)
    return warped, new_lm
