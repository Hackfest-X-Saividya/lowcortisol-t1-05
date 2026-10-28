"""Accessory and mark overlays placed from landmarks (no AI).

A similarity transform maps the PNG's two anchor pixels onto two anchor landmarks (or,
for positional overlays such as scars, onto a landmark chosen by ``position`` with a width
derived from the inter-eye distance). The PNG is warped and alpha-blended (normal or
multiply). Overlays are re-applied after every shape edit, so they follow the warped face
instead of being distorted by it.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import Settings
from app.core.errors import ValidationFailed
from app.services.sketch.overlay_assets import ensure_placeholders


@lru_cache(maxsize=2)
def load_catalog(overlay_dir: str) -> dict[str, dict[str, Any]]:
    d = Path(overlay_dir)
    path = ensure_placeholders(d)
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


@lru_cache(maxsize=64)
def _load_png(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def catalog_public(settings: Settings) -> list[dict[str, Any]]:
    cat = load_catalog(str(settings.assets_path / "overlays"))
    out = []
    for oid, spec in cat.items():
        out.append(
            {
                "id": oid,
                "name": spec.get("name", oid),
                "region": spec.get("region", ""),
                "positional": bool(spec.get("positional")),
                "positions": sorted((spec.get("positions") or {}).keys()),
                "thumbnail": f"/overlays/{oid}/thumbnail",
            }
        )
    return out


def overlay_png_bytes(settings: Settings, overlay_id: str) -> bytes:
    cat = load_catalog(str(settings.assets_path / "overlays"))
    spec = cat.get(overlay_id)
    if spec is None:
        raise ValidationFailed(f"Unknown overlay {overlay_id}")
    return (settings.assets_path / "overlays" / spec["file"]).read_bytes()


def _anchor_points(
    spec: dict[str, Any], lm_px: np.ndarray, params: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    if spec.get("positional"):
        positions: dict[str, int] = spec.get("positions") or {}
        pos = str(params.get("position") or next(iter(positions)))
        if pos not in positions:
            raise ValidationFailed(f"Overlay {spec.get('name')} cannot be placed at {pos}")
        centre = lm_px[int(positions[pos])]
        r1, r2 = spec.get("ref_landmarks", [33, 263])
        ref = lm_px[int(r2)] - lm_px[int(r1)]
        width = (
            float(np.linalg.norm(ref))
            * float(spec.get("ref_scale", 0.3))
            * float(params.get("size", 1.0))
        )
        angle = math.atan2(ref[1], ref[0])
        a1 = centre - 0.5 * width * np.array([math.cos(angle), math.sin(angle)])
        a2 = centre + 0.5 * width * np.array([math.cos(angle), math.sin(angle)])
        return a1, a2
    i, j = spec["anchor_landmarks"]
    a1, a2 = lm_px[int(i)].copy(), lm_px[int(j)].copy()
    scale = float(spec.get("scale", 1.0)) * float(params.get("size", 1.0))
    mid = (a1 + a2) / 2
    a1 = mid + (a1 - mid) * scale
    a2 = mid + (a2 - mid) * scale
    off = spec.get("offset") or [0.0, 0.0]
    d = a2 - a1
    length = float(np.linalg.norm(d))
    n = np.array([-d[1], d[0]]) / max(length, 1e-6)  # perpendicular (image down is +y)
    shift = (d / max(length, 1e-6)) * off[0] * length + n * off[1] * length
    return a1 + shift, a2 + shift


def place_overlay(
    img: np.ndarray, lm: np.ndarray, spec: dict[str, Any], png: np.ndarray, params: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    """Return (image with overlay, alpha mask float32 HxW)."""
    h, w = img.shape[:2]
    lm_px = lm * [w, h]
    a1, a2 = _anchor_points(spec, lm_px, params)
    p1, p2 = (np.asarray(p, dtype=np.float64) for p in spec["png_anchors"])
    src_vec, dst_vec = p2 - p1, a2 - a1
    s = float(np.linalg.norm(dst_vec)) / max(float(np.linalg.norm(src_vec)), 1e-6)
    theta = math.atan2(dst_vec[1], dst_vec[0]) - math.atan2(src_vec[1], src_vec[0])
    c, sn = math.cos(theta) * s, math.sin(theta) * s
    R = np.array([[c, -sn], [sn, c]])
    t = a1 - R @ p1
    M = np.hstack([R, t[:, None]]).astype(np.float32)
    warped = cv2.warpAffine(
        png,
        M,
        (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    alpha = warped[:, :, 3].astype(np.float32) / 255.0
    colour = warped[:, :, :3].astype(np.float32)
    base = img.astype(np.float32)
    if spec.get("blend") == "multiply":
        blended = base * (colour / 255.0)
    else:
        blended = colour
    a3 = alpha[:, :, None]
    out = a3 * blended + (1.0 - a3) * base
    return np.clip(out, 0, 255).astype(np.uint8), alpha


def apply_overlays(
    settings: Settings, img: np.ndarray, lm: np.ndarray, overlays: list[dict[str, Any]]
) -> tuple[np.ndarray, np.ndarray]:
    """Apply a list of ``{"overlay_id", "params"}`` in order. Returns (image, union alpha)."""
    cat = load_catalog(str(settings.assets_path / "overlays"))
    out = img.copy()
    union = np.zeros(img.shape[:2], np.float32)
    for item in overlays:
        oid = str(item.get("overlay_id", ""))
        spec = cat.get(oid)
        if spec is None:
            raise ValidationFailed(f"Unknown overlay {oid}")
        png = _load_png(str(settings.assets_path / "overlays" / spec["file"]))
        out, alpha = place_overlay(out, lm, spec, png, item.get("params") or {})
        union = np.maximum(union, alpha)
    return out, union


def overlay_region(settings: Settings, overlay_id: str) -> str:
    cat = load_catalog(str(settings.assets_path / "overlays"))
    spec = cat.get(overlay_id)
    if spec is None:
        raise ValidationFailed(f"Unknown overlay {overlay_id}")
    return str(spec.get("region", "marks"))
