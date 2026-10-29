"""Prompts for the live suspect sketch: what the image model is asked to draw, and the check.

- ``describe``: the whole description, one labelled sentence per feature ("Hair: long curly."),
  so the image model knows which feature each detail belongs to (unlabelled lists such as
  "long curly, thick, short, very fat" were drawn wrongly).
- ``llm_prompt_request``: a Groq model rewrites that description as a precise drawing prompt
  (the style text is always appended by the code, never left to the model).
- ``edit_lines`` / ``edit_instruction``: later sketches EDIT the previous one (FLUX.2 reference
  image), naming only what the witness added or changed, so it stays the same person.
- ``check_request`` / ``fix_lines``: the vision model compares a finished sketch with the
  description; clear mismatches are fixed with one more edit.

Only what the witness said goes into a prompt; nothing is invented for undescribed features.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.providers.base import LLMRequest, VisionRequest

# feature key -> how it is named in a prompt (drawing order)
FEATURES: tuple[tuple[str, str], ...] = (
    ("gender", "gender"),
    ("age_range", "age"),
    ("build", "build"),
    ("skin_tone", "complexion"),
    ("face_shape", "face shape"),
    ("hair", "hair"),
    ("eyes", "eyes"),
    ("brows", "eyebrows"),
    ("nose", "nose"),
    ("mouth", "mouth and lips"),
    ("jaw", "jaw and chin"),
    ("ears", "ears"),
    ("facial_hair", "facial hair"),
    ("headwear", "headwear"),
    ("eyewear", "eyewear"),
    ("face_cover", "face covering"),
    ("scars", "scars"),
    ("moles", "moles"),
    ("other_marks", "other distinctive marks"),
)
FEATURE_KEYS = tuple(k for k, _ in FEATURES)
LABELS = dict(FEATURES)
NONE_WORDS = (
    "no", "none", "nothing", "not noticed", "none noticed", "clean shaven", "clean-shaven",
)  # fmt: skip

PENCIL_STYLE = (
    "Style: a realistic hand-drawn police forensic composite sketch by an experienced sketch "
    "artist, graphite pencil on white paper. An ordinary real person, not a model: natural "
    "asymmetry, accurate anatomy and proportions, precise detail in the eyes, eyelids, nose, "
    "lips and hairline, tonal shading built from fine pencil hatching and smudged graphite, "
    "visible pencil strokes and paper grain. Head and shoulders, straight front view, eyes "
    "looking at the viewer, neutral expression, mouth closed. Plain white background, black "
    "and white only, no colour, no text, no signature, no border."
)
PHOTO_STYLE = (
    "Style: a realistic, unretouched police identification photograph of an ordinary person, "
    "not a model: natural skin with pores, blemishes and slight asymmetry, accurate facial "
    "proportions, head and shoulders, straight front view, eyes looking at the camera, neutral "
    "expression, mouth closed, flat even light, plain light grey background, no text."
)
# put first: image models weigh the start of a prompt most (said only at the end, "front view"
# was often ignored and the head drawn turned)
FRONT = (
    "Straight front view, like a passport photo: the face looks directly into the camera, "
    "head not turned, both eyes and both ears equally visible."
)
PENCIL_LEAD = f"{FRONT} Graphite pencil drawing on white paper, a police forensic composite sketch."
PHOTO_LEAD = f"{FRONT} Unretouched police identification photograph."
KEEP = (
    "Keep everything else exactly as it is in image 0: the same person and identity, every "
    "other feature unchanged in shape, size and position, the same drawing style and shading, "
    "the same framing, pose and background."
)


def value(sheet: dict[str, Any], key: str) -> str:
    v = sheet.get(key)
    s = str(v.get("value", "")).strip() if isinstance(v, dict) else ""
    return "" if s in ("", "not_remembered") else s[:120]


def snapshot(sheet: dict[str, Any]) -> dict[str, str]:
    """The face features the witness has described."""
    return {k: value(sheet, k) for k in FEATURE_KEYS if value(sheet, k)}


def is_none(v: str) -> bool:
    return v.strip().lower() in NONE_WORDS


def style_text(style: str) -> str:
    return PHOTO_STYLE if style == "photo" else PENCIL_STYLE


def _who(snap: dict[str, str]) -> str:
    g = snap.get("gender", "").lower()
    if any(w in g for w in ("female", "woman", "lady", "girl")):
        return "woman"
    if any(w in g for w in ("male", "man", "boy", "gent")):
        return "man"
    return "person"


def describe(snap: dict[str, str], style: str = "pencil") -> str:
    """Full prompt for a new sketch: one labelled sentence per described feature."""
    kind = "identification photograph" if style == "photo" else "forensic composite sketch"
    who = {"man": "man (male)", "woman": "woman (female)"}.get(_who(snap), "person")
    head = f"{FRONT} A police {kind} of one Indian {who}"
    if snap.get("age_range"):
        head += f", age {snap['age_range']}"
    lines = [head + "."]
    for key, label in FEATURES:
        if key in ("gender", "age_range") or key not in snap:
            continue
        v = snap[key]
        lines.append(f"No {label}." if is_none(v) else f"{label.capitalize()}: {v}.")
    lines.append(style_text(style))
    return " ".join(lines)


# ---- the LLM writes the drawing prompt -----------------------------------------------------


class SketchPromptOut(BaseModel):
    prompt: str = Field(min_length=20, max_length=1500)


def llm_prompt_request(snap: dict[str, str], style: str = "pencil") -> LLMRequest:
    medium = "identification photograph" if style == "photo" else "forensic pencil sketch"
    system = (
        "You write the image-generation prompt for a police " + medium + " from a witness's "
        "description. Describe one Indian person seen straight from the front, head and "
        "shoulders. Include EVERY described feature, each named with the feature it belongs "
        "to, turned into precise visual detail an artist can draw, the most distinctive "
        "features (build, face shape, hair, headwear, marks) first (e.g. 'hair: long curly' -> "
        "'long, tightly curled black hair reaching the shoulders'; 'build: very fat' -> 'heavy, "
        "fleshy face with full cheeks and a double chin'). Keep the witness's meaning exactly: "
        "never add, soften or contradict a detail, never invent features that were not "
        "described (do not mention them at all), never add accessories that were not "
        "described. Do not describe the drawing style. Plain sentences, at most 140 words. "
        'Return {"prompt": "..."}.'
    )
    payload = {"description": snap}
    return LLMRequest(
        task="sketch_prompt",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=SketchPromptOut,
        temperature=0.2,
    )


def subject(snap: dict[str, str]) -> str:
    """Who is drawn, from the witness's own words (never left to the LLM)."""
    build = snap.get("build", "")
    words = (
        f"a {build} Indian {_who(snap)}"
        if build and not is_none(build)
        else f"an Indian {_who(snap)}"
    )
    if snap.get("age_range"):
        words += f", age {snap['age_range']}"
    if snap.get("skin_tone"):
        words += f", {snap['skin_tone']} complexion"
    return f"Subject: {words}."


def checklist(snap: dict[str, str]) -> str:
    """Every described feature in a few words, early in the prompt (image models drop
    details that only come late in a long prompt)."""
    items = [
        f"no {LABELS[k]}" if is_none(v) else f"{LABELS[k]} {v}"
        for k, v in snap.items()
        if k not in ("gender", "age_range", "build", "skin_tone") and k in LABELS
    ]
    return f"Must show: {'; '.join(items)}." if items else ""


def with_style(text: str, style: str, snap: dict[str, str] | None = None) -> str:
    lead = PHOTO_LEAD if style == "photo" else PENCIL_LEAD
    who = f" {subject(snap)} {checklist(snap)}".rstrip() if snap else ""
    return f"{lead}{who} {text.strip()} {style_text(style)}"


# ---- edits: change only what the witness changed -------------------------------------------


def edit_lines(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """What the witness added or changed since the previous sketch, one line per feature."""
    out: list[str] = []
    for key, label in FEATURES:
        a, b = old.get(key, ""), new.get(key, "")
        if a == b or not b:
            continue
        if is_none(b):
            if a and not is_none(a):
                out.append(f"remove the {label} completely")
        elif not a or is_none(a):
            out.append(f"{label}: draw it exactly as described - {b}")
        else:
            out.append(f"{label}: change it from '{a}' to '{b}'")
    return out


def edit_instruction(lines: list[str], style: str = "pencil") -> str:
    medium = "photograph" if style == "photo" else "pencil sketch"
    return (
        f"Image 0 is a police composite {medium} of a person. Edit image 0 and make only "
        f"these changes the witness asked for: {'; '.join(lines)}. {KEEP}"
    )


# ---- check: does the sketch show what was described? ---------------------------------------


class Mismatch(BaseModel):
    field: str
    expected: str = ""
    seen: str = ""


class SketchCheckOut(BaseModel):
    matches: bool = True
    mismatches: list[Mismatch] = Field(default_factory=list)


def check_request(image: bytes, snap: dict[str, str]) -> VisionRequest:
    system = (
        "You are the supervising forensic artist checking a police composite sketch against "
        "the witness's description before the witness sees it. Look carefully. For each "
        "described feature decide whether the image clearly shows it. Report only clear "
        "contradictions of described features (described 'thick moustache' but clean shaven; "
        "'long curly hair' but short straight hair; 'cap' but bare head; 'very fat' but a thin "
        "face; 'woman' but a man). Ignore features that were not described, small differences "
        "of degree and the drawing style. Use field 'framing' if the image is not exactly one "
        "face seen from the front. "
        'Return {"matches": bool, "mismatches": [{"field": feature key, "expected": the '
        'described value, "seen": what the image shows}]} with at most 4 mismatches.'
    )
    user = "Witness description (feature key -> value):\n" + json.dumps(snap, ensure_ascii=False)
    return VisionRequest(
        task="sketch_check",
        system=system,
        user=user,
        images=[image],
        payload={"description": snap},
        schema=SketchCheckOut,
        max_tokens=800,
    )


def fix_lines(data: dict[str, Any], snap: dict[str, str]) -> list[str]:
    out: list[str] = []
    for m in (data.get("mismatches") or [])[:4]:
        key = str(m.get("field", ""))
        if key == "framing":
            out.append("show exactly one person's head and shoulders, straight from the front")
        elif key in snap:
            label, want = LABELS.get(key, key), snap[key]
            out.append(f"remove the {label} completely" if is_none(want) else f"{label}: {want}")
    return out
