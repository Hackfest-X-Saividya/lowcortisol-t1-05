"""Placeholder overlay PNGs and ``anchors.json``.

``scripts/make_placeholder_overlays.py`` calls ``write_placeholders``. The drawings are
deliberately simple transparent shapes; replace the PNGs with better art and keep the
anchor points (two reference pixels per PNG) consistent in ``anchors.json``.

Anchor model (see ``overlays.py``):
- ``png_anchors``: two pixel points in the PNG.
- ``anchor_landmarks``: two landmark indices the PNG anchors are mapped onto, OR
- ``positional``: the overlay is placed at a landmark chosen by ``position`` with a width
  of ``ref_scale`` x the distance between ``ref_landmarks``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

W, H = 512, 256

# Overlay catalogue. Side naming follows MediaPipe (subject's left = image right).
CATALOG: dict[str, dict[str, Any]] = {
    "spectacles_round": {
        "name": "Round spectacles",
        "region": "eyes",
        "anchor_landmarks": [33, 263],
        "png_anchors": [[86, 128], [426, 128]],
        "scale": 1.0,
        "offset": [0.0, 0.0],
        "blend": "normal",
    },
    "spectacles_square": {
        "name": "Square spectacles",
        "region": "eyes",
        "anchor_landmarks": [33, 263],
        "png_anchors": [[86, 128], [426, 128]],
        "scale": 1.0,
        "offset": [0.0, 0.0],
        "blend": "normal",
    },
    "cap": {
        "name": "Cap",
        "region": "hair",
        "anchor_landmarks": [127, 356],
        "png_anchors": [[60, 200], [452, 200]],
        "scale": 1.05,
        "offset": [0.0, -0.42],
        "blend": "normal",
    },
    "turban": {
        "name": "Turban",
        "region": "hair",
        "anchor_landmarks": [127, 356],
        "png_anchors": [[40, 210], [472, 210]],
        "scale": 1.15,
        "offset": [0.0, -0.45],
        "blend": "normal",
    },
    "helmet": {
        "name": "Helmet",
        "region": "hair",
        "anchor_landmarks": [127, 356],
        "png_anchors": [[40, 215], [472, 215]],
        "scale": 1.2,
        "offset": [0.0, -0.35],
        "blend": "normal",
    },
    "face_cloth": {
        "name": "Face cloth",
        "region": "mouth",
        "anchor_landmarks": [234, 454],
        "png_anchors": [[30, 40], [482, 40]],
        "scale": 1.0,
        "offset": [0.0, 0.12],
        "blend": "normal",
    },
    "moustache_thin": {
        "name": "Thin moustache",
        "region": "hair",
        "anchor_landmarks": [61, 291],
        "png_anchors": [[96, 150], [416, 150]],
        "scale": 1.1,
        "offset": [0.0, -0.28],
        "blend": "normal",
    },
    "moustache_thick": {
        "name": "Thick moustache",
        "region": "hair",
        "anchor_landmarks": [61, 291],
        "png_anchors": [[96, 150], [416, 150]],
        "scale": 1.2,
        "offset": [0.0, -0.30],
        "blend": "normal",
    },
    "beard_short": {
        "name": "Short beard",
        "region": "hair",
        "anchor_landmarks": [172, 397],
        "png_anchors": [[70, 60], [442, 60]],
        "scale": 1.05,
        "offset": [0.0, 0.0],
        "blend": "multiply",
    },
    "beard_full": {
        "name": "Full beard",
        "region": "hair",
        "anchor_landmarks": [172, 397],
        "png_anchors": [[60, 50], [452, 50]],
        "scale": 1.15,
        "offset": [0.0, 0.05],
        "blend": "normal",
    },
    "scar": {
        "name": "Scar",
        "region": "marks",
        "positional": True,
        "positions": {"left_cheek": 280, "right_cheek": 50, "forehead": 151, "chin": 199},
        "ref_landmarks": [33, 263],
        "ref_scale": 0.35,
        "png_anchors": [[128, 128], [384, 128]],
        "blend": "multiply",
    },
    "mole": {
        "name": "Mole",
        "region": "marks",
        "positional": True,
        "positions": {"left_cheek": 280, "right_cheek": 50, "forehead": 151, "chin": 199},
        "ref_landmarks": [33, 263],
        "ref_scale": 0.08,
        "png_anchors": [[128, 128], [384, 128]],
        "blend": "multiply",
    },
    "tilak": {
        "name": "Tilak",
        "region": "marks",
        "positional": True,
        "positions": {"forehead": 9},
        "ref_landmarks": [33, 263],
        "ref_scale": 0.12,
        "png_anchors": [[128, 128], [384, 128]],
        "blend": "normal",
    },
    "earring": {
        "name": "Earrings",
        "region": "ears",
        "anchor_landmarks": [132, 361],
        "png_anchors": [[40, 60], [472, 60]],
        "scale": 1.0,
        "offset": [0.0, 0.0],
        "blend": "normal",
    },
}

DARK = (40, 35, 35, 255)
HAIR = (35, 30, 30, 235)


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def _draw(name: str) -> Image.Image:
    im, d = _canvas()
    if name == "spectacles_round":
        for cx in (150, 362):
            d.ellipse((cx - 70, 58, cx + 70, 198), outline=DARK, width=9)
        d.line((220, 128, 292, 128), fill=DARK, width=8)
        d.line((80, 120, 10, 95), fill=DARK, width=7)
        d.line((432, 120, 502, 95), fill=DARK, width=7)
    elif name == "spectacles_square":
        for cx in (150, 362):
            d.rounded_rectangle((cx - 78, 66, cx + 78, 190), radius=16, outline=DARK, width=9)
        d.line((228, 120, 284, 120), fill=DARK, width=8)
        d.line((72, 112, 10, 92), fill=DARK, width=7)
        d.line((440, 112, 502, 92), fill=DARK, width=7)
    elif name == "cap":
        d.chord((40, 30, 472, 330), 180, 360, fill=(40, 60, 120, 255))
        d.rounded_rectangle((20, 185, 300, 215), radius=12, fill=(30, 45, 95, 255))
    elif name == "turban":
        d.ellipse((30, 20, 482, 300), fill=(170, 40, 50, 255))
        for y in (90, 130, 170):
            d.arc((50, y - 60, 462, y + 160), 200, 340, fill=(130, 25, 35, 255), width=10)
    elif name == "helmet":
        d.chord((30, 20, 482, 360), 180, 360, fill=(25, 25, 30, 255))
        d.rounded_rectangle((60, 170, 452, 235), radius=20, fill=(90, 90, 100, 255))
    elif name == "face_cloth":
        d.polygon([(30, 40), (482, 40), (420, 230), (92, 230)], fill=(90, 100, 130, 255))
        d.line((30, 40, 482, 40), fill=(60, 70, 100, 255), width=8)
    elif name in ("moustache_thin", "moustache_thick"):
        thick = 26 if name == "moustache_thick" else 12
        d.ellipse((96, 150 - thick, 256, 150 + thick), fill=HAIR)
        d.ellipse((256, 150 - thick, 416, 150 + thick), fill=HAIR)
    elif name == "beard_short":
        d.chord((70, -120, 442, 240), 0, 180, fill=(35, 30, 30, 170))
    elif name == "beard_full":
        d.chord((60, -150, 452, 256), 0, 180, fill=HAIR)
    elif name == "scar":
        d.line((128, 128, 384, 128), fill=(120, 60, 70, 230), width=10)
        for x in range(150, 384, 50):
            d.line((x, 100, x, 156), fill=(120, 60, 70, 200), width=6)
    elif name == "mole":
        d.ellipse((128 - 60, 128 - 60, 128 + 60, 128 + 60), fill=(45, 30, 30, 240))
        d.ellipse((384 - 1, 128 - 1, 384 + 1, 128 + 1), fill=(0, 0, 0, 0))
    elif name == "tilak":
        d.ellipse((128 - 50, 20, 128 + 50, 236), fill=(30, 40, 200, 230))
    elif name == "earring":
        for cx in (40, 472):
            d.ellipse((cx - 22, 60, cx + 22, 104), outline=(40, 160, 200, 255), width=8)
    return im


def write_placeholders(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    anchors: dict[str, Any] = {}
    for name, spec in CATALOG.items():
        im = _draw(name)
        fname = f"{name}.png"
        im.save(out_dir / fname)
        anchors[name] = {"file": fname, **spec}
    path = out_dir / "anchors.json"
    path.write_text(json.dumps(anchors, indent=2), encoding="utf-8")
    return path


def ensure_placeholders(out_dir: Path) -> Path:
    path = out_dir / "anchors.json"
    if path.exists() and all((out_dir / f"{n}.png").exists() for n in CATALOG):
        return path
    return write_placeholders(out_dir)
