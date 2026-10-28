"""Pencil sketch rendering: greyscale -> invert -> blur -> colour dodge, multiplied with
XDoG edges. The witness only ever sees this rendering, never the photoreal master."""

from __future__ import annotations

import cv2
import numpy as np

from app.config import Settings


def xdog_edges(gray: np.ndarray, sigma: float, k: float, tau: float, phi: float) -> np.ndarray:
    g = gray.astype(np.float32) / 255.0
    g1 = cv2.GaussianBlur(g, (0, 0), sigma)
    g2 = cv2.GaussianBlur(g, (0, 0), sigma * k)
    dog = g1 - tau * g2
    edges = np.where(dog >= 0.0, 1.0, 1.0 + np.tanh(phi * dog))
    # inside near-black areas (dark hair, beards) the sign of the DoG follows JPEG noise and
    # leaves black blocks: fade the edges out there (the tone layer keeps those areas dark)
    local = cv2.GaussianBlur(g, (0, 0), 4.0)
    keep = np.clip((local - 0.06) / 0.12, 0.0, 1.0)
    edges = 1.0 - (1.0 - edges) * keep
    return np.clip(edges, 0.0, 1.0).astype(np.float32)


def pencil_sketch(img_bgr: np.ndarray, settings: Settings | None = None) -> np.ndarray:
    blur_sigma = settings.sketch_blur_sigma if settings else 9.0
    xs = settings.sketch_xdog_sigma if settings else 1.0
    xk = settings.sketch_xdog_k if settings else 1.6
    xt = settings.sketch_xdog_tau if settings else 0.98
    xp = settings.sketch_xdog_phi if settings else 10.0
    weight = settings.sketch_edge_weight if settings else 0.55

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    inv = 255 - gray
    blur = cv2.GaussianBlur(inv, (0, 0), blur_sigma).astype(np.float32)
    # colour dodge in float: uint8 cv2.divide returns 0 (black blocks) where the blurred
    # inverse reaches 255, i.e. inside very dark hair or beards
    dodge_f = np.clip(gray.astype(np.float32) / np.maximum(255.0 - blur, 1.0), 0.0, 1.0)
    # in near-black areas the dodge flips between 0 and 1 on single grey levels (blotches):
    # leave those to the graphite tone below
    local = cv2.GaussianBlur(gray.astype(np.float32) / 255.0, (0, 0), 4.0)
    keep = np.clip((local - 0.06) / 0.12, 0.0, 1.0)
    dodge_f = dodge_f * keep + (1.0 - keep)
    edges = xdog_edges(gray, xs, xk, xt, xp)
    # graphite tone: keeps dark hair, brows, beard and shadows dark like a forensic
    # composite (a pure colour-dodge washes them out to white)
    tone = cv2.GaussianBlur(gray, (0, 0), 1.6).astype(np.float32) / 255.0
    tone = np.clip(tone, 0.0, 1.0) ** 0.9
    shading = 0.28 + 0.72 * tone
    out = dodge_f * (1.0 - weight + weight * edges) * (0.5 + 0.5 * shading)
    out = np.minimum(out, shading + 0.18)
    # levels: paper white stays white, the darkest graphite goes properly dark
    lo, hi = np.percentile(out, 0.5), np.percentile(out, 99.0)
    if hi - lo > 0.05:
        out = np.clip((out - lo) / (hi - lo), 0.0, 1.0) ** 1.12
    out8 = np.clip(out * 255.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(out8, cv2.COLOR_GRAY2BGR)


def line_drawing(img_bgr: np.ndarray, settings: Settings | None = None) -> np.ndarray:
    """Only the pencil outlines (no shading): the first pass of the live drawing."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    xs = settings.sketch_xdog_sigma if settings else 1.0
    edges = xdog_edges(gray, xs * 1.2, 1.6, 0.985, 14.0)
    # darker, slightly heavier strokes so the outline pass reads as a drawing on paper
    edges = cv2.erode(edges, np.ones((2, 2), np.uint8)) ** 2.2
    out8 = np.clip(edges * 255.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(out8, cv2.COLOR_GRAY2BGR)


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return buf.tobytes()


def decode_png(data: bytes, gray: bool = False) -> np.ndarray:
    flag = cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR
    img = cv2.imdecode(np.frombuffer(data, np.uint8), flag)
    if img is None:
        raise ValueError("could not decode image")
    return img


def watermark(img_bgr: np.ndarray, text: str) -> np.ndarray:
    out = img_bgr.copy()
    h, w = out.shape[:2]
    scale = max(0.6, w / 1400)
    thickness = max(1, int(scale * 2))
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    x, y = max(10, (w - tw) // 2), h - 20
    cv2.rectangle(out, (x - 10, y - th - 10), (x + tw + 10, y + 10), (0, 0, 0), -1)
    cv2.putText(
        out, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thickness, cv2.LINE_AA
    )
    return out
