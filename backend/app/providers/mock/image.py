"""Deterministic mock image generation and inpainting (OpenCV drawing, no AI).

The synthetic face is drawn at the canonical template geometry (the same drawing produced
``assets/templates/canonical_face.json``), so in mock mode the template landmarks describe
the generated face exactly and MediaPipe is not needed. Colours vary with the prompt
(skin tone, hair colour, facial hair) and a little deterministic noise with the seed.
"""

from __future__ import annotations

import hashlib

import cv2
import numpy as np

from app.providers.base import ImageRequest, ImageResult, InpaintRequest

SKIN_TONES = {
    "fair": (190, 205, 235),
    "wheatish": (150, 180, 220),
    "medium brown": (110, 145, 190),
    "dark brown": (70, 95, 140),
}


def _skin_from_prompt(prompt: str) -> tuple[int, int, int]:
    p = prompt.lower()
    for key, bgr in SKIN_TONES.items():
        if key in p:
            return bgr
    if "dark" in p:
        return SKIN_TONES["dark brown"]
    if "fair" in p or "light" in p:
        return SKIN_TONES["fair"]
    return SKIN_TONES["medium brown"]


def draw_face(size: int = 1024, prompt: str = "", seed: int | None = None) -> np.ndarray:
    p = prompt.lower()
    rng = np.random.default_rng(seed or 0)
    bg = 200 + int(rng.integers(-6, 7))
    img: np.ndarray = np.full((size, size, 3), (bg, bg, bg), np.uint8)
    cx, cy = size // 2, int(size * 0.52)
    fw, fh = int(size * 0.22), int(size * 0.30)
    skin = _skin_from_prompt(prompt)
    darker = tuple(max(0, int(c * 0.8)) for c in skin)
    hair_col = (30, 30, 35)
    if "grey hair" in p or "gray hair" in p or "white hair" in p:
        hair_col = (170, 170, 170)
    elif "brown hair" in p:
        hair_col = (40, 60, 90)
    bald = "bald" in p
    long_hair = "long hair" in p

    cv2.rectangle(
        img, (cx - int(fw * 0.45), cy + int(fh * 0.7)), (cx + int(fw * 0.45), size), skin, -1
    )
    cv2.ellipse(
        img,
        (cx, size + int(size * 0.15)),
        (int(size * 0.45), int(size * 0.35)),
        0,
        180,
        360,
        (90, 90, 110),
        -1,
    )
    if not bald:
        cv2.ellipse(
            img,
            (cx, cy - int(fh * 0.15)),
            (int(fw * 1.08), int(fh * (1.25 if long_hair else 1.05))),
            0,
            0,
            360,
            hair_col,
            -1,
        )
    cv2.ellipse(img, (cx, cy), (fw, fh), 0, 0, 360, skin, -1)
    for s in (-1, 1):
        cv2.ellipse(img, (cx + s * fw, cy), (int(fw * 0.12), int(fh * 0.18)), 0, 0, 360, skin, -1)
    if not bald:
        cv2.ellipse(
            img,
            (cx, cy - int(fh * 0.55)),
            (int(fw * 1.0), int(fh * 0.45)),
            0,
            180,
            360,
            hair_col,
            -1,
        )
    overlay = img.copy()
    cv2.ellipse(
        overlay, (cx, cy + int(fh * 0.1)), (int(fw * 0.95), int(fh * 0.85)), 0, 0, 360, darker, -1
    )
    img = cv2.addWeighted(overlay, 0.35, img, 0.65, 0)
    cv2.ellipse(
        img, (cx, cy - int(fh * 0.05)), (int(fw * 0.8), int(fh * 0.75)), 0, 0, 360, skin, -1
    )
    ey = cy - int(fh * 0.12)
    ex = int(fw * 0.42)
    ew, eh = int(fw * 0.22), int(fh * 0.09)
    brow_thick = int(size * (0.016 if "thick" in p else 0.012))
    for s in (-1, 1):
        cv2.ellipse(
            img,
            (cx + s * ex, ey - int(fh * 0.17)),
            (int(ew * 1.2), int(eh * 0.5)),
            0,
            180,
            360,
            (40, 40, 50),
            brow_thick,
        )
        cv2.ellipse(img, (cx + s * ex, ey), (ew, eh), 0, 0, 360, (245, 245, 245), -1)
        cv2.circle(img, (cx + s * ex, ey), int(eh * 0.8), (60, 80, 110), -1)
        cv2.circle(img, (cx + s * ex, ey), int(eh * 0.4), (10, 10, 10), -1)
        cv2.circle(
            img,
            (cx + s * ex - int(eh * 0.25), ey - int(eh * 0.25)),
            int(eh * 0.15),
            (255, 255, 255),
            -1,
        )
        cv2.ellipse(img, (cx + s * ex, ey), (ew, eh), 0, 180, 360, (60, 50, 50), 2)
    ny = cy + int(fh * 0.22)
    cv2.line(img, (cx, ey + int(fh * 0.05)), (cx - int(fw * 0.08), ny), darker, 3)
    cv2.ellipse(img, (cx, ny), (int(fw * 0.17), int(fh * 0.07)), 0, 0, 180, darker, 3)
    cv2.circle(img, (cx - int(fw * 0.1), ny), int(fw * 0.04), darker, -1)
    cv2.circle(img, (cx + int(fw * 0.1), ny), int(fw * 0.04), darker, -1)
    my = cy + int(fh * 0.5)
    if "moustache" in p or "mustache" in p:
        cv2.ellipse(
            img,
            (cx, my - int(fh * 0.14)),
            (int(fw * 0.3), int(fh * 0.05)),
            0,
            180,
            360,
            (40, 40, 50),
            -1,
        )
    if "beard" in p and "no beard" not in p:
        cv2.ellipse(
            img,
            (cx, cy + int(fh * 0.62)),
            (int(fw * 0.75), int(fh * 0.4)),
            0,
            0,
            180,
            (40, 40, 50),
            -1,
        )
    cv2.ellipse(img, (cx, my), (int(fw * 0.32), int(fh * 0.08)), 0, 0, 360, (90, 80, 160), -1)
    cv2.line(img, (cx - int(fw * 0.32), my), (cx + int(fw * 0.32), my), (60, 50, 110), 3)
    img = cv2.GaussianBlur(img, (0, 0), 1.2)
    noise = rng.integers(-2, 3, size=img.shape, dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    return img


class MockImageGen:
    name = "mock"
    model = "mock-face-drawer"

    async def generate(self, req: ImageRequest) -> ImageResult:
        img = draw_face(req.width, req.prompt, req.seed)
        if req.height != req.width:
            img = cv2.resize(img, (req.width, req.height), interpolation=cv2.INTER_AREA)
        return ImageResult(png=encode_png(img), provider=self.name, model=self.model, seed=req.seed)


class MockInpainter:
    name = "mock"
    model = "mock-inpainter"

    async def inpaint(self, req: InpaintRequest) -> ImageResult:
        img = decode_image(req.image_png)
        mask = cv2.imdecode(np.frombuffer(req.mask_png, np.uint8), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError("could not decode mask")
        if mask.shape[:2] != img.shape[:2]:
            mask = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        # Deterministic "edit": tint derived from the prompt hash, blurred inside the mask.
        h = hashlib.sha256(req.prompt.encode("utf-8")).digest()
        tint = np.array([h[0] % 60 - 30, h[1] % 60 - 30, h[2] % 60 - 30], dtype=np.int16)
        edited: np.ndarray = cv2.GaussianBlur(img, (0, 0), 3)
        edited = np.clip(edited.astype(np.int16) + tint, 0, 255).astype(np.uint8)
        m = (mask > 127)[:, :, None]
        out = np.where(m, edited, img)
        return ImageResult(png=encode_png(out), provider=self.name, model=self.model, seed=req.seed)
