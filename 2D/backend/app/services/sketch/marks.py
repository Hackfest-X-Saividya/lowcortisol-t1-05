"""Moles, birthmarks and scars drawn exactly where the witness said they were.

The image model is not asked to draw marks (it puts them anywhere, or not at all). Instead the
witness's words ("a mole on his left cheek", "birthmark above the right eyebrow", "scar on the
chin") are parsed into a mark type and a place on the face, and the mark is drawn in graphite
on the finished sketch at the matching face landmark (MediaPipe face mesh). Left and right
are the person's own sides, as in a witness statement: the person's left is the right side of
the picture.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import cv2
import numpy as np

MARK_KEYS = ("moles", "scars", "other_marks")

_TYPE_WORDS = (
    ("birthmark", r"birth ?marks?|port[- ]?wine|stain|patch|blotch|discolou?r"),
    ("scar", r"scars?|scarred|cuts?|stitch\w*|slash\w*|burn\w*|wounds?|gash\w*"),
    ("mole", r"moles?|beauty spots?|warts?|dots?|spots?|til\b|marks?"),
)
_NONE = re.compile(r"^\s*(no|none|nothing|not noticed|none noticed|no marks?)\s*\.?$", re.I)

# person's side -> face mesh landmark; "c" = centre line
_ANCHORS: dict[str, dict[str, tuple[int, ...]]] = {
    "cheek": {"left": (425, 454, 425), "right": (205, 234, 205)},  # mid-cheek (blend)
    "temple": {"left": (251,), "right": (21,)},
    "eyebrow": {"left": (282,), "right": (52,)},
    "eye": {"left": (253,), "right": (23,)},  # just under the eye
    "nostril": {"left": (358,), "right": (129,)},
    "mouth": {"left": (291,), "right": (61,)},  # corner of the mouth
    "jaw": {"left": (365,), "right": (136,)},
    "ear": {"left": (454,), "right": (234,)},
}
_CENTRE: dict[str, tuple[int, ...]] = {
    "forehead": (151,),
    "nose": (1,),
    "bridge": (6,),
    "upper lip": (1, 0, 0),  # between nose and lip
    "lower lip": (17, 199),
    "chin": (199, 152),
    "neck": (152,),
}
_REGION_WORDS = (
    (
        "upper lip",
        r"above (?:the |his |her )?(?:upper )?lips?|upper lip"
        r"|over (?:the |his |her )?lip|moustache area",
    ),
    (
        "lower lip",
        r"below (?:the |his |her )?(?:lower )?lips?|lower lip|under (?:the |his |her )?lip",
    ),
    ("eyebrow", r"eye ?brows?|brows?"),
    ("eye", r"eyes?|eyelids?"),
    ("nostril", r"nostrils?|side of (?:the |his |her )?nose"),
    ("bridge", r"bridge"),
    ("nose", r"nose"),
    ("mouth", r"mouth|lips?"),
    ("temple", r"temples?"),
    ("forehead", r"forehead"),
    ("jaw", r"jaw\w*"),
    ("chin", r"chin"),
    ("neck", r"neck|throat"),
    ("ear", r"ears?|earlobe"),
    ("cheek", r"cheeks?|cheekbones?|face"),
)


@dataclass(frozen=True)
class Mark:
    kind: str  # mole | birthmark | scar
    region: str
    side: str  # left | right | centre (the person's own side)
    up: float = 0.0  # shift in face heights (+ = up)
    scale: float = 1.0


def parse(text: str, default_kind: str = "") -> list[Mark]:
    """Marks described in one answer ("a mole on his left cheek and a scar on the chin")."""
    out: list[Mark] = []
    if not text or _NONE.match(text):
        return out
    for part in re.split(r"\s*(?:;|,|\band\b|\balso\b)\s*", text.lower()):
        if not part.strip() or _NONE.match(part):
            continue
        kind = next((k for k, pat in _TYPE_WORDS if re.search(pat, part)), default_kind)
        if not kind:
            continue
        region = next((r for r, pat in _REGION_WORDS if re.search(pat, part)), "cheek")
        side = (
            "left"
            if re.search(r"\bleft\b", part)
            else "right"
            if re.search(r"\bright\b", part)
            else ""
        )
        if region in _CENTRE:
            side = side or "centre"
        elif not side:
            side = "left" if region != "ear" else "right"
        up = 0.0
        if re.search(r"\babove\b|\bover\b|\bupper\b|\btop\b", part) and region not in (
            "upper lip",
        ):
            up = 0.035
        elif re.search(r"\bbelow\b|\bunder\b|\blower\b|\bbottom\b", part) and region != "lower lip":
            up = -0.035
        scale = (
            0.7
            if re.search(r"small|tiny|little|faint", part)
            else 1.6
            if re.search(r"big|large|huge|prominent", part)
            else 1.0
        )
        out.append(Mark(kind, region, side, up, scale))
    return out


def from_sheet(values: dict[str, str]) -> list[Mark]:
    """All marks in the feature sheet values (``moles``, ``scars``, ``other_marks``)."""
    marks: list[Mark] = []
    marks += parse(values.get("moles", ""), "mole")
    marks += parse(values.get("scars", ""), "scar")
    marks += parse(values.get("other_marks", ""), "")
    return marks


def describes_mark(text: str) -> bool:
    return bool(parse(text))


def _point(lm: np.ndarray, m: Mark, w: int, h: int) -> tuple[float, float, float]:
    """(x, y, face width) in pixels."""
    pts = lm[:, :2] * np.array([w, h])
    face_w = float(np.linalg.norm(pts[454] - pts[234]))
    face_h = float(np.linalg.norm(pts[152] - pts[10]))
    side = m.side if m.side in ("left", "right") else "left"
    ids = _CENTRE.get(m.region) or _ANCHORS.get(m.region, _ANCHORS["cheek"])[side]
    if m.region == "cheek":
        p = pts[ids[0]] * 0.7 + pts[ids[1]] * 0.3 + np.array([0, -0.03 * face_h])
    else:
        p = np.mean([pts[i] for i in ids], axis=0)
    if m.region in _CENTRE and m.side in ("left", "right"):
        # "left side of the chin": a little towards that side (person's left = picture right)
        p = p + np.array([0.12 * face_w * (1 if m.side == "left" else -1), 0])
    p = p + np.array([0, -m.up * face_h])
    return float(p[0]), float(p[1]), face_w


def draw(img: np.ndarray, lm: np.ndarray | None, marks: list[Mark]) -> np.ndarray:
    """The image with the marks drawn in graphite (``lm``: normalised face mesh landmarks)."""
    if not marks or lm is None or len(lm) < 455:
        return img
    h, w = img.shape[:2]
    out = img.astype(np.float32) / 255.0
    for m in marks:
        x, y, fw = _point(lm, m, w, h)
        rng = np.random.default_rng(int(hashlib.sha256(repr(m).encode()).hexdigest()[:8], 16))
        ink = np.zeros((h, w), np.float32)
        if m.kind == "mole":
            r = max(2.5, 0.013 * fw * m.scale)
            axes = (int(round(r * rng.uniform(0.9, 1.15))), int(round(r * rng.uniform(0.85, 1.1))))
            cv2.ellipse(
                ink, (int(x), int(y)), axes, rng.uniform(0, 180), 0, 360, 1.0, -1, cv2.LINE_AA
            )
            ink = cv2.GaussianBlur(ink, (0, 0), 0.7) * 0.92
        elif m.kind == "birthmark":
            r = 0.045 * fw * m.scale
            for _ in range(7):
                cx, cy = x + rng.normal(0, r * 0.35), y + rng.normal(0, r * 0.3)
                ax = (int(r * rng.uniform(0.35, 0.7)), int(r * rng.uniform(0.3, 0.6)))
                cv2.ellipse(
                    ink, (int(cx), int(cy)), ax, rng.uniform(0, 180), 0, 360, 1.0, -1, cv2.LINE_AA
                )
            mottle = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 1.2)
            ink = cv2.GaussianBlur(ink, (0, 0), 2.2) * (0.55 + 0.3 * mottle)
        else:  # scar: a slightly jagged line with stitch marks
            length = 0.11 * fw * m.scale
            ang = np.deg2rad(rng.uniform(-35, 35))
            d = np.array([np.cos(ang), np.sin(ang)]) * length / 2
            n = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-6)
            pts = [
                np.array([x, y]) - d + 2 * d * t + n * rng.normal(0, 1.0)
                for t in np.linspace(0, 1, 7)
            ]
            line = np.array(pts, dtype=np.int32)
            cv2.polylines(ink, [line], False, 1.0, max(2, int(fw * 0.006)), cv2.LINE_AA)
            for t in np.linspace(0.2, 0.8, 4):
                c = np.array([x, y]) - d + 2 * d * t
                a, b = c - n * fw * 0.012, c + n * fw * 0.012
                cv2.line(ink, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), 0.7, 1, cv2.LINE_AA)
            ink = cv2.GaussianBlur(ink, (0, 0), 0.6) * 0.85
        out *= 1.0 - np.clip(ink, 0, 1)[:, :, None]
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)
