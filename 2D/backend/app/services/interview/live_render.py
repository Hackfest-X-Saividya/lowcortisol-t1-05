"""Realistic live sketch for the voice interview.

What the witness sees is always a generated sketch of the described person (the stock
library face below is no longer shown: it rarely matched the description). The first sketch is
drawn from the whole description, each feature labelled ("Hair: long curly."), worded as a
precise drawing prompt by the LLM (Groq) and drawn directly as a forensic pencil sketch
(``SKETCH_STYLE``); later changes EDIT that sketch (FLUX.2 reference image) so it stays the same
person; the vision model (Groq Qwen) checks each new sketch against the description and one
corrective edit fixes clear mismatches. While a new sketch is drawn the previous one stays.
The image model draws a realistic photo; ``hand_drawn`` then redraws it as pencil on paper
(contours, graphite hatching, smudging, paper grain), and moles, birthmarks and scars are
drawn by ``marks`` exactly where the witness said (never left to the image model).

Earlier design notes (library and region paths are kept as fallbacks):

- **instant** (about 0.2 s, local): the closest face from the base-face library
  (``assets/base_faces``, chosen by gender, age and facial hair) -> spoken corrections applied
  as landmark warps -> spectacles / headwear overlays -> forensic pencil layers.
- **portrait** (background): a realistic frontal portrait generated from the whole description
  (Workers AI, fixed per-session seed where the model takes one, Pollinations as fallback) ->
  MediaPipe landmarks -> the same warps -> pencil layers. It replaces the instant drawing
  as soon as it is ready; the browser polls ``latest``.

Only one portrait is generated at a time per session, always for the newest description
(intermediate descriptions are skipped). Two layers are returned: outlines (drawn first) and
the shaded composite (filled in after), so the browser can show the sketch being drawn.

``preview`` renders use the witness's words while they are still talking (nothing is stored
except an audit entry); ``commit`` renders are saved as sketch versions (the version tree is
the record of every image the witness saw).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.container import Container
from app.core import audit
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.core.security import Principal
from app.db.models.sketch import SketchVersion
from app.db.repositories import sketch as sketch_repo
from app.db.repositories import statements as repo
from app.providers.base import ImageRequest, InpaintRequest
from app.services import cases as case_service
from app.services.interview import engine, live_warp, prompts
from app.services.interview import portrait as pt
from app.services.interview.fields import FIELD_MAP
from app.services.interview.live import ADJUST_KEY, EDITS_KEY, apply_adjustments
from app.services.sketch import hand_drawn
from app.services.sketch import marks as face_marks
from app.services.sketch.generation import build_prompt
from app.services.sketch.inpaint import inpaint_region
from app.services.sketch.landmarks import landmarks_to_json, load_template
from app.services.sketch.masks import region_binary
from app.services.sketch.overlays import apply_overlays
from app.services.sketch.render import decode_png, encode_png, line_drawing, pencil_sketch

log = get_logger(__name__)

FACE_FIELDS = {
    "gender", "age_range", "build", "skin_tone", "face_shape", "hair", "eyes", "brows", "nose",
    "mouth", "jaw", "ears", "facial_hair", "headwear", "eyewear", "face_cover", "scars", "moles",
    "other_marks",
}  # fmt: skip
EXTRA_PROMPT_FIELDS = ("eyewear", "headwear", "face_cover", "scars", "moles", "other_marks", "ears")

# Core identity fields — a change to these forces a full face re-generation.
CORE_FIELDS = {"gender", "age_range", "skin_tone", "build"}

# Map interview field key → facial region name used by masks.region_binary / inpaint_region.
FIELD_TO_REGION: dict[str, str] = {
    "face_shape": "face_shape",
    "hair": "hair",
    "eyes": "eyes",
    "brows": "brows",
    "nose": "nose",
    "mouth": "mouth",
    "jaw": "jaw",
    "ears": "ears",
    "facial_hair": "skin",
    "eyewear": "eyes",
    "headwear": "hair",
    "face_cover": "skin",
    "scars": "marks",
    "moles": "marks",
    "other_marks": "marks",
}

NEGATIVE = (
    "smiling, open mouth, tilted head, profile, three-quarter view, sunglasses unless described, "
    "makeup, jewellery, text, watermark, multiple people, cartoon, illustration, painting, blurry"
)
PREVIEW_PX = 768
SIZE = 1024
PORTRAIT_TIMEOUT_S = 60.0
BASE_DIR = Path(__file__).resolve().parents[3] / "assets" / "base_faces"

_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CACHE_MAX = 64


def _remember(key: str, value: dict[str, Any]) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def session_seed(session_id: str) -> int:
    return int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16) % 2_000_000_000


def _val(sheet: dict[str, Any], key: str) -> str:
    v = sheet.get(key)
    s = str(v.get("value", "")).strip() if isinstance(v, dict) else ""
    return "" if s in ("", "not_remembered") else s


REGION_FOCUS = {
    "eyes": "both eyes open and clearly visible, natural eyelids and eyelashes, looking straight at the camera",
    "brows": "natural eyebrows above open eyes",
    "nose": "natural nose",
    "mouth": "natural closed mouth",
    "jaw": "natural jaw and chin",
    "ears": "natural ears",
    "face_shape": "natural face",
    "hair": "natural hair",
    "skin": "natural skin",
    "marks": "natural skin",
}
REGION_NEGATIVE = (
    NEGATIVE + ", closed eyes, blank eyes, no eyes, missing eyes, empty face, smooth plastic skin"
)


def region_prompt(sheet: dict[str, Any], region: str) -> str:
    """Short prompt describing only the region being repainted (not the whole passport photo)."""
    parts = []
    for fk, reg in FIELD_TO_REGION.items():
        v = _val(sheet, fk)[:60]
        if reg == region and v and v.lower() not in ("no", "none", "nothing"):
            parts.append(v)
    focus = REGION_FOCUS.get(region, "natural face")
    detail = (", " + ", ".join(parts)) if parts else ""
    return (
        f"close-up photo of a man's face, {focus}{detail}, realistic, natural skin texture, "
        "same person, same lighting, sharp focus"
    )


def has_face_details(sheet: dict[str, Any]) -> bool:
    return any(_val(sheet, k) for k in FACE_FIELDS)


def gender_given(sheet: dict[str, Any]) -> bool:
    """The witness has said the gender, or said they do not remember it."""
    v = sheet.get("gender")
    return isinstance(v, dict) and bool(str(v.get("value", "")).strip())


def realistic_prompt(sheet: dict[str, Any], style: str | None = None) -> str:
    """The description with every feature labelled (cache key and fallback image prompt).
    The image model is always asked for a realistic photo: ``hand_drawn`` makes the pencil look,
    and the marks are drawn separately (see ``_face_now``)."""
    return pt.describe(_face_now(sheet), style or GEN_STYLE)


def legacy_prompt(sheet: dict[str, Any]) -> str:
    """The earlier unlabelled photo prompt (kept for reference)."""
    info = build_prompt(sheet)
    p = info.prompt.replace(
        "frontal passport-style photograph", "realistic frontal passport photograph, sharp focus"
    )
    extra = [_val(sheet, k)[:60] for k in EXTRA_PROMPT_FIELDS if _val(sheet, k)]
    extra = [e for e in extra if e.lower() not in ("no", "none", "nothing")]
    tail = (", " + ", ".join(extra)) if extra else ""
    return f"{p}{tail}, Indian, natural skin texture, documentary photo"


LLM_PROMPT_TIMEOUT_S = 12.0
CHECK_TIMEOUT_S = 15.0
_llm_prompts: OrderedDict[str, str] = OrderedDict()


GEN_STYLE = "photo"


def _face_now(sheet: dict[str, Any]) -> dict[str, str]:
    """Described face features for the image model, without the marks (drawn by ``marks``)."""
    out = {k: _val(sheet, k) for k in FACE_FIELDS if _val(sheet, k)}
    for k in ("moles", "scars"):
        out.pop(k, None)
    if face_marks.describes_mark(out.get("other_marks", "")):
        out.pop("other_marks")
    return out


def _marks(sheet: dict[str, Any]) -> list[face_marks.Mark]:
    return face_marks.from_sheet({k: _val(sheet, k) for k in face_marks.MARK_KEYS})


async def _generation_prompt(container: Container, snap: dict[str, str]) -> str:
    """Drawing prompt written by the LLM from the labelled description (cached); the plain
    labelled description when the LLM is unavailable."""
    settings = container.settings
    style = GEN_STYLE
    if not settings.sketch_llm_prompt or settings.mock_mode:
        return pt.describe(snap, style)
    key = json.dumps([snap, style], sort_keys=True)
    if key in _llm_prompts:
        return _llm_prompts[key]
    try:
        res = await asyncio.wait_for(
            container.providers.llm_json(pt.llm_prompt_request(snap, style)), LLM_PROMPT_TIMEOUT_S
        )
        text = str(res.data.get("prompt") or "").strip()
        if res.provider == "mock" or len(text) < 20:
            raise ValueError("no usable prompt")
        out = pt.with_style(text, style, snap)
    except Exception as exc:  # noqa: BLE001
        log.warning("live_render: LLM sketch prompt unavailable (%s)", type(exc).__name__)
        return pt.describe(snap, style)
    _llm_prompts[key] = out
    while len(_llm_prompts) > _CACHE_MAX:
        _llm_prompts.popitem(last=False)
    return out


def _flux_edit_ready(container: Container) -> bool:
    s = container.settings
    reg = container.providers
    return (
        not s.mock_mode
        and "flux-2" in s.cf_inpaint_model
        and bool(s.inpaint_chain)
        and reg.ready("inpaint", "cloudflare")
        and reg.ready("image", "cloudflare")  # cooling after the daily quota ran out
    )


async def _flux_edit(
    container: Container, img: np.ndarray, instruction: str, seed: int
) -> tuple[np.ndarray, str, str] | None:
    """Whole-image FLUX.2 reference edit (the same person, only the named changes); None when
    unavailable or when the result is not exactly one face."""
    if not _flux_edit_ready(container):
        return None
    h, w = img.shape[:2]
    try:
        res = await asyncio.wait_for(
            container.providers.inpaint(
                InpaintRequest(
                    image_png=encode_png(img),
                    mask_png=b"",
                    prompt=instruction,
                    instruction=instruction,
                    seed=seed,
                    width=w,
                    height=h,
                )
            ),
            PORTRAIT_TIMEOUT_S,
        )
        out = decode_png(res.png)
        if out.shape[:2] != (h, w):
            out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LANCZOS4)
        faces = await asyncio.to_thread(container.landmarker.detect, out)
    except Exception as exc:  # noqa: BLE001
        log.warning("live_render: sketch edit failed (%s)", type(exc).__name__)
        return None
    if len(faces) != 1:
        log.warning("live_render: sketch edit rejected (%d faces found)", len(faces))
        return None
    return out, res.provider, res.model


async def _checked(
    container: Container,
    img: np.ndarray,
    snap: dict[str, str],
    provider: str,
    model: str,
    seed: int,
) -> tuple[np.ndarray, str, str]:
    """The vision model compares the sketch with the description; clear mismatches are fixed
    with one FLUX.2 edit. Any failure keeps the sketch as it is."""
    s = container.settings
    if not s.sketch_verify or s.mock_mode or not snap or not _flux_edit_ready(container):
        return img, provider, model
    small = cv2.resize(img, (768, 768), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return img, provider, model
    try:
        res = await asyncio.wait_for(
            container.providers.vision_json(pt.check_request(buf.tobytes(), snap)),
            CHECK_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("live_render: sketch check unavailable (%s)", type(exc).__name__)
        return img, provider, model
    fixes = pt.fix_lines(res.data, snap) if res.provider != "mock" else []
    if not fixes:
        return img, provider, model
    log.info("live_render: correcting %d mismatched feature(s)", len(fixes))
    got = await _flux_edit(container, img, pt.edit_instruction(fixes, GEN_STYLE), seed)
    # no redraw on the fallback service: its rate limit would cool it down for minutes
    return got if got is not None else (img, provider, model)


# Every portrait must be one face seen straight from the front, of the described gender. The
# image services ignore "front view" now and then (three-quarter views, a woman for "man"), so
# each attempt is measured and checked, and a failing one is drawn again with another seed.
PORTRAIT_ATTEMPTS = 3
# |nose position between the cheek edges - 0.5|: 0.00-0.03 measured on frontal portraits,
# 0.11-0.15 on slightly turned heads and 0.27-0.33 on three-quarter views.
MAX_HEAD_TURN = 0.12
# mismatches that make a sketch a different person: never shown
HARD_MISMATCH = {"gender", "framing"}


def head_turn(lm: np.ndarray) -> float:
    """How far the head is turned sideways (0 = straight at the viewer), from the nose tip's
    position between the left and right face edges (MediaPipe points 1, 234 and 454)."""
    left, right, nose = lm[234, 0], lm[454, 0], lm[1, 0]
    return float(abs((nose - left) / max(right - left, 1e-6) - 0.5))


async def _identity_mismatches(
    container: Container, photo: np.ndarray, snap: dict[str, str]
) -> list[str] | None:
    """Described features the image clearly contradicts (vision model); None = not checked."""
    if not snap or not container.settings.sketch_verify:
        return None
    small = cv2.resize(photo, (768, 768), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return None
    try:
        res = await asyncio.wait_for(
            container.providers.vision_json(pt.check_request(buf.tobytes(), snap)),
            CHECK_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("live_render: portrait check unavailable (%s)", type(exc).__name__)
        return None
    if res.provider == "mock":
        log.warning("live_render: portrait not checked (vision model busy or rate limited)")
        return None  # the offline stand-in always says "matches"
    fields = [str(m.get("field", "")) for m in (res.data.get("mismatches") or [])]
    return [f for f in fields if f == "framing" or f in snap]


_RETRY_AFTER = re.compile(r"retry after (\d+)\s*s", re.IGNORECASE)
MAX_LIMIT_WAIT_S = 60


async def _generate(container: Container, req: ImageRequest) -> Any:
    """One image. A short free-tier limit (Pollinations: one image every 45 s per IP) is
    waited out once, so a redraw is not lost to it."""
    for tries in range(2):
        try:
            return await asyncio.wait_for(
                container.providers.generate_image(req), PORTRAIT_TIMEOUT_S
            )
        except ProviderError as exc:
            m = _RETRY_AFTER.search(exc.message)
            if tries or m is None or int(m.group(1)) > MAX_LIMIT_WAIT_S:
                raise
            log.info("live_render: image service asks to wait %ss before the next image", m[1])
            await asyncio.sleep(int(m.group(1)) + 1)
    raise AssertionError("unreachable")


async def _front_facing_photo(
    container: Container, prompt: str, snap: dict[str, str], seed: int
) -> tuple[np.ndarray, Any]:
    """Generate the portrait, redrawing (new seed) any attempt that is not exactly one
    front-facing face or that shows a different gender than described. Raises when no attempt
    qualifies, so the witness keeps the previous sketch instead of a wrong one."""
    s = container.settings
    checkable = not s.mock_mode and container.landmarker is not None
    # with the FLUX.2 edit model available, _checked fixes smaller mismatches by editing
    verify = checkable and not _flux_edit_ready(container)
    best: tuple[tuple[int, int, float], np.ndarray, Any] | None = None
    problems: list[str] = []
    for attempt in range(PORTRAIT_ATTEMPTS):
        req = ImageRequest(
            prompt=prompt,
            negative_prompt=NEGATIVE,
            width=SIZE,
            height=SIZE,
            seed=(seed + attempt * 104_729) % 2_000_000_000,
        )
        try:
            res = await _generate(container, req)
        except (ProviderError, TimeoutError) as exc:
            if attempt == 0:
                raise
            problems.append(f"redraw failed ({type(exc).__name__})")
            break
        photo = decode_png(res.png)
        if photo.shape[:2] != (SIZE, SIZE):
            photo = cv2.resize(photo, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
        if not checkable or res.provider == "mock":
            return photo, res
        faces = await asyncio.to_thread(container.landmarker.detect, photo)
        if len(faces) != 1:
            problems.append(f"{len(faces)} faces")
            continue
        turn = head_turn(faces[0])
        if turn > MAX_HEAD_TURN:
            problems.append(f"head turned {turn:.2f}")
            continue
        wrong = (await _identity_mismatches(container, photo, snap)) if verify else None
        hard = sorted(set(wrong or []) & HARD_MISMATCH)
        if hard:
            problems.append("wrong " + "/".join(hard))
            continue
        rank = (0, len(wrong or []), turn)
        if rank[1] == 0:
            return photo, res
        problems.append(f"{rank[1]} small mismatches")
        if best is None or rank < best[0]:
            best = (rank, photo, res)
    log.warning("live_render: portrait attempts rejected: %s", "; ".join(problems))
    if best is not None:
        return best[1], best[2]
    raise ProviderError(
        "no front-facing portrait matching the description: " + "; ".join(problems),
        provider="image",
    )


_FULL_RE = re.compile(r"chubby|fat|plump|full|fleshy|heavy|round|puffy|wide")
_THIN_RE = re.compile(r"thin|slim|lean|gaunt|narrow|skinny|sunken|hollow")
# Face geometry is changed by warping the existing photo; repainting it with the small
# inpainting model blurs the identity and cannot reshape the outline.
WARP_ONLY_REGIONS = {"face_shape", "jaw"}


def _implied_adjust(sheet: dict[str, Any]) -> dict[str, float]:
    """Warp amounts implied by described face shape (e.g. "chubby face" -> fuller cheeks)."""
    out: dict[str, float] = {}
    shape = _val(sheet, "face_shape").lower()
    if _THIN_RE.search(shape):
        out["face_width"] = -0.12
    elif _FULL_RE.search(shape):
        out["face_width"] = 0.12
    if re.search(r"\blong\b", shape):
        out["face_length"] = 0.10
    if re.search(r"\bsquare\b", shape):
        out["jaw_width"] = 0.08
    return out


def _adjust(sheet: dict[str, Any]) -> dict[str, float]:
    merged: dict[str, float] = {k: float(v) for k, v in _implied_adjust(sheet).items()}
    for k, v in (sheet.get(ADJUST_KEY) or {}).items():
        merged[k] = merged.get(k, 0.0) + float(v)
    return {k: round(max(-0.45, min(0.45, v)), 3) for k, v in merged.items() if abs(v) > 1e-3}


def _jpeg_b64(img: np.ndarray, size: int = PREVIEW_PX) -> str:
    small = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 86])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


# ---- base-face library -----------------------------------------------------------------------


def pick_base(sheet: dict[str, Any]) -> tuple[str, str, str]:
    """(gender, age band, facial hair) for the closest library face."""
    g = _val(sheet, "gender").lower()
    gender = "female" if re.search(r"\b(female|woman|lady|girl|f)\b", g) else "male"
    a = _val(sheet, "age_range").lower()
    nums = [int(n) for n in re.findall(r"\d{1,2}", a)]
    if nums:
        age_n = sum(nums) / len(nums)
        age = "young" if age_n < 32 else ("middle" if age_n < 50 else "older")
    elif re.search(r"old|elder|aged|senior|grey|gray", a):
        age = "older"
    elif re.search(r"young|teen|boy|college|student", a):
        age = "young"
    else:
        age = "middle"
    fh = _val(sheet, "facial_hair").lower()
    if gender == "female" or not fh or re.search(r"\b(no|none|clean|shaved|shaven)\b", fh):
        hair = "clean"
    elif re.search(r"beard|stubble|goatee", fh):
        hair = "beard"
    elif re.search(r"mous|mus", fh):
        hair = "moustache"
    else:
        hair = "clean"
    return gender, age, hair


@dataclass
class _Base:
    img: np.ndarray
    lm: np.ndarray
    key: str


_bases: dict[str, _Base] = {}


def _library_keys() -> list[str]:
    return sorted(p.stem for p in BASE_DIR.glob("*.jpg")) if BASE_DIR.exists() else []


def _load_base(container: Container, key: str) -> _Base | None:
    if key in _bases:
        return _bases[key]
    path = BASE_DIR / f"{key}.jpg"
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return None
    img = cv2.resize(img, (SIZE, SIZE), interpolation=cv2.INTER_CUBIC)
    lm_path = path.with_suffix(".lm.json")
    lm: np.ndarray | None = None
    if lm_path.exists():
        lm = np.asarray(json.loads(lm_path.read_text(encoding="utf-8")), dtype=np.float64)
    elif not container.settings.mock_mode:
        try:
            faces = container.landmarker.detect(img)
            if faces:
                lm = faces[0]
                lm_path.write_text(json.dumps(landmarks_to_json(lm)), encoding="utf-8")
        except Exception:  # noqa: BLE001
            lm = None
    if lm is None:
        lm = load_template().landmarks.copy()
    _bases[key] = _Base(img=img, lm=lm, key=key)
    return _bases[key]


def _closest_base(container: Container, sheet: dict[str, Any]) -> _Base | None:
    keys = _library_keys()
    if not keys:
        return None
    gender, age, hair = pick_base(sheet)
    want = f"{gender}_{age}_{hair}"
    order = [want, f"{gender}_{age}_clean", f"{gender}_middle_{hair}", f"{gender}_middle_clean"]
    for k in order + [k for k in keys if k.startswith(gender)] + keys:
        if k in keys:
            return _load_base(container, k)
    return None


def _instant_overlays(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ew = _val(sheet, "eyewear").lower()
    if ew and not re.search(r"\b(no|none)\b", ew):
        out.append({"overlay_id": "spectacles_round" if "round" in ew else "spectacles_square"})
    hw = _val(sheet, "headwear").lower()
    if hw and not re.search(r"\b(no|none)\b", hw):
        if "turban" in hw or "pagdi" in hw or "peta" in hw:
            out.append({"overlay_id": "turban"})
        elif "helmet" in hw:
            out.append({"overlay_id": "helmet"})
        elif "cap" in hw or "hat" in hw:
            out.append({"overlay_id": "cap"})
    fc = _val(sheet, "face_cover").lower()
    if fc and not re.search(r"\b(no|none)\b", fc):
        out.append({"overlay_id": "face_cloth"})
    return out


# ---- composing -------------------------------------------------------------------------------


def _drawn(container: Container) -> bool:
    """Generated photos are redrawn by hand (``hand_drawn``), with no pasted overlays."""
    return container.settings.sketch_style == "pencil"


def _layers(
    container: Container,
    photo: np.ndarray,
    lm: np.ndarray | None,
    adjust: dict[str, float],
    overlays: list[dict[str, Any]],
    drawn: bool = False,
    mark_list: list[face_marks.Mark] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    settings = container.settings
    if drawn:
        overlays = []  # the image model drew any headwear / eyewear itself
    warped = photo
    if lm is not None and adjust:
        warped, lm = live_warp.warp(photo, lm, adjust)
    if lm is not None and overlays:
        try:
            warped, _ = apply_overlays(settings, warped, lm, overlays)
        except Exception:  # noqa: BLE001
            log.warning("live overlay failed")
    if not drawn:
        return warped, line_drawing(warped, settings), pencil_sketch(warped, settings), lm
    sketch, lines = hand_drawn.render(warped, lm)
    if mark_list:
        where = lm if lm is not None else load_template().landmarks
        sketch = face_marks.draw(sketch, where, mark_list)
        lines = face_marks.draw(lines, where, mark_list)
    return warped, lines, sketch, lm


def _pack(
    kind: str,
    prompt: str,
    adjust: dict[str, float],
    provider: str,
    model: str,
    landmark_source: str,
    base: np.ndarray,
    warped: np.ndarray,
    lines: np.ndarray,
    sketch: np.ndarray,
    lm: np.ndarray | None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "prompt": prompt,
        "adjust": adjust,
        "provider": provider,
        "model": model,
        "landmark_source": landmark_source,
        "landmarks": landmarks_to_json(lm if lm is not None else load_template().landmarks),
        "base_png": encode_png(base),
        "master_png": encode_png(warped),
        "sketch_png": encode_png(sketch),
        "lines_b64": _jpeg_b64(lines),
        "sketch_b64": _jpeg_b64(sketch),
    }


def _keys(sheet: dict[str, Any], seed: int) -> tuple[str, str, str]:
    prompt = realistic_prompt(sheet)
    adjust = _adjust(sheet)
    photo_key = hashlib.sha256(json.dumps([prompt, seed], sort_keys=True).encode()).hexdigest()
    edits = list(sheet.get(EDITS_KEY) or [])
    final_key = hashlib.sha256(
        json.dumps([photo_key, adjust, edits], sort_keys=True).encode()
    ).hexdigest()
    return prompt, photo_key, final_key


def instant(container: Container, sheet: dict[str, Any], seed: int) -> dict[str, Any] | None:
    """Local drawing from the closest library face (no network)."""
    base = _closest_base(container, sheet)
    if base is None:
        return None
    prompt = realistic_prompt(sheet)
    adjust = _adjust(sheet)
    overlays = _instant_overlays(sheet)
    key = hashlib.sha256(
        json.dumps(["instant", base.key, adjust, overlays], sort_keys=True).encode()
    ).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return {**_cache[key], "cached": True}
    warped, lines, sketch, lm = _layers(container, base.img, base.lm.copy(), adjust, overlays)
    out = _pack(
        "instant", prompt, adjust, "library", base.key, "library",
        base.img, warped, lines, sketch, lm,
    )  # fmt: skip
    _remember(key, out)
    return {**out, "cached": False}


async def portrait(container: Container, sheet: dict[str, Any], seed: int) -> dict[str, Any]:
    """Generated portrait from the whole description (cached per prompt + corrections)."""
    prompt, photo_key, final_key = _keys(sheet, seed)
    if final_key in _cache:
        _cache.move_to_end(final_key)
        return {**_cache[final_key], "cached": True}
    adjust = _adjust(sheet)
    photo_entry = _cache.get("photo:" + photo_key)
    if photo_entry is None:
        snap = _face_now(sheet)
        drawing_prompt = await _generation_prompt(container, snap)
        photo, res = await _front_facing_photo(container, drawing_prompt, snap, seed)
        photo, gen_provider, gen_model = await _checked(
            container, photo, snap, res.provider, res.model, seed
        )
        lm = None
        source = "template"
        if res.provider == "mock" or container.settings.mock_mode:
            lm = load_template().landmarks.copy()
        else:
            try:
                faces = await asyncio.to_thread(container.landmarker.detect, photo)
                if faces:
                    lm, source = faces[0], "mediapipe"
                    if _drawn(container):  # a far-away figure -> head and shoulders
                        photo, lm = hand_drawn.frame_head(photo, lm)
            except Exception:  # noqa: BLE001
                lm = None
        photo_entry = {"photo": photo, "lm": lm, "provider": gen_provider, "model": gen_model,
                       "source": source}  # fmt: skip
        _remember("photo:" + photo_key, photo_entry)
    lm0 = photo_entry["lm"]
    warped, lines, sketch, lm = await asyncio.to_thread(
        _layers,
        container,
        photo_entry["photo"],
        None if lm0 is None else lm0.copy(),
        adjust,
        [],
        _drawn(container),
        _marks(sheet),
    )
    out = _pack(
        "portrait", prompt, adjust, photo_entry["provider"], photo_entry["model"],
        photo_entry["source"], photo_entry["photo"], warped, lines, sketch, lm,
    )  # fmt: skip
    _remember(final_key, out)
    return {**out, "cached": False}


# ---- per-session background portraits ------------------------------------------------------


@dataclass
class _Live:
    seq: int = 0
    latest: dict[str, Any] | None = None
    latest_key: str = ""
    running_key: str = ""
    want: tuple[str, dict[str, Any], int] | None = None
    task: asyncio.Task[None] | None = None
    failed: str = ""
    done: dict[str, asyncio.Event] = field(default_factory=dict)
    # Per-session base photo — locked after the first AI portrait so subsequent
    # turns edit only the changed region instead of regenerating the whole face.
    base_photo: np.ndarray | None = None
    base_lm: np.ndarray | None = None
    base_lm_source: str = ""
    base_provider: str = ""
    base_model: str = ""
    # Snapshot of FACE field values at the time the base was generated (used for diffing).
    base_fields: dict[str, str] = field(default_factory=dict)
    # Free-form appearance edits already painted into base_photo (or attempted).
    applied_edits: list[str] = field(default_factory=list)


_live: dict[str, _Live] = {}


def _state(session_id: str) -> _Live:
    st = _live.get(session_id)
    if st is None:
        st = _live[session_id] = _Live()
        while len(_live) > 64:
            _live.pop(next(iter(_live)))
    return st


def _save_base(st: _Live, photo_entry: dict[str, Any], sheet: dict[str, Any]) -> None:
    """Store a newly-generated photo as the session base."""
    st.base_photo = photo_entry["photo"].copy()
    st.base_lm = photo_entry["lm"].copy() if photo_entry["lm"] is not None else None
    st.base_lm_source = photo_entry.get("source", "template")
    st.base_provider = photo_entry["provider"]
    st.base_model = photo_entry["model"]
    st.base_fields = {k: _val(sheet, k) for k in FACE_FIELDS}
    st.applied_edits = []  # a fresh face has none of the earlier free-form edits


def _pending_edits(st: _Live, sheet: dict[str, Any]) -> list[str]:
    return [e for e in (sheet.get(EDITS_KEY) or []) if e not in st.applied_edits]


async def _apply_free_edits(container: Container, st: _Live, sheet: dict[str, Any]) -> bool:
    """Paint any new free-form appearance details (hair length, scars, glasses, ...) into the
    base photo with one FLUX.2 reference-image edit, so no predefined field is needed.

    Keeps the old base on any failure (no face found, provider error, wrong model)."""
    pending = _pending_edits(st, sheet)
    if not pending or st.base_photo is None:
        return False
    settings = container.settings
    if (
        settings.mock_mode
        or "flux-2" not in settings.cf_inpaint_model
        or not settings.inpaint_chain
    ):
        return False  # reference editing needs a FLUX.2 model
    st.applied_edits.extend(pending)  # attempted: never loop on a failing edit
    h, w = st.base_photo.shape[:2]
    try:
        res = await container.providers.inpaint(
            InpaintRequest(
                image_png=encode_png(st.base_photo),
                mask_png=b"",
                prompt="; ".join(pending),
                width=w,
                height=h,
            )
        )
        photo = decode_png(res.png)
        if photo.shape[:2] != (h, w):
            photo = cv2.resize(photo, (w, h), interpolation=cv2.INTER_LANCZOS4)
        faces = await asyncio.to_thread(container.landmarker.detect, photo)
    except Exception as exc:  # noqa: BLE001
        log.warning("live_render: free-form edit failed (%s)", type(exc).__name__)
        return False
    if len(faces) != 1:
        log.warning("live_render: free-form edit rejected (%d faces found)", len(faces))
        return False
    st.base_photo = photo
    st.base_lm, st.base_lm_source = faces[0], "mediapipe"
    st.base_provider, st.base_model = res.provider, res.model
    # The edit already covers whatever the witness said about these features, so do not
    # repaint the same regions again; identity fields (gender/age/skin/build) still regenerate.
    for k in FACE_FIELDS:
        if k not in CORE_FIELDS:
            st.base_fields[k] = _val(sheet, k)
    return True


def _changed_regions(st: _Live, sheet: dict[str, Any]) -> tuple[list[str], bool]:
    """Return (regions_to_inpaint, needs_full_regen).

    Compares the current sheet against base_fields. A CORE_FIELDS change
    triggers a full re-generation; everything else is inpainted per-region.
    """
    regions: list[str] = []
    for fk in FACE_FIELDS:
        if fk in face_marks.MARK_KEYS and get_settings().sketch_style == "pencil":
            continue  # moles, birthmarks and scars are drawn on the sketch (see _marks)
        cur = _val(sheet, fk)
        prev = st.base_fields.get(fk, "")
        if cur == prev:
            continue
        if fk in CORE_FIELDS:
            return [], True
        region = FIELD_TO_REGION.get(fk)
        if region in WARP_ONLY_REGIONS:
            continue
        if region and region not in regions:
            regions.append(region)
    return regions, False


async def portrait_incremental(
    container: Container, st: _Live, sheet: dict[str, Any], seed: int
) -> dict[str, Any]:
    """Edit only the regions that changed since the base was generated.

    Fallback hierarchy:
      1. Core-identity change → full portrait() re-generation.
      2. No landmarks available → full portrait() re-generation.
      3. Inpaint failure → full portrait() re-generation.
      4. No region change → apply warp/overlays on base only (no network call, base_fields NOT updated).
      5. Region changed → inpaint changed region(s), update base.
    """
    # ── 0. Edit the previous sketch: only what the witness changed (same person) ──
    if st.base_photo is not None:
        edited = await _edit_changes(container, st, sheet, seed)
        if edited is not None:
            return edited

    regions, needs_regen = _changed_regions(st, sheet)

    # ── 1. Core identity changed or no base yet ──────────────────────────────
    if needs_regen or st.base_photo is None:
        out = await portrait(container, sheet, seed)
        pe = _cache.get("photo:" + _keys(sheet, seed)[1])
        if pe is not None:
            _save_base(st, pe, sheet)
        return out

    # ── 4. No face change — warp/overlay only (base_fields NOT updated) ──────
    if not regions:
        log.debug("live_render: no region change — reusing base with warp only")
        adjust = _adjust(sheet)
        overlays = _instant_overlays(sheet)
        lm = st.base_lm.copy() if st.base_lm is not None else None
        warped, lines, sketch, lm_out = await asyncio.to_thread(
            _layers, container, st.base_photo, lm, adjust, overlays, _drawn(container),
            _marks(sheet),
        )  # fmt: skip
        prompt = realistic_prompt(sheet)
        return _pack(
            "portrait", prompt, adjust, st.base_provider, st.base_model,
            st.base_lm_source, st.base_photo, warped, lines, sketch, lm_out,
        )  # fmt: skip

    # ── 2. No landmarks — cannot compute mask, fall back to full regen ────────
    if st.base_lm is None:
        log.warning("live_render: no landmarks for session base, falling back to full regen")
        out = await portrait(container, sheet, seed)
        pe = _cache.get("photo:" + _keys(sheet, seed)[1])
        if pe is not None:
            _save_base(st, pe, sheet)
        return out

    # ── 5. Inpaint changed regions on the base photo ─────────────────────────
    log.info("live_render: inpainting regions %s", regions)
    photo = st.base_photo.copy()
    h, w = photo.shape[:2]
    lm_norm = st.base_lm
    provider, model = st.base_provider, st.base_model
    ok = True
    try:
        for region in regions:
            mask = region_binary(lm_norm, region, (h, w))
            photo, provider, model = await inpaint_region(
                container.providers,
                photo,
                mask,
                region_prompt(sheet, region),
                seed,
                pad_frac=0.6,
                negative_prompt=REGION_NEGATIVE,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("live_render: inpaint failed (%s), falling back to full regen", exc)
        ok = False

    # ── 3. Inpaint failure ────────────────────────────────────────────────────
    if not ok:
        out = await portrait(container, sheet, seed)
        pe = _cache.get("photo:" + _keys(sheet, seed)[1])
        if pe is not None:
            _save_base(st, pe, sheet)
        return out

    # Re-detect landmarks on the inpainted photo for accurate warps next turn.
    lm_new: np.ndarray | None = lm_norm
    lm_source = st.base_lm_source
    if not container.settings.mock_mode:
        try:
            faces = await asyncio.to_thread(container.landmarker.detect, photo)
            if faces:
                lm_new, lm_source = faces[0], "mediapipe"
        except Exception:  # noqa: BLE001
            pass

    adjust = _adjust(sheet)
    overlays = _instant_overlays(sheet)
    lm_warp = lm_new.copy() if lm_new is not None else None
    warped, lines, sketch, lm_out = await asyncio.to_thread(
        _layers, container, photo, lm_warp, adjust, overlays, _drawn(container), _marks(sheet)
    )
    prompt = realistic_prompt(sheet)
    out = _pack(
        "portrait", prompt, adjust, provider, model,
        lm_source, photo, warped, lines, sketch, lm_out,
    )  # fmt: skip

    # Update base to the inpainted photo so the next turn diffs against it.
    st.base_photo = photo.copy()
    st.base_lm = lm_new
    st.base_lm_source = lm_source
    st.base_provider = provider
    st.base_model = model
    st.base_fields = {k: _val(sheet, k) for k in FACE_FIELDS}
    return out


async def _edit_changes(
    container: Container, st: _Live, sheet: dict[str, Any], seed: int
) -> dict[str, Any] | None:
    """One FLUX.2 reference edit naming the changed features; None to use the other paths
    (no edit model, nothing changed, a different gender = a different person)."""
    old = {k: v for k, v in st.base_fields.items() if v}
    new = _face_now(sheet)
    if old.get("gender") and new.get("gender") and old["gender"] != new["gender"]:
        return None
    changes = pt.edit_lines(old, new)
    if not changes or st.base_photo is None:
        return None
    got = await _flux_edit(container, st.base_photo, pt.edit_instruction(changes, GEN_STYLE), seed)
    if got is None:
        return None
    photo, provider, model = got
    photo, provider, model = await _checked(container, photo, new, provider, model, seed)
    lm: np.ndarray | None = None
    source = "template"
    try:
        faces = await asyncio.to_thread(container.landmarker.detect, photo)
        if faces:
            lm, source = faces[0], "mediapipe"
    except Exception:  # noqa: BLE001
        lm = None
    st.base_photo = photo.copy()
    st.base_lm, st.base_lm_source = lm, source
    st.base_provider, st.base_model = provider, model
    st.base_fields = {k: _val(sheet, k) for k in FACE_FIELDS}
    adjust = _adjust(sheet)
    warped, lines, sketch, lm_out = await asyncio.to_thread(
        _layers, container, photo, None if lm is None else lm.copy(), adjust, [],
        _drawn(container), _marks(sheet),
    )  # fmt: skip
    return _pack(
        "portrait", realistic_prompt(sheet), adjust, provider, model, source,
        photo, warped, lines, sketch, lm_out,
    )  # fmt: skip


async def _worker(container: Container, session_id: str) -> None:
    st = _state(session_id)
    while st.want is not None:
        key, sheet, seed = st.want
        st.want = None
        st.running_key = key
        try:
            if st.base_photo is None:
                # First generation — full portrait, then lock in the base.
                out = await portrait(container, sheet, seed)
                pe = _cache.get("photo:" + _keys(sheet, seed)[1])
                if pe is not None:
                    _save_base(st, pe, sheet)
                if _pending_edits(st, sheet) and await _apply_free_edits(container, st, sheet):
                    out = await portrait_incremental(container, st, sheet, seed)
            else:
                # Subsequent turns — free-form details first, then edit only what changed.
                await _apply_free_edits(container, st, sheet)
                out = await portrait_incremental(container, st, sheet, seed)
                if _pending_edits(st, sheet) and await _apply_free_edits(container, st, sheet):
                    out = await portrait_incremental(
                        container, st, sheet, seed
                    )  # base was regenerated
            out["edits"] = list(sheet.get(EDITS_KEY) or [])
            st.seq += 1
            st.latest, st.latest_key, st.failed = out, key, ""
        except Exception as exc:  # noqa: BLE001
            st.failed = type(exc).__name__
            log.warning("live portrait failed for session %s: %s", session_id, st.failed)
        st.running_key = ""
        ev = st.done.pop(key, None)
        if ev is not None:
            ev.set()
    st.task = None


def _request(container: Container, session_id: str, sheet: dict[str, Any], seed: int) -> str:
    _, _, key = _keys(sheet, seed)
    st = _state(session_id)
    if st.latest_key == key:
        return key
    st.done.setdefault(key, asyncio.Event())
    if st.running_key != key:
        st.want = (key, sheet, seed)
        if st.task is None:
            st.task = asyncio.create_task(_worker(container, session_id))
    return key


def latest(session_id: str, after: int = 0) -> dict[str, Any]:
    st = _state(session_id)
    out: dict[str, Any] = {"seq": st.seq, "pending": st.task is not None, "failed": st.failed}
    if st.latest is not None and st.seq > after:
        out.update(
            kind=st.latest["kind"],
            lines_b64=st.latest["lines_b64"],
            sketch_b64=st.latest["sketch_b64"],
            provider=st.latest["provider"],
        )
    return out


# ---- API entry -------------------------------------------------------------------------------


async def render(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    session_id: str,
    *,
    text: str | None = None,
    commit: bool = False,
    wait_s: float | None = None,
) -> dict[str, Any]:
    sess, _ = await case_service.require_open_session(db, actor, session_id)
    fs = await repo.get_feature_sheet(db, sess.id)
    sheet: dict[str, Any] = dict(fs.sheet if fs else {})
    preview_fields: list[str] = []
    if text and text.strip() and not commit:
        # words still being spoken: quick extraction into a copy of the sheet (not stored)
        try:
            res = await container.providers.llm_json(prompts.quick_fields(text.strip(), sheet))
            data = res.data
        except Exception:  # noqa: BLE001
            data = {}
        fields = {
            k: v
            for k, v in (data.get("fields") or {}).items()
            if k in FIELD_MAP and k in FACE_FIELDS and isinstance(v, dict)
        }
        sheet = engine.merge_extracted(sheet, fields, source="preview", said=text)
        if data.get("adjustments"):
            sheet[ADJUST_KEY] = apply_adjustments(sheet, list(data["adjustments"]))
        preview_fields = sorted(fields)
    if not has_face_details(sheet):
        return {"ready": False, "reason": "not_enough_detail", "preview_fields": preview_fields}
    if not gender_given(sheet):
        # a face drawn before the witness said man or woman would be the image model's guess
        return {"ready": False, "reason": "need_gender", "preview_fields": preview_fields}

    seed = session_seed(sess.id)
    st = _state(sess.id)
    # While the witness is still talking and the main image service is out of quota, keep the
    # current sketch instead of queueing a drawing for every few words on the slow fallback.
    hold = (
        not commit
        and bool(text)
        and st.latest is not None
        and not container.settings.mock_mode
        and not container.providers.ready("image", container.settings.image_chain[0])
    )
    key = st.latest_key if hold else _request(container, sess.id, sheet, seed)
    wait = (30.0 if commit else 0.0) if wait_s is None else max(0.0, min(wait_s, 55.0))
    ev = st.done.get(key)
    timed_out = False
    if wait and ev is not None:
        try:
            await asyncio.wait_for(ev.wait(), wait)
        except TimeoutError:
            timed_out = True
    # The sketch for this description may still be drawing: show the previous sketch meanwhile
    # (never the stock library face, which rarely matches the description).
    current = st.latest is not None and st.latest_key == key
    out: dict[str, Any] | None = st.latest
    if out is None:
        return {
            "ready": False,
            "reason": "drawing",
            "pending": st.task is not None,
            "seq": st.seq,
            "preview_fields": preview_fields,
        }

    version_id = None
    # a previous sketch is only saved when the caller waited for the new one and it did not come
    if commit and (current or timed_out):
        version_id = await _commit(db, container, actor, sess, out, seed)
    audit.record(
        db,
        actor,
        "sketch.live_render",
        object_type="sketch_version" if version_id else "session",
        object_id=version_id or sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={
            "commit": commit,
            "preview": bool(text),
            "kind": out["kind"],
            "provider": out["provider"],
            "adjust": out["adjust"],
        },
    )
    await audit.commit_with_audit(db)
    return {
        "ready": True,
        "kind": out["kind"],
        "pending": st.task is not None or not current,
        "seq": st.seq,
        "version_id": version_id,
        "lines_b64": out["lines_b64"],
        "sketch_b64": out["sketch_b64"],
        "provider": out["provider"],
        "preview_fields": preview_fields,
    }


async def _commit(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    sess: Any,
    out: dict[str, Any],
    seed: int,
) -> str:
    latest_v = await sketch_repo.latest_version(db, sess.id)
    edit = {"type": "live", "render": out["kind"], "prompt": out["prompt"], "adjust": out["adjust"]}
    if out.get("edits"):
        edit["edits"] = out["edits"]
    if latest_v is not None and latest_v.edit == edit:
        return latest_v.id
    files = container.files
    saved = {}
    for name, kind in (
        ("base_png", "base_master_image"),
        ("master_png", "master_image"),
        ("sketch_png", "sketch_image"),
    ):
        saved[name] = await files.save(
            db, out[name], kind=kind, mime="image/png", session_id=sess.id,
            created_by=actor.user_id,
        )  # fmt: skip
    v = SketchVersion(
        session_id=sess.id,
        parent_id=latest_v.id if latest_v else None,
        master_file_id=saved["master_png"].id,
        base_master_file_id=saved["base_png"].id,
        sketch_file_id=saved["sketch_png"].id,
        mask_file_id=None,
        landmarks=out["landmarks"],
        edit=edit,
        edit_source="voice",
        seed=seed,
        provider_info={
            "type": "live_sketch",
            "render": out["kind"],
            "provider": out["provider"],
            "model": out["model"],
            "landmark_source": out["landmark_source"],
        },
        stability={},
        overlays=[],
        sliders=dict(out["adjust"]),
        created_by_user_id=actor.user_id,
        created_by_role=actor.role,
    )
    await sketch_repo.add_version(db, v)
    container.bus.publish(
        sess.id,
        "version.created",
        {
            "version_id": v.id,
            "parent_id": v.parent_id,
            "sketch_file_id": v.sketch_file_id,
            "edit_source": "voice",
        },
    )
    return v.id
