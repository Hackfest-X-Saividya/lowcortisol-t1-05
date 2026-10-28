"""Deterministic interview state machine. The LLM only phrases questions.

Order: situation -> overall -> face -> marks -> check (contradictions). Fixed priority
within each stage (the order of ``FIELDS``). Filled fields are skipped; a field is never
asked twice except once more during the check stage. Stops after
``INTERVIEW_MAX_QUESTIONS`` with ``done=True, reason="limit"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from app.db.base import iso_utc, utcnow
from app.services.interview.fields import (
    ASKED_FIELDS,
    CARD_CATALOG,
    CONTRADICTIONS,
    FIELD_MAP,
    NOT_REMEMBERED,
    FieldDef,
    field_options,
    filled,
)

STAGE_ORDER = ("situation", "overall", "face", "marks")


@dataclass
class NextStep:
    done: bool
    reason: str = ""
    field: FieldDef | None = None
    stage: str = ""
    options: list[dict[str, str]] = dc_field(default_factory=list)
    context: dict[str, Any] = dc_field(default_factory=dict)


def _matches(sheet: dict[str, Any], key: str, fragment: str) -> bool:
    entry = sheet.get(key) or {}
    value = str(entry.get("value", "")).lower()
    if not value or value == NOT_REMEMBERED:
        return False
    if not fragment:
        return True
    return fragment in value or fragment in str(entry.get("source_text", "")).lower()


def next_step(
    sheet: dict[str, Any],
    asked: list[dict[str, str]],
    question_count: int,
    max_questions: int,
    order: tuple[str, ...] = STAGE_ORDER,
) -> NextStep:
    """``asked`` is a list of ``{"field_key", "stage"}`` for every question already asked."""
    if question_count >= max_questions:
        return NextStep(done=True, reason="limit")
    asked_keys = {a["field_key"] for a in asked if a.get("stage") != "check"}
    asked_check = {a["field_key"] for a in asked if a.get("stage") == "check"}
    for stage in order:
        for f in ASKED_FIELDS:
            if f.stage != stage:
                continue
            if filled(sheet, f.key) or f.key in asked_keys:
                continue
            return NextStep(done=False, field=f, stage=stage, options=field_options(f))
    for key_a, frag_a, key_b, frag_b, re_ask in CONTRADICTIONS:
        if re_ask in asked_check:
            continue
        if _matches(sheet, key_a, frag_a) and _matches(sheet, key_b, frag_b):
            f = FIELD_MAP[re_ask]
            return NextStep(
                done=False,
                field=f,
                stage="check",
                options=field_options(f),
                context={"conflict": [key_a, key_b]},
            )
    return NextStep(done=True, reason="complete")


def apply_answer(
    sheet: dict[str, Any],
    field_key: str,
    *,
    answer_type: str,
    option_id: str | None,
    text_en: str | None,
    source: str,
) -> dict[str, Any]:
    """Return the updated sheet after recording an answer (never deletes, only replaces)."""
    now = iso_utc(utcnow())
    entry: dict[str, Any] | None = None
    if answer_type == "not_remembered" or option_id == NOT_REMEMBERED:
        entry = {
            "value": NOT_REMEMBERED,
            "confidence": NOT_REMEMBERED,
            "source_text": "",
            "source": source,
            "updated_at": now,
        }
    elif answer_type == "option" and option_id:
        card = CARD_CATALOG.get(option_id)
        if card is None or card["field"] != field_key:
            from app.core.errors import ValidationFailed

            raise ValidationFailed(f"Option {option_id} is not valid for {field_key}")
        entry = {
            "value": card["value"],
            "confidence": "high",
            "source_text": card["label"],
            "source": source,
            "updated_at": now,
        }
    elif answer_type in ("text", "voice") and text_en and text_en.strip():
        entry = {
            "value": text_en.strip(),
            "confidence": "medium",
            "source_text": text_en.strip(),
            "source": source,
            "updated_at": now,
        }
    elif answer_type == "skipped":
        entry = None
    if entry is not None:
        sheet = dict(sheet)
        sheet[field_key] = entry
    return sheet


_CONF_RANK = {"not_remembered": 0, "low": 1, "medium": 2, "high": 3}


def merge_extracted(
    sheet: dict[str, Any], extracted: dict[str, Any], source: str
) -> dict[str, Any]:
    """Merge LLM-extracted fields: fill empty fields, upgrade when confidence is higher.
    Answers given directly by the witness (source starts with 'question:') are never
    overridden by a later extraction."""
    now = iso_utc(utcnow())
    out = dict(sheet)
    for key, val in extracted.items():
        if key not in FIELD_MAP or not isinstance(val, dict):
            continue
        value = str(val.get("value", "")).strip()
        if not value:
            continue
        current = out.get(key)
        if current and str(current.get("source", "")).startswith("question:"):
            continue
        new_conf = str(val.get("confidence", "medium"))
        if current and _CONF_RANK.get(str(current.get("confidence")), 0) > _CONF_RANK.get(
            new_conf, 0
        ):
            continue
        out[key] = {
            "value": value,
            "confidence": new_conf,
            "source_text": str(val.get("source_text", ""))[:500],
            "source": source,
            "updated_at": now,
        }
    return out
