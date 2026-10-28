"""One tiny request per configured cloud provider. Prints only ``ok`` or ``failed: <reason>``.

Run:  python scripts/smoke_test_providers.py

- Gemini / Groq LLM: a two-word JSON reply.
- Groq Whisper: a 2-second silent WAV clip.
- Cloudflare Workers AI: one 512 px image.
- Pollinations (no key): one 512 px image.
Keys are read from backend/.env and never printed.
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.providers.base import ImageRequest, LLMRequest  # noqa: E402


def silent_wav(seconds: float = 2.0, rate: int = 16000) -> bytes:
    n = int(rate * seconds)
    data = b"\x00\x00" * n
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


def _llm_request() -> LLMRequest:
    return LLMRequest(
        task="smoke",
        system="Reply with JSON only.",
        user='Return {"reply": "<two words>"} and nothing else.',
        payload={},
        schema=None,
        temperature=0.0,
    )


async def run() -> int:
    settings = get_settings()
    if settings.ai_mode == "mock":
        print("AI_MODE=mock: nothing to test (all providers are mocked)")
        return 0
    if not settings.cloud_mode_ack:
        print("CLOUD_MODE_ACK=false: cloud providers disabled")
        return 0
    failures = 0

    async def report(name: str, coro) -> None:  # type: ignore[no-untyped-def]
        nonlocal failures
        try:
            await asyncio.wait_for(coro, timeout=max(settings.http_timeout_s, 90))
            print(f"{name}: ok")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            reason = str(exc).replace(settings.gemini_api_key.get_secret_value() or "\0", "***")
            reason = reason.replace(settings.groq_api_key.get_secret_value() or "\0", "***")
            reason = reason.replace(settings.cloudflare_api_token.get_secret_value() or "\0", "***")
            print(f"{name}: failed: {type(exc).__name__}: {reason[:200]}")

    if settings.gemini_configured:
        from app.providers.gemini import GeminiLLM

        async def gemini() -> None:
            res = await GeminiLLM(settings).complete_json(_llm_request())
            if not isinstance(res.data, dict):
                raise RuntimeError("non-JSON reply")

        await report(f"gemini ({settings.gemini_model})", gemini())
    else:
        print("gemini: skipped (no key)")

    if settings.groq_configured:
        from app.providers.groq import GroqASR, GroqLLM

        async def groq_llm() -> None:
            llm = GroqLLM(settings)
            try:
                res = await llm.complete_json(_llm_request())
                json.dumps(res.data)
            finally:
                await llm.aclose()

        async def groq_asr() -> None:
            asr = GroqASR(settings)
            try:
                await asr.transcribe(silent_wav(), "audio/wav", "en")
            finally:
                await asr.aclose()

        await report(f"groq llm ({settings.groq_llm_model})", groq_llm())
        await report(f"groq whisper ({settings.groq_asr_model})", groq_asr())
    else:
        print("groq: skipped (no key)")

    if settings.cloudflare_configured:
        from app.providers.cloudflare import CloudflareImageGen

        async def cf() -> None:
            gen = CloudflareImageGen(settings)
            try:
                res = await gen.generate(
                    ImageRequest(prompt="a plain grey circle", width=512, height=512, seed=1)
                )
                if len(res.png) < 1000:
                    raise RuntimeError("image too small")
            finally:
                await gen.aclose()

        await report(f"cloudflare image ({settings.cf_image_model})", cf())
    else:
        print("cloudflare: skipped (no key)")

    from app.providers.pollinations import PollinationsImageGen

    async def poll() -> None:
        gen = PollinationsImageGen(settings)
        try:
            res = await gen.generate(
                ImageRequest(prompt="a plain grey circle", width=512, height=512, seed=1)
            )
            if len(res.png) < 1000:
                raise RuntimeError("image too small")
        finally:
            await gen.aclose()

    await report("pollinations", poll())
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
