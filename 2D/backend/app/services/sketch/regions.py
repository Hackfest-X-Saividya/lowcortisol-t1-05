"""Landmark regions, handles, sliders and mirror pairs.

Region index sets come from MediaPipe's own connection lists
(``FaceLandmarksConnections``) so no long index lists are typed by hand. Sub-regions
(jaw, cheekbones) are derived from the face oval using the template geometry.

Side naming follows MediaPipe: "left" is the subject's left, which appears on the image's
right-hand side. Handles are named the same way (``jaw_left`` = landmark 397).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from app.services.sketch.landmarks import load_template


def _indices(connections: list) -> list[int]:  # type: ignore[type-arg]
    s: set[int] = set()
    for c in connections:
        s.add(int(c.start))
        s.add(int(c.end))
    return sorted(s)


@lru_cache(maxsize=1)
def mediapipe_regions() -> dict[str, list[int]]:
    from mediapipe.tasks.python.vision.face_landmarker import FaceLandmarksConnections as C

    return {
        "face_oval": _indices(C.FACE_LANDMARKS_FACE_OVAL),
        "left_eye": _indices(C.FACE_LANDMARKS_LEFT_EYE),
        "right_eye": _indices(C.FACE_LANDMARKS_RIGHT_EYE),
        "left_eyebrow": _indices(C.FACE_LANDMARKS_LEFT_EYEBROW),
        "right_eyebrow": _indices(C.FACE_LANDMARKS_RIGHT_EYEBROW),
        "lips": _indices(C.FACE_LANDMARKS_LIPS),
        "nose": _indices(C.FACE_LANDMARKS_NOSE),
        "left_iris": _indices(C.FACE_LANDMARKS_LEFT_IRIS),
        "right_iris": _indices(C.FACE_LANDMARKS_RIGHT_IRIS),
    }


# Anchor landmarks used by handles and sliders.
FOREHEAD, CHIN = 10, 152
JAW_RIGHT, JAW_LEFT = 172, 397  # subject's right (image left) / subject's left (image right)
CHEEK_RIGHT, CHEEK_LEFT = 234, 454
EYE_R_OUTER, EYE_R_INNER, EYE_L_INNER, EYE_L_OUTER = 33, 133, 362, 263
EYE_R_TOP, EYE_R_BOTTOM, EYE_L_TOP, EYE_L_BOTTOM = 159, 145, 386, 374
NOSE_TIP, NOSE_BRIDGE = 1, 6
NOSTRIL_RIGHT, NOSTRIL_LEFT = 98, 327
MOUTH_RIGHT, MOUTH_LEFT = 61, 291
LIP_TOP, LIP_BOTTOM = 0, 17
BROW_RIGHT, BROW_LEFT = 105, 334
EAR_RIGHT_IDS = [234, 93, 132, 127, 227, 137]
EAR_LEFT_IDS = [454, 323, 361, 356, 447, 366]

# Lock features (feature_locks.feature) -> landmark regions they protect.
FEATURES = ("face_shape", "eyes", "brows", "nose", "mouth", "jaw", "hair", "ears", "skin", "marks")


@lru_cache(maxsize=1)
def feature_regions() -> dict[str, list[int]]:
    """Landmark indices per lock feature (hair/skin/marks have no own landmarks)."""
    mp = mediapipe_regions()
    t = load_template().landmarks
    oval = mp["face_oval"]
    mouth_y = max(t[MOUTH_RIGHT][1], t[MOUTH_LEFT][1])
    eye_y = (t[EYE_R_OUTER][1] + t[EYE_L_OUTER][1]) / 2
    jaw = [i for i in oval if t[i][1] >= mouth_y - 0.01] + [CHIN]
    cheeks = [i for i in oval if eye_y <= t[i][1] < mouth_y - 0.01]
    return {
        "face_shape": oval,
        "jaw": sorted(set(jaw)),
        "cheekbones": sorted(set(cheeks)),
        "eyes": sorted(set(mp["left_eye"] + mp["right_eye"] + mp["left_iris"] + mp["right_iris"])),
        "brows": sorted(set(mp["left_eyebrow"] + mp["right_eyebrow"])),
        "nose": mp["nose"],
        "mouth": mp["lips"],
        "ears": sorted(set(EAR_RIGHT_IDS + EAR_LEFT_IDS)),
        "hair": [],
        "skin": [],
        "marks": [],
    }


@dataclass(frozen=True)
class Handle:
    name: str
    anchor: int
    region: str  # feature region whose points follow the handle
    sigma: float  # Gaussian falloff radius as a fraction of face width
    mirror: str | None = None


HANDLES: dict[str, Handle] = {
    h.name: h
    for h in [
        Handle("forehead", FOREHEAD, "face_shape", 0.35),
        Handle("chin", CHIN, "jaw", 0.35),
        Handle("jaw_right", JAW_RIGHT, "jaw", 0.30, "jaw_left"),
        Handle("jaw_left", JAW_LEFT, "jaw", 0.30, "jaw_right"),
        Handle("cheek_right", CHEEK_RIGHT, "cheekbones", 0.25, "cheek_left"),
        Handle("cheek_left", CHEEK_LEFT, "cheekbones", 0.25, "cheek_right"),
        Handle("eye_right_outer", EYE_R_OUTER, "eyes", 0.12, "eye_left_outer"),
        Handle("eye_right_inner", EYE_R_INNER, "eyes", 0.12, "eye_left_inner"),
        Handle("eye_left_inner", EYE_L_INNER, "eyes", 0.12, "eye_right_inner"),
        Handle("eye_left_outer", EYE_L_OUTER, "eyes", 0.12, "eye_right_outer"),
        Handle("eye_right_top", EYE_R_TOP, "eyes", 0.10, "eye_left_top"),
        Handle("eye_right_bottom", EYE_R_BOTTOM, "eyes", 0.10, "eye_left_bottom"),
        Handle("eye_left_top", EYE_L_TOP, "eyes", 0.10, "eye_right_top"),
        Handle("eye_left_bottom", EYE_L_BOTTOM, "eyes", 0.10, "eye_right_bottom"),
        Handle("nose_tip", NOSE_TIP, "nose", 0.18),
        Handle("nose_bridge", NOSE_BRIDGE, "nose", 0.15),
        Handle("nostril_right", NOSTRIL_RIGHT, "nose", 0.12, "nostril_left"),
        Handle("nostril_left", NOSTRIL_LEFT, "nose", 0.12, "nostril_right"),
        Handle("mouth_right", MOUTH_RIGHT, "mouth", 0.15, "mouth_left"),
        Handle("mouth_left", MOUTH_LEFT, "mouth", 0.15, "mouth_right"),
        Handle("lip_top", LIP_TOP, "mouth", 0.12),
        Handle("lip_bottom", LIP_BOTTOM, "mouth", 0.12),
        Handle("brow_right", BROW_RIGHT, "brows", 0.18, "brow_left"),
        Handle("brow_left", BROW_LEFT, "brows", 0.18, "brow_right"),
    ]
}

MIRROR_PAIRS: list[tuple[str, str]] = sorted(
    {tuple(sorted((h.name, h.mirror))) for h in HANDLES.values() if h.mirror}  # type: ignore[misc]
)

# Sliders: name -> (region, [(handle, dx_factor, dy_factor), ...]). A slider value ``a``
# moves each handle by (dx_factor * a * face_width, dy_factor * a * face_width), where
# face_width is the distance between landmarks 234 and 454.
SLIDERS: dict[str, tuple[str, list[tuple[str, float, float]]]] = {
    "jaw_width": ("jaw", [("jaw_right", -1.0, 0.0), ("jaw_left", 1.0, 0.0)]),
    "face_length": ("face_shape", [("chin", 0.0, 1.0), ("forehead", 0.0, -0.5)]),
    "eye_size": (
        "eyes",
        [
            ("eye_right_outer", -0.5, 0.0),
            ("eye_right_inner", 0.3, 0.0),
            ("eye_left_outer", 0.5, 0.0),
            ("eye_left_inner", -0.3, 0.0),
            ("eye_right_top", 0.0, -0.35),
            ("eye_right_bottom", 0.0, 0.35),
            ("eye_left_top", 0.0, -0.35),
            ("eye_left_bottom", 0.0, 0.35),
        ],
    ),
    "eye_spacing": (
        "eyes",
        [
            ("eye_right_outer", -1.0, 0.0),
            ("eye_right_inner", -1.0, 0.0),
            ("eye_right_top", -1.0, 0.0),
            ("eye_right_bottom", -1.0, 0.0),
            ("eye_left_outer", 1.0, 0.0),
            ("eye_left_inner", 1.0, 0.0),
            ("eye_left_top", 1.0, 0.0),
            ("eye_left_bottom", 1.0, 0.0),
        ],
    ),
    "nose_length": (
        "nose",
        [("nose_tip", 0.0, 1.0), ("nostril_right", 0.0, 0.8), ("nostril_left", 0.0, 0.8)],
    ),
    "nose_width": ("nose", [("nostril_right", -1.0, 0.0), ("nostril_left", 1.0, 0.0)]),
    "lip_fullness": ("mouth", [("lip_top", 0.0, -0.6), ("lip_bottom", 0.0, 0.6)]),
    "brow_height": ("brows", [("brow_right", 0.0, -1.0), ("brow_left", 0.0, -1.0)]),
}

REGION_PARAMS: dict[str, list[str]] = {}
for _name, (_region, _) in SLIDERS.items():
    REGION_PARAMS.setdefault(_region, []).append(_name)

# Edit-router region vocabulary -> lock feature.
ROUTER_REGIONS = (
    "jaw",
    "eyes",
    "nose",
    "mouth",
    "brows",
    "face_shape",
    "hair",
    "skin",
    "ears",
    "marks",
)


def face_width(lm: np.ndarray) -> float:
    """Distance 234 -> 454 in the landmark units (normalized or pixels)."""
    return float(np.linalg.norm(lm[CHEEK_LEFT] - lm[CHEEK_RIGHT]))


def handle_positions(lm: np.ndarray) -> dict[str, list[float]]:
    return {name: [float(lm[h.anchor][0]), float(lm[h.anchor][1])] for name, h in HANDLES.items()}


def slider_moves(name: str, amount: float) -> list[dict[str, float | str]]:
    """Expand a slider value into handle moves (dx, dy as fractions of face width)."""
    if name not in SLIDERS:
        raise KeyError(name)
    _, moves = SLIDERS[name]
    return [{"handle": h, "dx": fx * amount, "dy": fy * amount} for h, fx, fy in moves]


def regions_for_handles(moves: list[dict[str, float | str]]) -> set[str]:
    return {HANDLES[str(m["handle"])].region for m in moves if str(m["handle"]) in HANDLES}
