"""Live sketch prompts (labelled features, edits, checks) and the Groq model fallback."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import settings_with
from app.providers.groq import GroqLLM, GroqVision
from app.services.interview import portrait as pt
from app.services.interview import prompts

CLOUD_ENV = {"AI_MODE": "cloud", "GROQ_API_KEY": "qk", "MAX_RETRIES": "0"}
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _sheet(**kw: str) -> dict[str, dict[str, str]]:
    return {k: {"value": v} for k, v in kw.items()}


def test_describe_labels_every_feature_and_invents_nothing() -> None:
    snap = pt.snapshot(
        _sheet(
            gender="male", age_range="25-30", hair="long curly", build="very fat",
            headwear="cap", eyewear="none", nose="not_remembered",
        )
    )  # fmt: skip
    text = pt.describe(snap)
    assert "one Indian man (male), age 25-30." in text
    assert text.startswith("Straight front view")  # image models weigh the start most
    assert "Hair: long curly." in text and "Build: very fat." in text
    assert "Headwear: cap." in text and "No eyewear." in text
    assert "nose" not in text.split("Style:")[0].lower()  # not remembered -> not drawn
    assert "pencil" in text and "not a model" in text


def test_edit_lines_name_only_what_changed() -> None:
    old = {"gender": "male", "hair": "short", "eyewear": "round spectacles"}
    new = {"gender": "male", "hair": "long curly", "eyewear": "none", "moles": "on left cheek"}
    lines = pt.edit_lines(old, new)
    assert lines == [
        "hair: change it from 'short' to 'long curly'",
        "remove the eyewear completely",
        "moles: draw it exactly as described - on left cheek",
    ]
    assert pt.edit_lines(old, old) == []
    assert "Keep everything else exactly" in pt.edit_instruction(lines)


def test_fix_lines_from_check() -> None:
    snap = {"hair": "long curly", "headwear": "cap", "eyewear": "none"}
    data = {
        "matches": False,
        "mismatches": [
            {"field": "hair", "expected": "long curly", "seen": "short straight"},
            {"field": "eyewear", "expected": "none", "seen": "glasses"},
            {"field": "tattoos", "expected": "", "seen": ""},  # not described -> ignored
            {"field": "framing"},
        ],
    }
    assert pt.fix_lines(data, snap) == [
        "hair: long curly",
        "remove the eyewear completely",
        "show exactly one person's head and shoulders, straight from the front",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_groq_llm_moves_on_after_invalid_json_and_rate_limits() -> None:
    s = settings_with(**CLOUD_ENV)
    llm = GroqLLM(s)
    assert llm.models == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
    bad_json = {"error": {"message": "Failed to validate JSON.", "code": "json_validate_failed"}}
    ok = {"choices": [{"message": {"content": '<think>x</think>{"translation": "hello"}'}}]}
    route = respx.post(GROQ_URL).mock(
        side_effect=[
            httpx.Response(400, json=bad_json),
            httpx.Response(429, json={"error": {"message": "tokens per day"}}),
            httpx.Response(200, json=ok),
        ]
    )
    res = await llm.complete_json(prompts.translate("x", "hi", "en"))
    await llm.aclose()
    assert res.data == {"translation": "hello"} and res.model == "qwen/qwen3.8-27b"
    models = [json.loads(c.request.content)["model"] for c in route.calls]
    assert models == llm.models


@pytest.mark.asyncio
@respx.mock
async def test_groq_vision_sends_the_image() -> None:
    s = settings_with(**CLOUD_ENV)
    vision = GroqVision(s)
    route = respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": '{"matches": true, "mismatches": []}'}}]}
        )
    )
    res = await vision.vision_json(pt.check_request(b"\xff\xd8jpeg", {"hair": "long curly"}))
    await vision.aclose()
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "qwen/qwen3.8-27b"
    parts = body["messages"][1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert res.data["matches"] is True
