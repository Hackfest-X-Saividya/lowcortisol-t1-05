"""Provider clients against respx mocks: retries, fallback, both Cloudflare formats, cache."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest
import respx

from app.config import settings_with
from app.core.errors import ProviderError
from app.providers.base import ImageRequest, LLMRequest
from app.providers.cloudflare import CloudflareImageGen
from app.providers.groq import GroqASR, GroqLLM
from app.providers.http import request_with_retries
from app.providers.registry import build_registry
from app.services.interview import prompts

CLOUD_ENV = {
    "AI_MODE": "cloud",
    "GEMINI_API_KEY": "gk",
    "GROQ_API_KEY": "qk",
    "CLOUDFLARE_ACCOUNT_ID": "acc",
    "CLOUDFLARE_API_TOKEN": "tok",
    "MAX_RETRIES": "2",
}


async def _no_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
@respx.mock
async def test_retry_on_429_respects_retry_after_then_succeeds() -> None:
    route = respx.post("https://example.test/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with httpx.AsyncClient() as c:
        r = await request_with_retries(
            c, "POST", "https://example.test/x", provider="t", max_retries=3, sleep=_no_sleep
        )
    assert r.status_code == 200 and route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_retry_exhaustion_raises_provider_error() -> None:
    respx.post("https://example.test/x").mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as c:
        with pytest.raises(ProviderError) as ei:
            await request_with_retries(
                c, "POST", "https://example.test/x", provider="t", max_retries=1, sleep=_no_sleep
            )
    assert ei.value.retryable and ei.value.status == 500


@pytest.mark.asyncio
@respx.mock
async def test_non_retryable_4xx_raises_immediately() -> None:
    route = respx.post("https://example.test/x").mock(return_value=httpx.Response(401))
    async with httpx.AsyncClient() as c:
        with pytest.raises(ProviderError):
            await request_with_retries(
                c, "POST", "https://example.test/x", provider="t", max_retries=3, sleep=_no_sleep
            )
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_groq_asr_verbose_json_segments() -> None:
    s = settings_with(**CLOUD_ENV)
    respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(
        return_value=httpx.Response(
            200,
            json={
                "text": "नमस्ते",
                "language": "hi",
                "segments": [{"start": 0.0, "end": 1.2, "text": "नमस्ते", "avg_logprob": -0.1}],
            },
        )
    )
    asr = GroqASR(s)
    t = await asr.transcribe(b"RIFF....WAVE", "audio/wav", "hi")
    await asr.aclose()
    assert t.text == "नमस्ते" and t.language == "hi" and t.provider == "groq"
    assert len(t.segments) == 1 and t.segments[0].confidence == pytest.approx(0.9)


@pytest.mark.asyncio
@respx.mock
async def test_groq_llm_json_mode() -> None:
    s = settings_with(**CLOUD_ENV)
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"translation": "hello"})}}]}
        )
    )
    llm = GroqLLM(s)
    res = await llm.complete_json(prompts.translate("नमस्ते", "hi", "en"))
    await llm.aclose()
    assert res.data == {"translation": "hello"} and res.model == s.groq_llm_model


@pytest.mark.asyncio
@respx.mock
async def test_cloudflare_both_response_formats() -> None:
    s = settings_with(**CLOUD_ENV)
    url = f"https://api.cloudflare.com/client/v4/accounts/acc/ai/run/{s.cf_image_model}"
    png = b"\x89PNG\r\n\x1a\nfakepng"
    respx.post(url).mock(
        side_effect=[
            httpx.Response(200, content=png, headers={"Content-Type": "image/png"}),
            httpx.Response(
                200, json={"result": {"image": base64.b64encode(png).decode()}, "success": True}
            ),
        ]
    )
    gen = CloudflareImageGen(s)
    a = await gen.generate(ImageRequest(prompt="p", width=512, height=512, seed=1))
    b = await gen.generate(ImageRequest(prompt="p2", width=512, height=512, seed=2))
    await gen.aclose()
    assert a.png == png and b.png == png and a.provider == "cloudflare"


@pytest.mark.asyncio
@respx.mock
async def test_cloudflare_sends_auth_and_fields() -> None:
    s = settings_with(**CLOUD_ENV)
    url = f"https://api.cloudflare.com/client/v4/accounts/acc/ai/run/{s.cf_image_model}"
    route = respx.post(url).mock(
        return_value=httpx.Response(200, content=b"img", headers={"Content-Type": "image/png"})
    )
    gen = CloudflareImageGen(s)
    await gen.generate(
        ImageRequest(prompt="p", negative_prompt="n", width=1024, height=1024, seed=7, num_steps=4)
    )
    await gen.aclose()
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer tok"
    body = json.loads(req.content)
    assert body == {
        "prompt": "p",
        "negative_prompt": "n",
        "width": 1024,
        "height": 1024,
        "seed": 7,
        "num_steps": 4,
    }


@pytest.mark.asyncio
@respx.mock
async def test_gemini_json_mode_and_fallback_to_groq_then_mock(container) -> None:  # type: ignore[no-untyped-def]
    s = settings_with(**CLOUD_ENV)
    reg = build_registry(s, container.files, container.db)
    assert s.llm_chain == ["gemini", "groq", "mock"]
    gem = respx.route(host="generativelanguage.googleapis.com").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    groq = respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"translation": "from groq"})}}]},
        )
    )
    # patch sleeps so retries are instant
    import asyncio

    orig = asyncio.sleep

    async def fast(_: float) -> None:
        await orig(0)

    asyncio.sleep = fast  # type: ignore[assignment]
    try:
        res = await reg.llm_json(prompts.translate("x", "hi", "en"))
        assert res.provider == "groq" and res.data["translation"] == "from groq"
        assert gem.called and groq.called
        # cache hit: no new groq call
        res2 = await reg.llm_json(prompts.translate("x", "hi", "en"))
        assert res2.cached and res2.provider == "groq" and groq.call_count == 1
        # both fail -> mock serves
        groq.mock(return_value=httpx.Response(500))
        res3 = await reg.llm_json(prompts.translate("y", "hi", "en"))
        assert res3.provider == "mock"
    finally:
        asyncio.sleep = orig  # type: ignore[assignment]
        await reg.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_llm_validation_retry_then_fallback(container) -> None:  # type: ignore[no-untyped-def]
    s = settings_with(**{**CLOUD_ENV, "GEMINI_API_KEY": "", "LLM_PRIMARY": "groq"})
    reg = build_registry(s, container.files, container.db)
    assert s.llm_chain == ["groq", "mock"]
    groq = respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"wrong": 1})}}]}
        )
    )
    res = await reg.llm_json(prompts.translate("x", "hi", "en"))
    await reg.aclose()
    assert groq.call_count == 2  # one retry with the validation error
    assert res.provider == "mock"
    second = json.loads(groq.calls[1].request.content)
    assert "failed validation" in second["messages"][1]["content"]


@pytest.mark.asyncio
@respx.mock
async def test_image_fallback_cloudflare_to_pollinations_and_cache(container) -> None:  # type: ignore[no-untyped-def]
    s = settings_with(**CLOUD_ENV)
    reg = build_registry(s, container.files, container.db)
    cf = respx.route(host="api.cloudflare.com").mock(return_value=httpx.Response(500))
    poll = respx.route(host="image.pollinations.ai").mock(
        return_value=httpx.Response(
            200, content=b"\x89PNGpoll", headers={"Content-Type": "image/jpeg"}
        )
    )
    import asyncio

    orig = asyncio.sleep

    async def fast(_: float) -> None:
        await orig(0)

    asyncio.sleep = fast  # type: ignore[assignment]
    try:
        res = await reg.generate_image(ImageRequest(prompt="face", seed=3))
        assert res.provider == "pollinations" and res.png == b"\x89PNGpoll"
        assert cf.called and poll.call_count == 1
        res2 = await reg.generate_image(ImageRequest(prompt="face", seed=3))
        assert res2.cached and poll.call_count == 1
    finally:
        asyncio.sleep = orig  # type: ignore[assignment]
        await reg.aclose()


@pytest.mark.asyncio
async def test_inpaint_unavailable_message(container) -> None:  # type: ignore[no-untyped-def]
    s = settings_with(**{**CLOUD_ENV, "CLOUDFLARE_ACCOUNT_ID": "", "CLOUDFLARE_API_TOKEN": ""})
    reg = build_registry(s, container.files, container.db)
    from app.providers.base import InpaintRequest

    with pytest.raises(ProviderError, match="online image editing"):
        await reg.inpaint(InpaintRequest(image_png=b"", mask_png=b"", prompt="x"))
    await reg.aclose()


def test_cloud_mode_ack_false_forces_mock() -> None:
    s = settings_with(**{**CLOUD_ENV, "CLOUD_MODE_ACK": "false"})
    assert s.mock_mode and s.llm_chain == ["mock"] and s.image_chain == ["mock"]
    assert s.data_mode == "local_mock"


def test_mock_asr_marker_selects_fixture() -> None:
    import asyncio

    from app.providers.mock.asr import MockASR

    t = asyncio.run(MockASR().transcribe(b"RIFF nishaan-mock:edit_command", "audio/wav", "hi"))
    assert "जबड़ा" in t.text
    t2 = asyncio.run(MockASR().transcribe(b"RIFF", "audio/wav", "kn"))
    assert t2.language == "kn" and t2.segments


def test_llm_request_payload_shapes() -> None:
    req: LLMRequest = prompts.route_edit("x", "y", "hi", [], ["jaw"], {"jaw": ["jaw_width"]}, [])
    data: dict[str, Any] = json.loads(req.user)
    assert data["utterance_original"] == "x" and req.schema is prompts.EditSpecOut
