from __future__ import annotations

import pytest

from app.core.errors import ValidationFailed
from app.services.interview import engine
from app.services.interview.fields import ASKED_FIELDS, NOT_REMEMBERED
from app.services.interview.leading_check import rule_check

LEADING = [
    "Did he have a beard?",
    "Was he dark?",
    "Didn't he have a scar?",
    "Was it a knife?",
    "Wasn't he tall?",
    "Did she wear glasses?",
    "Was he wearing a cap?",
    "Did he have long hair?",
    "Was his nose hooked?",
    "Were his eyebrows thick?",
    "Did the man have a moustache?",
    "He had a square jaw, right?",
    "Was the person bald?",
    "Didn't the man wear a mask?",
    "Was he young?",
    "The other witness said he was fat. Was he?",
    "Did he have thin lips?",
]

SAFE = [
    "What do you remember about his nose?",
    "What was the lighting like at that time?",
    "About how far away was the person from you?",
    "How would you describe the person's hair?",
    "What do you remember about the person's eyes?",
    "Can you describe the shape of the face?",
    "What, if anything, was the person wearing on their head?",
    "What do you remember about the person's build?",
    "For about how long could you see the person?",
    "From which side did you see the person's face?",
    "What do you remember about any marks on the face?",
    "How would you describe the person's skin tone?",
    "What was the person's jaw or chin like?",
    "What do you remember about the eyebrows?",
    "Tell me about the person's clothing.",
    "What do you remember about the person's facial hair, if any?",
]


@pytest.mark.parametrize("q", LEADING)
def test_leading_questions_flagged(q: str) -> None:
    assert rule_check(q) is not None, q


@pytest.mark.parametrize("q", SAFE)
def test_safe_questions_pass(q: str) -> None:
    assert rule_check(q) is None, q


def test_order_situation_overall_face_marks() -> None:
    sheet: dict = {}
    asked: list[dict[str, str]] = []
    stages: list[str] = []
    for _ in range(40):
        step = engine.next_step(sheet, asked, len(asked), 100)
        if step.done:
            break
        assert step.field is not None
        stages.append(step.stage)
        asked.append({"field_key": step.field.key, "stage": step.stage})
    assert step.done and step.reason == "complete"
    order = [s for i, s in enumerate(stages) if i == 0 or stages[i - 1] != s]
    assert order == ["situation", "overall", "face", "marks"]
    assert len(asked) == len(ASKED_FIELDS)


def test_skips_filled_fields_and_never_repeats() -> None:
    sheet = {"lighting": {"value": "dim"}, "gender": {"value": "male"}}
    asked: list[dict[str, str]] = []
    keys = []
    for _ in range(40):
        step = engine.next_step(sheet, asked, len(asked), 100)
        if step.done:
            break
        assert step.field is not None
        keys.append(step.field.key)
        asked.append({"field_key": step.field.key, "stage": step.stage})
    assert "lighting" not in keys and "gender" not in keys
    assert len(keys) == len(set(keys))


def test_limit_stops_after_max_questions() -> None:
    step = engine.next_step({}, [{"field_key": "x", "stage": "situation"}] * 12, 12, 12)
    assert step.done and step.reason == "limit"
    step = engine.next_step({}, [], 11, 12)
    assert not step.done


def test_not_remembered_counts_as_filled_and_options_include_it() -> None:
    step = engine.next_step({}, [], 0, 12)
    assert step.field is not None
    assert any(o["id"] == NOT_REMEMBERED for o in step.options)
    sheet = engine.apply_answer(
        {},
        step.field.key,
        answer_type="not_remembered",
        option_id=None,
        text_en=None,
        source="question:1",
    )
    assert sheet[step.field.key]["value"] == NOT_REMEMBERED
    asked = [{"field_key": step.field.key, "stage": step.stage}]
    nxt = engine.next_step(sheet, asked, 1, 12)
    assert nxt.field is not None and nxt.field.key != step.field.key


def test_option_answer_and_merge_rules() -> None:
    sheet = engine.apply_answer(
        {},
        "nose",
        answer_type="option",
        option_id="nose_hooked",
        text_en=None,
        source="question:q1",
    )
    assert sheet["nose"]["value"] == "hooked" and sheet["nose"]["confidence"] == "high"
    with pytest.raises(ValidationFailed):
        engine.apply_answer(
            {}, "nose", answer_type="option", option_id="eyes_large", text_en=None, source="q"
        )
    merged = engine.merge_extracted(
        sheet,
        {
            "nose": {"value": "long", "confidence": "high", "source_text": "long nose"},
            "eyes": {"value": "large", "confidence": "low", "source_text": "big eyes"},
        },
        source="statement:s1",
    )
    assert merged["nose"]["value"] == "hooked"  # witness answers win
    assert merged["eyes"]["value"] == "large"
    merged2 = engine.merge_extracted(
        merged,
        {"eyes": {"value": "small", "confidence": "high", "source_text": ""}},
        "statement:s2",
    )
    assert merged2["eyes"]["value"] == "small"  # higher confidence upgrades
    merged3 = engine.merge_extracted(
        merged2,
        {"eyes": {"value": "round", "confidence": "low", "source_text": ""}},
        "statement:s3",
    )
    assert merged3["eyes"]["value"] == "small"  # lower confidence does not downgrade


def test_contradiction_check_stage() -> None:
    sheet = {
        "gender": {"value": "female", "confidence": "high"},
        "facial_hair": {
            "value": "full_beard",
            "confidence": "medium",
            "source_text": "he had a beard",
        },
    }
    asked = [{"field_key": f.key, "stage": f.stage} for f in ASKED_FIELDS]
    step = engine.next_step(sheet, asked, len(asked), 100)
    assert not step.done and step.stage == "check" and step.field is not None
    assert step.field.key == "gender"
    asked.append({"field_key": "gender", "stage": "check"})
    assert engine.next_step(sheet, asked, len(asked), 100).done
