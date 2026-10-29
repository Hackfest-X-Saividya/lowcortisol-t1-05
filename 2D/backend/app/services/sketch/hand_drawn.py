"""Hand-drawn forensic pencil rendering of a portrait (local, about half a second).

The generated face is a photo; this redraws it the way a sketch artist works, so the result
reads as pencil on paper and not as a filtered or black-and-white AI image:

- contours: thin graphite lines from an XDoG edge pass, broken where a pencil skips;
- tone: diagonal hatching strokes laid in layers (a tonal art map: darker areas add denser
  strokes, then cross-hatching), over a soft smudged graphite wash;
- the plain studio background is left as paper and the drawing fades out towards the edges
  (head and shoulders vignette);
- paper grain where the graphite catches the tooth of the paper.

Strokes are seeded, so the same face is always drawn the same way.
"""

from __future__ import annotations

import math
from functools import lru_cache

import cv2
import numpy as np

SIZE = 1024
LEVELS = 7
# (new strokes at this level, angle in degrees) - each level keeps the strokes of the ones before
_LEVEL_STROKES = (
    (520, 50.0),
    (700, 50.0),
    (900, 56.0),
    (1000, 44.0),
    (1200, 50.0),
    (1300, 130.0),
    (1600, 85.0),
)


@lru_cache(maxsize=4)
def _tonal_art_map(size: int, seed: int) -> np.ndarray:
    """(LEVELS + 1, size, size) stroke darkness 0..1, level 0 empty, each level denser."""
    rng = np.random.default_rng(seed)
    stack = np.zeros((LEVELS + 1, size, size), np.float32)
    canvas = np.zeros((size, size), np.uint8)
    scale = size / 1024.0
    for level, (count, base_angle) in enumerate(_LEVEL_STROKES, start=1):
        layer = np.zeros((size, size), np.uint8)
        for _ in range(int(count * scale * scale)):
            x, y = rng.uniform(-20, size + 20, 2)
            length = rng.uniform(26, 62) * scale
            ang = math.radians(base_angle + rng.normal(0, 3))
            dx, dy = math.cos(ang) * length / 2, -math.sin(ang) * length / 2
            # a slight bow, like a stroke from the wrist
            bow = rng.normal(0, 1.2) * scale
            mx, my = x + bow * math.sin(ang), y + bow * math.cos(ang)
            pts = np.array([[x - dx, y - dy], [mx, my], [x + dx, y + dy]], np.int32)
            shade = int(rng.uniform(90, 190))
            cv2.polylines(layer, [pts], False, shade, 1, cv2.LINE_AA)
        canvas = np.maximum(canvas, layer)
        stack[level] = canvas.astype(np.float32) / 255.0
    return stack


def _hatch(darkness: np.ndarray, seed: int) -> np.ndarray:
    """Stroke darkness for a tone map (0 = paper, 1 = darkest), blended between levels."""
    size = darkness.shape[0]
    tam = _tonal_art_map(size, seed)
    pos = np.clip(darkness, 0.0, 0.999) * LEVELS
    lo = np.floor(pos).astype(np.int64)
    frac = (pos - lo).astype(np.float32)
    a = np.take_along_axis(tam, lo[None], axis=0)[0]
    b = np.take_along_axis(tam, np.minimum(lo + 1, LEVELS)[None], axis=0)[0]
    return a * (1 - frac) + b * frac


def _xdog(gray: np.ndarray, sigma: float = 1.1, k: float = 1.6, tau: float = 0.985,
          phi: float = 14.0, eps: float = 0.0) -> np.ndarray:  # fmt: skip
    """Line darkness 0..1 (extended difference of Gaussians)."""
    g1 = cv2.GaussianBlur(gray, (0, 0), sigma)
    g2 = cv2.GaussianBlur(gray, (0, 0), sigma * k)
    d = g1 - tau * g2
    e = np.where(d >= eps, 1.0, 1.0 + np.tanh(phi * (d - eps)))
    return np.clip(1.0 - e, 0.0, 1.0).astype(np.float32)


def _vignette(shape: tuple[int, int], lm: np.ndarray | None) -> np.ndarray:
    """1 over the head and shoulders, fading to 0 (bare paper) towards the edges."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if lm is not None and len(lm):
        px = lm[:, 0] * w
        py = lm[:, 1] * h
        fw, fh = float(px.max() - px.min()), float(py.max() - py.min())
        cx = float(px.mean())
        cy = float(py.min()) + fh * 0.45
        rx, ry = fw * 1.25, fh * 1.35
    else:
        cx, cy, rx, ry = w / 2, h * 0.5, w * 0.42, h * 0.55
    r = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    m = np.clip((1.18 - r) / 0.38, 0.0, 1.0)
    return (m * m * (3 - 2 * m)).astype(np.float32)


def _background(gray: np.ndarray) -> np.ndarray:
    """1 where the picture is the plain studio backdrop: smooth (low gradient, even if it is a
    light-to-dark gradient) and connected to the image border. Left as bare paper."""
    blur = cv2.GaussianBlur(gray, (0, 0), 2.5)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    smooth_area = cv2.GaussianBlur(np.hypot(gx, gy), (0, 0), 3) < 0.035
    flat: np.ndarray = (smooth_area & (blur > 0.42)).astype(np.uint8)  # hair is never backdrop
    flat = cv2.morphologyEx(flat, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    _, labels = cv2.connectedComponents(flat)
    border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    keep_ids = [i for i in np.unique(border) if i != 0]
    keep: np.ndarray = np.isin(labels, keep_ids).astype(np.float32)
    keep = cv2.erode(keep, np.ones((7, 7), np.uint8))  # keep the outline of hair and shoulders
    return cv2.GaussianBlur(keep, (0, 0), 6)


def frame_head(
    img: np.ndarray, lm: np.ndarray | None, face_frac: float = 0.42
) -> tuple[np.ndarray, np.ndarray | None]:
    """Crop a far-away face to head and shoulders (face about ``face_frac`` of the height),
    as in a composite; landmarks are moved with it. Close-ups are returned unchanged."""
    if lm is None or not len(lm):
        return img, lm
    h, w = img.shape[:2]
    py0, py1 = float(lm[:, 1].min()) * h, float(lm[:, 1].max()) * h
    fh = py1 - py0
    if fh >= face_frac * h * 0.85:
        return img, lm
    side = min(min(h, w), max(64.0, fh / face_frac))
    cx = float(lm[:, 0].mean()) * w
    cy = py0 + fh * 0.62
    x0 = int(round(min(max(cx - side / 2, 0), w - side)))
    y0 = int(round(min(max(cy - side / 2, 0), h - side)))
    s_int = int(round(side))
    crop = img[y0 : y0 + s_int, x0 : x0 + s_int]
    out = cv2.resize(crop, (w, h), interpolation=cv2.INTER_CUBIC)
    moved = lm.copy()
    moved[:, 0] = (lm[:, 0] * w - x0) / s_int
    moved[:, 1] = (lm[:, 1] * h - y0) / s_int
    return out, moved


def _grain(shape: tuple[int, int], seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 7)
    noise = rng.normal(0.0, 1.0, shape).astype(np.float32)
    g: np.ndarray = cv2.GaussianBlur(noise, (0, 0), 0.8)
    lo, hi = float(g.min()), float(g.max())
    return (g - lo) / (hi - lo + 1e-6)


def render(
    img_bgr: np.ndarray, lm: np.ndarray | None = None, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """(finished pencil sketch, contour lines only) as BGR images of the input size."""
    h0, w0 = img_bgr.shape[:2]
    img = cv2.resize(img_bgr, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    gray8 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray8 = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(gray8)
    smooth = cv2.bilateralFilter(gray8, 9, 38, 7).astype(np.float32) / 255.0

    paper_mask = np.clip(_vignette((SIZE, SIZE), lm) * (1.0 - 0.92 * _background(smooth)), 0, 1)

    # tone: lighter mid-tones than a photo, as in a graphite drawing
    darkness = np.clip((1.0 - smooth) ** 1.25 * 1.08, 0.0, 1.0) * paper_mask
    wash = cv2.GaussianBlur(darkness, (0, 0), 3.0)
    hatch = _hatch(cv2.GaussianBlur(darkness, (0, 0), 1.5), seed)

    lines = _xdog(smooth) * np.clip(paper_mask * 1.3, 0, 1)
    skips = cv2.GaussianBlur(
        np.random.default_rng(seed + 3).random((SIZE // 8, SIZE // 8)).astype(np.float32), (0, 0), 1
    )
    skips = cv2.resize(skips, (SIZE, SIZE), interpolation=cv2.INTER_CUBIC)
    lines *= np.clip((skips - 0.18) * 3.0, 0.35, 1.0)  # a pencil line is never perfectly even

    # light skin stays a soft wash; strokes build up only in the mid and dark tones
    build = np.clip((darkness - 0.18) / 0.5, 0.0, 1.0)
    dark = np.clip(0.5 * wash + 0.55 * hatch * build, 0.0, 1.0)
    dark = np.maximum(dark, lines * 0.82)
    grain = _grain((SIZE, SIZE), seed)
    dark *= 0.82 + 0.18 * grain  # graphite catches the tooth of the paper
    tone = 1.0 - dark
    sketch8: np.ndarray = np.clip(tone * 255.0 + 4.0, 0, 255).astype(np.uint8)
    lines8: np.ndarray = np.clip((1.0 - lines * 0.85) * 255.0, 0, 255).astype(np.uint8)
    if (h0, w0) != (SIZE, SIZE):
        sketch8 = cv2.resize(sketch8, (w0, h0), interpolation=cv2.INTER_AREA)
        lines8 = cv2.resize(lines8, (w0, h0), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(sketch8, cv2.COLOR_GRAY2BGR), cv2.cvtColor(lines8, cv2.COLOR_GRAY2BGR)
