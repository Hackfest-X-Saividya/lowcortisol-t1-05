"""Deterministic interview state machine. The LLM only phrases questions.

Order: situation -> overall -> face -> marks -> check (contradictions). Fixed priority
within each stage (the order of ``FIELDS``). Filled fields are skipped; a field is never
asked twice except once more during the check stage, or when the caller allows a re-ask
(``reask``) because the answer did not come through. Stops after
``INTERVIEW_MAX_QUESTIONS`` with ``done=True, reason="limit"``.
"""

from __future__ import annotations

import re
from collections import Counter
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
    reask: dict[str, int] | None = None,
) -> NextStep:
    """``asked`` is a list of ``{"field_key", "stage"}`` for every question already asked.
    A field is asked once, or up to ``reask[key]`` times while its answer is still missing."""
    if question_count >= max_questions:
        return NextStep(done=True, reason="limit")
    times_asked = Counter(a["field_key"] for a in asked if a.get("stage") != "check")
    asked_check = {a["field_key"] for a in asked if a.get("stage") == "check"}
    for stage in order:
        for f in ASKED_FIELDS:
            if f.stage != stage:
                continue
            if filled(sheet, f.key) or times_asked[f.key] >= (reask or {}).get(f.key, 1):
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


def _words(text: str) -> list[str]:
    # Indic vowel signs and viramas are not \w, so they are added (Devanagari to Sinhala,
    # without the danda) or "ಗಂಡಸು" would split into "ಗ", "ಡಸ".
    return re.findall(r"(?:[^\W_]|[ऀ-ॣ०-෿])+", text.lower())


# Plain words for "man" / "woman" in the three languages: a gender answer that the speech
# recognition got right (or a tap on the Man / Woman buttons) is recorded even when the LLM
# extraction misses it, because no portrait is drawn until the gender is known.
_GENDER_WORDS = {
    "male": {
        "man", "male", "boy", "guy", "gentleman",
        "ಗಂಡಸು", "ಗಂಡು", "ಪುರುಷ", "ಪುರುಷರು", "ಹುಡುಗ", "ಹುಡುಗನು",
        "आदमी", "पुरुष", "मर्द", "लड़का",
    },
    "female": {
        "woman", "female", "girl", "lady",
        "ಹೆಂಗಸು", "ಹೆಣ್ಣು", "ಮಹಿಳೆ", "ಹುಡುಗಿ", "ಸ್ತ್ರೀ",
        "औरत", "महिला", "स्त्री", "लड़की",
    },
}  # fmt: skip


def stated_gender(said: str) -> tuple[str, str] | None:
    """(value, word) when the words name exactly one gender, else None."""
    words = _words(said)
    found = {g: w for g, vocab in _GENDER_WORDS.items() for w in words if w in vocab}
    if len(found) != 1:
        return None
    return next(iter(found.items()))


def grounded(source_text: str, said: str) -> bool:
    """True when the quoted words come from what the witness just said (not an LLM echo of
    something known from earlier turns)."""
    quote, heard = _words(source_text), set(_words(said))
    if not quote or not heard:
        return False
    return sum(w in heard for w in quote) / len(quote) >= 0.6


_UNKNOWN_RE = re.compile(
    r"\b(?:don'?t|do not|didn'?t|did not|can'?t|cannot|couldn'?t|could not)\s+"
    r"(?:remember|recall|know|see|notice)|\bno idea\b|\bnot sure\b|\bforg[eo]t|not remembered"
    r"|ನೆನಪಿಲ್ಲ|ಗೊತ್ತಿಲ್ಲ|याद नहीं|पता नहीं",
    re.IGNORECASE,
)


def _unknown_allowed(key: str, answered: str | None, said: str) -> bool:
    """'not_remembered' only for the question just asked, and only when the witness said so
    (or pressed "don't remember", which sends no words). The LLM tends to mark every field it
    did not hear as not remembered, which would stop the interview asking about them."""
    if not said:
        return True  # caller gave no words to check against
    if key != answered:
        return False
    return not _words(said) or bool(_UNKNOWN_RE.search(said))


def merge_extracted(
    sheet: dict[str, Any],
    extracted: dict[str, Any],
    source: str,
    said: str = "",
    answered: str | None = None,
) -> dict[str, Any]:
    """Merge LLM-extracted fields: fill empty fields, upgrade when confidence is higher.

    An earlier value (a direct answer, or one with higher confidence) is kept against a later
    extraction, because the LLM re-reads everything known so far and may echo or guess. The
    witness's newest words win, though: a value whose source_text is grounded in ``said``
    (this turn's words) replaces the old one, so "it's a man" corrects an earlier "female".
    ``answered`` is the field the witness was just asked about (see ``_unknown_allowed``)."""
    now = iso_utc(utcnow())
    out = dict(sheet)
    for key, val in extracted.items():
        if key not in FIELD_MAP or not isinstance(val, dict):
            continue
        value = str(val.get("value", "")).strip()
        if not value:
            continue
        if value == NOT_REMEMBERED and not _unknown_allowed(key, answered, said):
            continue
        current = out.get(key)
        new_conf = str(val.get("confidence", "medium"))
        old_value = str((current or {}).get("value", "")).strip().lower()
        correction = (
            bool(current)
            and value != NOT_REMEMBERED
            and value.lower() != old_value
            and grounded(str(val.get("source_text", "")), said)
        )
        if current and not correction:
            if str(current.get("source", "")).startswith("question:"):
                continue
            if _CONF_RANK.get(str(current.get("confidence")), 0) > _CONF_RANK.get(new_conf, 0):
                continue
        out[key] = {
            "value": value,
            "confidence": new_conf,
            "source_text": str(val.get("source_text", ""))[:500],
            "source": source,
            "updated_at": now,
        }
    return out
