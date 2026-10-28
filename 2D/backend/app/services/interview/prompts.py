"""LLM task definitions: system prompts, user prompt builders and response schemas.

``PROMPT_VERSION`` is stored with every job result so outputs can be traced to the prompt
text that produced them.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.providers.base import LLMRequest
from app.services.interview.fields import FIELDS
from app.services.scene.schema import Scene

PROMPT_VERSION = "2026-10-28.1"

_LANG_NAMES = {"hi": "Hindi", "kn": "Kannada", "en": "English"}

_COMMON_RULES = (
    "You help police officers build a suspect sketch from a witness account. "
    "Never invent details that the witness did not say. Never use crime-related words in "
    "any image prompt. Output valid JSON only, with exactly the keys requested."
)


# ---- response schemas ---------------------------------------------------------------------


class TranslateOut(BaseModel):
    translation: str


class FeatureValue(BaseModel):
    value: str = ""
    confidence: Literal["high", "medium", "low", "not_remembered"] = "medium"
    source_text: str = ""


class FeatureSheetOut(BaseModel):
    fields: dict[str, FeatureValue] = Field(default_factory=dict)


class QuestionOut(BaseModel):
    question_en: str


class LeadingOut(BaseModel):
    leading: bool
    reason: str = ""


class HandleMove(BaseModel):
    handle: str
    dx: float = 0.0
    dy: float = 0.0


class EditSpecOut(BaseModel):
    region: str = ""
    type: Literal["geometric", "overlay", "inpaint", "none"] = "none"
    param: str = ""
    amount: float | None = None
    direction: int = 1
    overlay_id: str = ""
    overlay_params: dict[str, Any] = Field(default_factory=dict)
    prompt: str = ""
    symmetric: bool = True
    needs_choice: bool = False
    message: str = ""


class SceneOut(BaseModel):
    scene: Scene


class PatchOut(BaseModel):
    patch: list[dict[str, Any]] = Field(default_factory=list)
    explanation: str = ""


# ---- builders ---------------------------------------------------------------------------------


def _fields_description() -> str:
    return "\n".join(f"- {f.key}: {f.description}" for f in FIELDS)


def translate(text: str, source_lang: str, target_lang: str) -> LLMRequest:
    system = (
        f"{_COMMON_RULES} Translate faithfully from {_LANG_NAMES.get(source_lang, source_lang)} "
        f"to {_LANG_NAMES.get(target_lang, target_lang)}. Keep names, numbers and hedges "
        "('maybe', 'I think') exactly. Do not add or remove information."
    )
    user = json.dumps(
        {"text": text, "source": source_lang, "target": target_lang}, ensure_ascii=False
    )
    return LLMRequest(
        task="translate",
        system=system,
        user=user,
        payload={"text": text, "source_lang": source_lang, "target_lang": target_lang},
        schema=TranslateOut,
        strict_schema=True,
    )


def extract_feature_sheet(
    statement_original: str,
    statement_english: str,
    language: str,
    existing: dict[str, Any] | None = None,
) -> LLMRequest:
    system = (
        f"{_COMMON_RULES} Extract a feature sheet from the witness statement. Fill only "
        "fields the witness actually mentioned. For each field give value (short English "
        "phrase), confidence (high|medium|low|not_remembered) and source_text (the exact "
        "words from the statement that support it). Fields:\n"
        + _fields_description()
        + '\nReturn {"fields": {field_key: {value, confidence, source_text}}}.'
    )
    payload = {
        "statement_original": statement_original,
        "statement_english": statement_english,
        "language": language,
        "existing": existing or {},
    }
    return LLMRequest(
        task="extract_feature_sheet",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=FeatureSheetOut,
    )


def phrase_question(
    field_key: str,
    field_description: str,
    known: dict[str, Any],
    options: list[dict[str, str]],
    previous: list[str],
    reason: str = "missing",
) -> LLMRequest:
    system = (
        f"{_COMMON_RULES} Write ONE open, non-leading interview question in simple English "
        "for the given field. Never suggest a specific value, never ask a yes/no question "
        "that names a feature value, never mention what other witnesses said. Prefer "
        "'What do you remember about...' phrasing. Return {\"question_en\": ...}."
    )
    payload = {
        "field_key": field_key,
        "field_description": field_description,
        "known": known,
        "options": [o["label"] for o in options],
        "previous_questions": previous,
        "reason": reason,
    }
    return LLMRequest(
        task="phrase_question",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=QuestionOut,
        strict_schema=True,
    )


def leading_check(question_en: str, field_key: str) -> LLMRequest:
    system = (
        f"{_COMMON_RULES} Decide whether the interview question is leading: it suggests a "
        "specific answer, names a feature value, assumes a fact not given by the witness, "
        'or is a yes/no question about a specific value. Return {"leading": bool, '
        '"reason": short string}.'
    )
    payload = {"question_en": question_en, "field_key": field_key}
    return LLMRequest(
        task="leading_check",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=LeadingOut,
        strict_schema=True,
    )


def route_edit(
    utterance_original: str,
    utterance_en: str,
    language: str,
    locks: list[str],
    regions: list[str],
    params: dict[str, list[str]],
    overlays: list[str],
) -> LLMRequest:
    system = (
        f"{_COMMON_RULES} Convert the witness's sketch edit request into a structured edit. "
        "type=geometric for shape changes (param is one of the listed slider params for the "
        "region; amount: 'a little/thoda/swalpa'=0.05, 'more/aur/innu'=0.10, "
        "'a lot/bahut/tumba'=0.15; direction +1 bigger/wider/longer/higher, -1 smaller/"
        "narrower/shorter/lower; if no amount word, set needs_choice=true and amount=null). "
        "type=overlay for accessories and marks (overlay_id from the list, overlay_params "
        "may include position: left_cheek|right_cheek|forehead|chin and size). "
        "type=inpaint for hair, skin or texture changes (prompt is a short description). "
        "If the target region is locked, set type=none and message explaining it is locked. "
        "Return the JSON object with keys region, type, param, amount, direction, overlay_id, "
        "overlay_params, prompt, symmetric, needs_choice, message."
    )
    payload = {
        "utterance_original": utterance_original,
        "utterance_en": utterance_en,
        "language": language,
        "locked_regions": locks,
        "regions": regions,
        "params": params,
        "overlays": overlays,
    }
    return LLMRequest(
        task="route_edit",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=EditSpecOut,
    )


def build_scene(
    description_en: str,
    description_original: str,
    templates: dict[str, Any],
    feature_sheet: dict[str, Any],
) -> LLMRequest:
    system = (
        f"{_COMMON_RULES} Build a crime-scene layout JSON from the witness description. "
        "Choose the closest template (shop|room|street|junction) and adapt it: keep the "
        "room size, place objects the witness mentioned (type from the template object "
        "types), place people (roles: witness, suspect, other) with positions in metres "
        "[x, y, z] on the floor (y=0), facing_deg, and list evidence markers and ordered "
        'events. Return {"scene": {...}} matching the template structure.'
    )
    payload = {
        "description_en": description_en,
        "description_original": description_original,
        "templates": templates,
        "feature_sheet_scene": feature_sheet,
    }
    return LLMRequest(
        task="build_scene",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=SceneOut,
    )


def scene_command(utterance_original: str, utterance_en: str, scene: dict[str, Any]) -> LLMRequest:
    system = (
        f"{_COMMON_RULES} Convert the spoken scene command into an RFC 6902 JSON Patch "
        "against the given scene JSON. Use paths like /objects/0/pos or /people/1/facing_deg. "
        "Never modify objects with locked=true. 'a little'=0.5 m, 'more'=1 m, 'a lot'=2 m. "
        'Return {"patch": [...], "explanation": short string}.'
    )
    payload = {
        "utterance_original": utterance_original,
        "utterance_en": utterance_en,
        "scene": scene,
    }
    return LLMRequest(
        task="scene_command",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=PatchOut,
    )


# ---- live interview turn (one call per witness turn) -------------------------------------

SKETCH_PARAMS = (
    "face_width",
    "jaw_width",
    "face_length",
    "eye_size",
    "eye_spacing",
    "nose_length",
    "nose_width",
    "lip_fullness",
    "brow_height",
)


class Adjustment(BaseModel):
    param: str
    amount: float = Field(default=0.05, ge=-0.3, le=0.3)


class TurnOut(BaseModel):
    english: str = ""
    fields: dict[str, FeatureValue] = Field(default_factory=dict)
    adjustments: list[Adjustment] = Field(default_factory=list)
    visual_edits: list[str] = Field(default_factory=list)
    reply_local: str = ""
    reply_en: str = ""
    ask_field: str = ""


def interview_turn(
    utterance: str,
    language: str,
    last_question: dict[str, Any] | None,
    sheet: dict[str, Any],
    next_fields: list[dict[str, str]],
    history: list[dict[str, str]],
) -> LLMRequest:
    lang_name = _LANG_NAMES.get(language, language)
    system = (
        "You are a calm, experienced police sketch artist interviewing a nervous witness, "
        f"speaking {lang_name}. You draw while you listen. For each witness turn do ALL of:\n"
        "1. english: translate the witness's words to English faithfully.\n"
        "2. fields: extract only details the witness actually said, using these keys:\n"
        + _fields_description()
        + "\n   value = short English phrase in the witness's sense (e.g. 'long, slightly hooked');"
        " confidence = high|medium|low|not_remembered; source_text = the witness's own words."
        " If the witness says they do not remember the field you last asked, set that field to"
        " value 'not_remembered', confidence 'not_remembered'.\n"
        "3. adjustments: ONLY if witness_words in THIS turn ask to change the drawing (e.g. 'make the jaw a bit wider',"
        " 'nose longer', 'eyes closer'), list {param, amount} with param one of "
        + ", ".join(SKETCH_PARAMS)
        + "; amount signed: a little=0.05, more=0.10, a lot=0.15 (negative = smaller/narrower/"
        "shorter/lower/closer). face_width = fuller/chubbier/rounder face (+) or thinner/slimmer (-).\n"
        "   visual_edits: for EVERY appearance detail of the face, head or neck that the witness states in THIS"
        " turn (hair, beard, scars, glasses, tattoos, skin marks, expression, shape, anything visible),"
        " one short English phrase describing how the person looks, e.g. 'long hair reaching the shoulders',"
        " 'a scar across the left cheek'. Empty list if the words say nothing about appearance; never"
        " include places, times, clothing worn below the neck, or anything the witness did not say.\n"
        f"4. reply_local: in {lang_name}, a very short neutral acknowledgement (at most five words,"
        " never repeating feature details back) and then exactly ONE open, non-leading question about"
        " the FIRST entry in next_fields that your step 2 did not fill. Ask it like a sketch artist:"
        " direct and simple, e.g. 'What was the nose like?'. Never suggest a value, never ask a yes/no"
        " question that names a feature, never give options or multiple choice. If next_fields is"
        " empty, ask whether anything in the sketch looks different from the person.\n"
        "5. reply_en: the same reply in English. ask_field: the field key you asked about, or 'review'.\n"
        "Return one JSON object with keys english, fields, adjustments, visual_edits, reply_local, reply_en, ask_field."
    )
    known = {
        k: v.get("value") for k, v in sheet.items() if isinstance(v, dict) and not k.startswith("_")
    }
    payload = {
        "witness_words": utterance,
        "language": language,
        "last_question": last_question,
        "known_so_far": known,
        "next_fields": next_fields,
    }
    return LLMRequest(
        task="interview_turn",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=TurnOut,
        temperature=0.2,
    )


class QuickFieldsOut(BaseModel):
    fields: dict[str, FeatureValue] = Field(default_factory=dict)
    adjustments: list[Adjustment] = Field(default_factory=list)


QUICK_FACE_FIELDS = (
    "gender", "age_range", "build", "skin_tone", "face_shape", "hair", "eyes", "brows", "nose",
    "mouth", "jaw", "ears", "facial_hair", "headwear", "eyewear", "face_cover", "scars", "moles",
    "other_marks",
)  # fmt: skip


def quick_fields(witness_words: str, sheet: dict[str, Any]) -> LLMRequest:
    """Fast extraction from words still being spoken (live sketch preview). Face fields only,
    and only the ones the words mention, so the answer stays tiny (fast, few tokens)."""
    keys = "\n".join(f"- {f.key}: {f.description}" for f in FIELDS if f.key in QUICK_FACE_FIELDS)
    system = (
        "Extract face details from a witness's words (any language, possibly cut off mid-"
        "sentence) for a police sketch. Use only what the words say; never guess. Allowed keys:\n"
        + keys
        + "\nInclude ONLY keys the words actually mention; leave every other key out. Each value"
        ' is an object: {"value": short English phrase, "confidence": "high"|"medium"|"low",'
        ' "source_text": the witness\'s words}. If the words ask to change the drawing, add'
        " adjustments {param, amount} with param one of "
        + ", ".join(SKETCH_PARAMS)
        + " (a little=0.05, more=0.10, a lot=0.15; negative = smaller/narrower/shorter/lower)."
        ' Example: {"fields": {"nose": {"value": "long", "confidence": "high", "source_text":'
        ' "a long nose"}}, "adjustments": [{"param": "jaw_width", "amount": 0.05}]}.'
        ' Nothing about the face -> {"fields": {}, "adjustments": []}. Return JSON only.'
    )
    known = {
        k: v.get("value") for k, v in sheet.items() if isinstance(v, dict) and not k.startswith("_")
    }
    payload = {"witness_words": witness_words, "known_so_far": known}
    return LLMRequest(
        task="quick_fields",
        system=system,
        user=json.dumps(payload, ensure_ascii=False),
        payload=payload,
        schema=QuickFieldsOut,
        temperature=0.1,
    )
