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
