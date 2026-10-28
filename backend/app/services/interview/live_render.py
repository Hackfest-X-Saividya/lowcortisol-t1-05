"""Realistic live sketch for the voice interview.

Two kinds of drawing, so the witness never waits on an image service:

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

from app.container import Container
from app.core import audit
from app.core.logging import get_logger
from app.core.security import Principal
from app.db.models.sketch import SketchVersion
from app.db.repositories import sketch as sketch_repo
from app.db.repositories import statements as repo
from app.providers.base import ImageRequest
from app.services import cases as case_service
from app.services.interview import engine, live_warp, prompts
from app.services.interview.fields import FIELD_MAP
from app.services.interview.live import ADJUST_KEY, apply_adjustments
from app.services.sketch.generation import build_prompt
from app.services.sketch.landmarks import landmarks_to_json, load_template
from app.services.sketch.overlays import apply_overlays
from app.services.sketch.render import decode_png, encode_png, line_drawing, pencil_sketch

log = get_logger(__name__)

FACE_FIELDS = {
    "gender", "age_range", "build", "skin_tone", "face_shape", "hair", "eyes", "brows", "nose",
    "mouth", "jaw", "ears", "facial_hair", "headwear", "eyewear", "face_cover", "scars", "moles",
    "other_marks",
}  # fmt: skip
EXTRA_PROMPT_FIELDS = ("eyewear", "headwear", "face_cover", "scars", "moles", "other_marks", "ears")
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


def has_face_details(sheet: dict[str, Any]) -> bool:
    return any(_val(sheet, k) for k in FACE_FIELDS)


def realistic_prompt(sheet: dict[str, Any]) -> str:
    info = build_prompt(sheet)
    p = info.prompt.replace(
        "frontal passport-style photograph", "realistic frontal passport photograph, sharp focus"
    )
    extra = [_val(sheet, k)[:60] for k in EXTRA_PROMPT_FIELDS if _val(sheet, k)]
    extra = [e for e in extra if e.lower() not in ("no", "none", "nothing")]
    tail = (", " + ", ".join(extra)) if extra else ""
    return f"{p}{tail}, Indian, natural skin texture, documentary photo"


def _adjust(sheet: dict[str, Any]) -> dict[str, float]:
    return {
        k: round(float(v), 3)
        for k, v in (sheet.get(ADJUST_KEY) or {}).items()
        if abs(float(v)) > 1e-3
    }


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


def _layers(
    container: Container,
    photo: np.ndarray,
    lm: np.ndarray | None,
    adjust: dict[str, float],
    overlays: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    settings = container.settings
    warped = photo
    if lm is not None and adjust:
        warped, lm = live_warp.warp(photo, lm, adjust)
    if lm is not None and overlays:
        try:
            warped, _ = apply_overlays(settings, warped, lm, overlays)
        except Exception:  # noqa: BLE001
            log.warning("live overlay failed")
    return warped, line_drawing(warped, settings), pencil_sketch(warped, settings), lm


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
    final_key = hashlib.sha256(json.dumps([photo_key, adjust], sort_keys=True).encode()).hexdigest()
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
        res = await asyncio.wait_for(
            container.providers.generate_image(
                ImageRequest(
                    prompt=prompt, negative_prompt=NEGATIVE, width=SIZE, height=SIZE, seed=seed
                )
            ),
            PORTRAIT_TIMEOUT_S,
        )
        photo = decode_png(res.png)
        if photo.shape[:2] != (SIZE, SIZE):
            photo = cv2.resize(photo, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
        lm = None
        source = "template"
        if res.provider == "mock" or container.settings.mock_mode:
            lm = load_template().landmarks.copy()
        else:
            try:
                faces = await asyncio.to_thread(container.landmarker.detect, photo)
                if faces:
                    lm, source = faces[0], "mediapipe"
            except Exception:  # noqa: BLE001
                lm = None
        photo_entry = {"photo": photo, "lm": lm, "provider": res.provider, "model": res.model,
                       "source": source}  # fmt: skip
        _remember("photo:" + photo_key, photo_entry)
    lm0 = photo_entry["lm"]
    warped, lines, sketch, lm = await asyncio.to_thread(
        _layers, container, photo_entry["photo"], None if lm0 is None else lm0.copy(), adjust, []
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


_live: dict[str, _Live] = {}


def _state(session_id: str) -> _Live:
    st = _live.get(session_id)
    if st is None:
        st = _live[session_id] = _Live()
        while len(_live) > 64:
            _live.pop(next(iter(_live)))
    return st


async def _worker(container: Container, session_id: str) -> None:
    st = _state(session_id)
    while st.want is not None:
        key, sheet, seed = st.want
        st.want = None
        st.running_key = key
        try:
            out = await portrait(container, sheet, seed)
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
        sheet = engine.merge_extracted(sheet, fields, source="preview")
        if data.get("adjustments"):
            sheet[ADJUST_KEY] = apply_adjustments(sheet, list(data["adjustments"]))
        preview_fields = sorted(fields)
    if not has_face_details(sheet):
        return {"ready": False, "reason": "not_enough_detail", "preview_fields": preview_fields}

    seed = session_seed(sess.id)
    key = _request(container, sess.id, sheet, seed)
    st = _state(sess.id)
    wait = (30.0 if commit else 0.0) if wait_s is None else max(0.0, min(wait_s, 55.0))
    ev = st.done.get(key)
    if wait and ev is not None:
        try:
            await asyncio.wait_for(ev.wait(), wait)
        except TimeoutError:
            pass
    out: dict[str, Any] | None = st.latest if st.latest_key == key else None
    if out is None:
        out = await asyncio.to_thread(instant, container, sheet, seed)
    if out is None:
        return {
            "ready": False,
            "reason": "drawing",
            "pending": st.task is not None,
            "seq": st.seq,
            "preview_fields": preview_fields,
        }

    version_id = None
    if commit:
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
        "pending": st.task is not None and out["kind"] != "portrait",
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
