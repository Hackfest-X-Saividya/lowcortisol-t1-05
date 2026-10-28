"""Leading-question detection: a deterministic rule check plus an LLM check.

Rule: a yes/no question (starts with did/was/is/does/... or a negative tag such as
"didn't he") that names a specific feature value is leading. Also flagged: questions that
quote other people ("the other witness said") or assume a value ("how big was his beard"
when a beard was never mentioned is handled by the LLM check).
"""

from __future__ import annotations

import re

from app.providers.base import LLMRequest
from app.services.interview.fields import LEADING_VALUE_KEYWORDS

_YES_NO_START = re.compile(
    r"^\s*(did|didn'?t|does|doesn'?t|do|don'?t|was|wasn'?t|were|weren'?t|is|isn'?t|are|"
    r"aren'?t|has|hasn'?t|had|hadn'?t|could|couldn'?t|would|wouldn'?t)\b",
    re.IGNORECASE,
)
_NEGATIVE_TAG = re.compile(
    r"\b(didn'?t|wasn'?t|weren'?t|isn'?t|hadn'?t|doesn'?t)\s+(he|she|"
    r"they|it|the\s+\w+)\b",
    re.IGNORECASE,
)
_SUGGESTIVE = re.compile(
    r"\b(the other witness|others? said|we (?:think|believe|know)|i think he|i think she|"
    r"as you said he had|you must have seen|surely|obviously|right\?|correct\?|isn'?t it\?)",
    re.IGNORECASE,
)
_RIGHT_TAG = re.compile(
    r",\s*(right|correct|wasn'?t (?:he|she|it)|didn'?t (?:he|she))\s*\?\s*$", re.IGNORECASE
)

# Generic feature values that make a yes/no question leading regardless of the field.
GENERIC_VALUES: tuple[str, ...] = (
    "beard",
    "moustache",
    "mustache",
    "scar",
    "mole",
    "tattoo",
    "glasses",
    "spectacles",
    "sunglasses",
    "cap",
    "turban",
    "helmet",
    "mask",
    "dark",
    "fair",
    "tall",
    "short",
    "thin",
    "fat",
    "heavy",
    "slim",
    "bald",
    "long hair",
    "short hair",
    "curly",
    "grey",
    "big nose",
    "long nose",
    "broad nose",
    "hooked",
    "thick eyebrows",
    "thin lips",
    "full lips",
    "square jaw",
    "round face",
    "long face",
    "young",
    "old",
    "blue",
    "red",
    "black",
    "white",
    "knife",
    "gun",
    "wide",
    "narrow",
    "large",
    "small",
    "big",
)


def _all_values() -> set[str]:
    vals: set[str] = set(GENERIC_VALUES)
    for kws in LEADING_VALUE_KEYWORDS.values():
        vals.update(k.strip().lower() for k in kws if len(k.strip()) > 2)
    return vals


_VALUES = _all_values()


def rule_check(question_en: str, field_key: str = "") -> str | None:
    """Return a reason string when the question is leading, else None."""
    q = question_en.strip()
    low = f" {q.lower()} "
    if _SUGGESTIVE.search(q):
        return "suggests an answer or cites others"
    if _RIGHT_TAG.search(q):
        return "tag question asking for confirmation"
    names_value = any(f" {v} " in low or f" {v}?" in low or f" {v}," in low for v in _VALUES)
    if _NEGATIVE_TAG.search(q) and names_value:
        return "negative yes/no question naming a value"
    if _YES_NO_START.match(q) and names_value:
        return "yes/no question naming a specific feature value"
    if _YES_NO_START.match(q) and field_key:
        kws = LEADING_VALUE_KEYWORDS.get(field_key, ())
        if any(k.strip().lower() in low for k in kws):
            return f"yes/no question naming a {field_key} value"
    return None


def llm_request(question_en: str, field_key: str) -> LLMRequest:
    from app.services.interview import prompts

    return prompts.leading_check(question_en, field_key)


def safe_template(field_label: str) -> str:
    return f"What do you remember about the person's {field_label.lower()}?"
