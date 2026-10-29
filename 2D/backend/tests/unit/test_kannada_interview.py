"""Kannada interview: Gemini hears the finished answer, and the gender always comes through
(no portrait is drawn without it)."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import settings_with
from app.services.interview.engine import _words, next_step, stated_gender
from app.services.interview.live import REASK, STAGE_ORDER

CLOUD_ENV = {"AI_MODE": "cloud", "GEMINI_API_KEY": "gk", "GROQ_API_KEY": "qk", "MAX_RETRIES": "0"}


# ---- words and gender ----------------------------------------------------------------------------


def test_kannada_and_hindi_words_stay_whole() -> None:
    assert _words("ಆ ವ್ಯಕ್ತಿ ಗಂಡಸು.") == ["ಆ", "ವ್ಯಕ್ತಿ", "ಗಂಡಸು"]
    assert _words("वह आदमी था।") == ["वह", "आदमी", "था"]
    assert _words("It's a man.") == ["it", "s", "a", "man"]


@pytest.mark.parametrize(
    ("said", "want"),
    [
        ("ಗಂಡಸು", "male"),
        ("ಅವನು ಹುಡುಗ", "male"),
        ("ಹೆಂಗಸು", "female"),
        ("आदमी", "male"),
        ("औरत", "female"),
        ("a woman", "female"),
        ("ಗಂಡಸು | Man", "male"),
    ],
)
def test_stated_gender(said: str, want: str) -> None:
    hit = stated_gender(said)
    assert hit is not None and hit[0] == want


@pytest.mark.parametrize("said", ["ಪುಡುಷಾವಿ", "a man and a woman", "shy", "", "ಉದ್ದ ಕೂದಲು"])
def test_no_gender_from_garbled_or_mixed_words(said: str) -> None:
    assert stated_gender(said) is None


# ---- the gender question is asked again until it is answered ------------------------------------


def _asked(*keys: str) -> list[dict[str, str]]:
    return [{"field_key": k, "stage": "overall"} for k in keys]


def test_unanswered_gender_is_asked_again_up_to_the_limit() -> None:
    def ask(sheet: dict, *asked: str) -> str:
        return next_step(sheet, _asked(*asked), len(asked), 24, STAGE_ORDER, reask=REASK).field.key

    assert REASK["gender"] == 3
    assert ask({}, "gender") == "gender"
    assert ask({}, "gender", "gender") == "gender"
    assert ask({}, "gender", "gender", "gender") != "gender"
    # an answered gender is never asked again, and without reask nothing is asked twice
    assert ask({"gender": {"value": "male", "confidence": "high"}}, "gender") != "gender"
    assert next_step({}, _asked("gender"), 1, 24, STAGE_ORDER).field.key != "gender"


# ---- speech to text ----------------------------------------------------------------------


def test_gemini_hears_finished_kannada_answers_whisper_the_rest() -> None:
    s = settings_with(**CLOUD_ENV)
    assert s.asr_chain_for("kn") == ["gemini", "groq", "mock"]
    assert s.asr_chain_for("kn", interim=True) == ["groq", "mock"]
    assert s.asr_chain_for("en") == ["groq", "mock"]
    assert (
        settings_with(**{**CLOUD_ENV, "GEMINI_ASR_LANGUAGES": "kn,hi"}).asr_chain_for("hi")[0]
        == "gemini"
    )
    assert settings_with(**{**CLOUD_ENV, "GEMINI_API_KEY": ""}).asr_chain_for("kn") == [
        "groq",
        "mock",
    ]
    assert settings_with(**{**CLOUD_ENV, "AI_MODE": "mock"}).asr_chain_for("kn") == ["mock"]


def _gemini_text(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}
    )


@pytest.mark.asyncio
@respx.mock
async def test_kannada_turn_uses_gemini_then_whisper_when_gemini_is_out_of_quota(container) -> None:  # type: ignore[no-untyped-def]
    from app.providers.registry import build_registry

    reg = build_registry(settings_with(**CLOUD_ENV), container.files, container.db)
    gem = respx.route(host="generativelanguage.googleapis.com").mock(
        return_value=_gemini_text("ಹುಡುಗ ಉದ್ದ\nಕೂದಲಿತ್ತು")
    )
    whisper = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "ಪುಡುಷಾವಿ", "language": "kn"})
    )
    try:
        t = await reg.transcribe(b"RIFF one", "audio/webm;codecs=opus", "kn")
        assert t.provider == "gemini" and t.text == "ಹುಡುಗ ಉದ್ದ ಕೂದಲಿತ್ತು"
        assert not whisper.called
        # the live words while speaking stay on Whisper
        t = await reg.transcribe(b"RIFF two", "audio/webm", "kn", interim=True)
        assert t.provider == "groq" and gem.call_count == 1
        # quota used up: Whisper answers, and Gemini is skipped while it cools down
        gem.mock(return_value=httpx.Response(429))
        t = await reg.transcribe(b"RIFF three", "audio/webm", "kn")
        assert t.provider == "groq" and t.text == "ಪುಡುಷಾವಿ"
        t = await reg.transcribe(b"RIFF four", "audio/webm", "kn")
        assert t.provider == "groq" and gem.call_count == 2
    finally:
        await reg.aclose()
