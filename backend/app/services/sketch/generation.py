"""First face generation: prompt from the feature sheet, cloud generation, face check,
alignment to the canonical template, landmark detection."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from app.config import Settings
from app.core.logging import get_logger
from app.providers.base import ImageRequest
from app.providers.registry import ProviderRegistry
from app.services.sketch.landmarks import Landmarker, Template, eye_mouth_points, load_template
from app.services.sketch.regions import CHEEK_LEFT, CHEEK_RIGHT, NOSE_TIP
from app.services.sketch.render import decode_png

log = get_logger(__name__)

NEGATIVE_PROMPT = (
    "smiling, tilted head, profile, sunglasses, makeup, jewelry, text, watermark, "
    "multiple people, cartoon, drawing"
)
DEFAULT_SKIN = "medium brown"

_PHRASES: dict[str, dict[str, str]] = {
    "gender": {"male": "man", "female": "woman", "unsure": "person"},
    "age_range": {
        "under_20": "about 18 years old",
        "20_30": "about 25 years old",
        "30_40": "about 35 years old",
        "40_50": "about 45 years old",
        "over_50": "about 55 years old",
    },
    "skin_tone": {
        "fair": "fair",
        "wheatish": "wheatish light brown",
        "medium_brown": "medium brown",
        "dark_brown": "dark brown",
    },
    "face_shape": {
        "oval": "oval",
        "round": "round",
        "square": "square",
        "long": "long",
        "heart": "heart-shaped",
        "diamond": "diamond-shaped",
    },
    "hair": {
        "short_straight": "short straight black hair",
        "short_curly": "short curly black hair",
        "medium": "medium length hair",
        "long": "long hair",
        "bald": "bald head",
        "receding": "receding hairline",
        "short": "short hair",
        "long hair": "long hair",
        "curly": "curly hair",
        "grey": "grey hair",
    },
    "eyes": {
        "large": "large eyes",
        "small": "small eyes",
        "narrow": "narrow eyes",
        "round": "round eyes",
        "deep_set": "deep-set eyes",
        "hooded": "hooded eyes",
    },
    "brows": {
        "thick": "thick eyebrows",
        "thin": "thin eyebrows",
        "arched": "arched eyebrows",
        "straight": "straight eyebrows",
        "joined": "joined eyebrows",
    },
    "nose": {
        "straight": "straight nose",
        "broad": "broad nose",
        "hooked": "hooked nose",
        "small": "small nose",
        "long": "long nose",
        "flat": "flat nose",
        "upturned": "upturned nose",
    },
    "mouth": {
        "wide": "wide mouth",
        "small": "small mouth",
        "full_lips": "full lips",
        "thin_lips": "thin lips",
    },
    "jaw": {
        "square": "square jaw",
        "round": "rounded jaw",
        "pointed": "pointed chin",
        "wide": "wide jaw",
        "narrow": "narrow jaw",
    },
    "facial_hair": {
        "none": "clean shaven",
        "stubble": "light stubble",
        "moustache": "moustache",
        "goatee": "goatee",
        "full_beard": "full beard",
    },
}

_NOT_FOR_PROMPT = ("not_remembered", "", "none")


def _value(sheet: dict[str, Any], key: str) -> str:
    entry = sheet.get(key) or {}
    v = str(entry.get("value", "")).strip()
    return "" if v in _NOT_FOR_PROMPT else v


def _phrase(key: str, value: str) -> str:
    table = _PHRASES.get(key, {})
    if value in table:
        return table[value]
    # free text (from extraction or voice answers): keep short, strip crime words
    words = [w for w in value.replace("_", " ").split() if w.lower() not in _CRIME_WORDS]
    return " ".join(words)[:60]


_CRIME_WORDS = {
    "knife",
    "gun",
    "pistol",
    "weapon",
    "robbery",
    "robber",
    "theft",
    "thief",
    "murder",
    "attack",
    "attacker",
    "assault",
    "crime",
    "criminal",
    "suspect",
    "accused",
    "victim",
    "blood",
    "police",
}


@dataclass
class PromptInfo:
    prompt: str
    negative_prompt: str
    notes: list[str] = field(default_factory=list)
    used_fields: list[str] = field(default_factory=list)


def build_prompt(sheet: dict[str, Any]) -> PromptInfo:
    notes: list[str] = []
    used: list[str] = []
    gender = _phrase("gender", _value(sheet, "gender")) or "person"
    age = _phrase("age_range", _value(sheet, "age_range")) or "adult"
    skin_v = _value(sheet, "skin_tone")
    if skin_v:
        skin = _phrase("skin_tone", skin_v)
        used.append("skin_tone")
    else:
        skin = DEFAULT_SKIN
        notes.append(f"skin tone not remembered; defaulted to '{DEFAULT_SKIN}'")
    parts = [f"frontal passport-style photograph of a {gender}, {age}, {skin} skin"]
    for key in ("gender", "age_range"):
        if _value(sheet, key):
            used.append(key)
    for key, suffix in (
        ("face_shape", " face"),
        ("hair", ""),
        ("eyes", ""),
        ("brows", ""),
        ("nose", ""),
        ("mouth", ""),
        ("jaw", ""),
        ("facial_hair", ""),
    ):
        v = _value(sheet, key)
        if v:
            ph = _phrase(key, v)
            if ph:
                parts.append(ph + suffix if key == "face_shape" else ph)
                used.append(key)
    parts.append(
        "neutral expression, looking straight at the camera, plain light grey "
        "background, even studio lighting, head and shoulders"
    )
    prompt = ", ".join(parts)
    return PromptInfo(prompt=prompt, negative_prompt=NEGATIVE_PROMPT, notes=notes, used_fields=used)


# ---- face check ----------------------------------------------------------------------------


@dataclass
class FaceCheck:
    ok: bool
    faces: int
    yaw_deg: float
    pitch_deg: float
    width_ratio: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "faces": self.faces,
            "yaw_deg": round(self.yaw_deg, 1),
            "pitch_deg": round(self.pitch_deg, 1),
            "width_ratio": round(self.width_ratio, 3),
            "reasons": list(self.reasons),
        }


def estimate_pose(lm: np.ndarray, template: Template | None = None) -> tuple[float, float]:
    """Rough yaw/pitch in degrees from the nose tip offset relative to the eye midpoint."""
    template = template or load_template()
    pts = eye_mouth_points(lm)
    mid = (pts[0] + pts[1]) / 2
    inter = max(float(np.linalg.norm(pts[1] - pts[0])), 1e-6)
    tpts = eye_mouth_points(template.landmarks)
    tmid = (tpts[0] + tpts[1]) / 2
    tinter = max(float(np.linalg.norm(tpts[1] - tpts[0])), 1e-6)
    rx = (lm[NOSE_TIP][0] - mid[0]) / inter - (template.landmarks[NOSE_TIP][0] - tmid[0]) / tinter
    ry = (lm[NOSE_TIP][1] - mid[1]) / inter - (template.landmarks[NOSE_TIP][1] - tmid[1]) / tinter
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, rx * 1.6))))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, ry * 1.6))))
    return yaw, pitch


def face_check(faces: list[np.ndarray], settings: Settings) -> FaceCheck:
    reasons: list[str] = []
    if len(faces) != 1:
        reasons.append(f"expected exactly one face, found {len(faces)}")
        return FaceCheck(False, len(faces), 0.0, 0.0, 0.0, reasons)
    lm = faces[0]
    yaw, pitch = estimate_pose(lm)
    width = float(np.linalg.norm(lm[CHEEK_LEFT] - lm[CHEEK_RIGHT]))
    if abs(yaw) > settings.face_check_max_yaw_deg:
        reasons.append(f"head yaw {yaw:.0f} deg exceeds {settings.face_check_max_yaw_deg:.0f}")
    if abs(pitch) > settings.face_check_max_pitch_deg:
        reasons.append(
            f"head pitch {pitch:.0f} deg exceeds {settings.face_check_max_pitch_deg:.0f}"
        )
    if width < settings.face_check_min_width_ratio:
        reasons.append(
            f"face width {width:.2f} of image is below {settings.face_check_min_width_ratio:.2f}"
        )
    return FaceCheck(not reasons, 1, yaw, pitch, width, reasons)


# ---- alignment -------------------------------------------------------------------------------


def similarity_transform(src_pts: np.ndarray, dst_pts: np.ndarray) -> np.ndarray:
    """Least-squares similarity (rotation, uniform scale, translation) 2x3 matrix."""
    M, _ = cv2.estimateAffinePartial2D(
        src_pts.astype(np.float32), dst_pts.astype(np.float32), method=cv2.LMEDS
    )
    if M is None:
        raise ValueError("could not estimate similarity transform")
    return M.astype(np.float64)


def apply_transform_points(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    ones = np.ones((pts.shape[0], 1))
    return (np.hstack([pts, ones]) @ M.T)[:, :2]


def align(
    img: np.ndarray, lm: np.ndarray, template: Template, size: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Align the face so its eye centres and mouth centre land on the template targets.

    Returns (aligned image size x size, transformed landmarks normalized, 2x3 matrix in px).
    """
    h, w = img.shape[:2]
    src = eye_mouth_points(lm) * [w, h]
    dst = template.targets * size
    M = similarity_transform(src, dst)
    # Fill anything outside the source frame with the image's own border colour (the
    # generated backgrounds are plain) instead of replicating edge pixels into streaks.
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]]).reshape(-1, img.shape[2])
    fill = tuple(int(v) for v in np.median(border, axis=0))
    aligned = cv2.warpAffine(
        img,
        M,
        (size, size),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=fill,
    )
    new_lm = apply_transform_points(M, lm * [w, h]) / size
    return aligned, new_lm, M


# ---- generation ------------------------------------------------------------------------------


@dataclass
class Generated:
    master: np.ndarray
    landmarks: np.ndarray
    seed: int
    provider: str
    model: str
    prompt: PromptInfo
    quality_warning: bool
    attempts: list[dict[str, Any]]
    landmark_source: str


async def generate_master(
    registry: ProviderRegistry,
    landmarker: Landmarker | None,
    settings: Settings,
    sheet: dict[str, Any],
    seed: int | None = None,
) -> Generated:
    template = load_template()
    pinfo = build_prompt(sheet)
    size = settings.face_size_px
    rng = random.Random(seed)
    attempts: list[dict[str, Any]] = []
    best: tuple[int, np.ndarray, list[np.ndarray], str, str, FaceCheck, str] | None = None
    current_seed = seed if seed is not None else rng.randint(1, 2**31 - 1)
    for _attempt in range(settings.generation_max_attempts):
        res = await registry.generate_image(
            ImageRequest(
                prompt=pinfo.prompt,
                negative_prompt=pinfo.negative_prompt,
                width=size,
                height=size,
                seed=current_seed,
            )
        )
        img = decode_png(res.png)
        if img.shape[0] != size or img.shape[1] != size:
            img = cv2.resize(img, (size, size), interpolation=cv2.INTER_LANCZOS4)
        faces: list[np.ndarray]
        lm_source = "mediapipe"
        if res.provider == "mock" or landmarker is None or not landmarker.available:
            faces = [template.landmarks.copy()]
            lm_source = "template"
        else:
            try:
                faces = landmarker.detect(img)
            except Exception:  # noqa: BLE001
                faces = [template.landmarks.copy()]
                lm_source = "template"
        check = face_check(faces, settings)
        attempts.append(
            {
                "seed": current_seed,
                "provider": res.provider,
                "model": res.model,
                "cached": res.cached,
                "check": check.as_dict(),
                "landmarks": lm_source,
            }
        )
        score = (1 if check.ok else 0, -len(check.reasons))
        if best is None or score > (1 if best[5].ok else 0, -len(best[5].reasons)):
            best = (current_seed, img, faces, res.provider, res.model, check, lm_source)
        if check.ok:
            break
        current_seed = rng.randint(1, 2**31 - 1)
    assert best is not None
    used_seed, img, faces, provider, model, check, lm_source = best
    lm = faces[0] if faces else template.landmarks.copy()
    if lm_source == "template":
        aligned, new_lm = img, lm
    else:
        aligned, new_lm, _ = align(img, lm, template, size)
        if landmarker is not None and landmarker.available:
            try:
                redetected = landmarker.detect(aligned)
                if len(redetected) == 1:
                    new_lm = redetected[0]
            except Exception:  # noqa: BLE001
                pass
    return Generated(
        master=aligned,
        landmarks=new_lm,
        seed=used_seed,
        provider=provider,
        model=model,
        prompt=pinfo,
        quality_warning=not check.ok,
        attempts=attempts,
        landmark_source=lm_source,
    )
