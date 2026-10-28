"""Google Gemini via the official google-genai SDK: JSON-mode LLM and text-to-speech.

Model names come from ``GEMINI_MODEL`` / ``GEMINI_TTS_MODEL``; verify them in Google AI
Studio because names change. The SDK talks to ``https://generativelanguage.googleapis.com``
over httpx, which is what ``respx`` mocks in the unit tests.

Latency rules (the interview is live):
- "thinking" is switched off by default (``GEMINI_THINKING_BUDGET=0``); if a model rejects
  that option the call is retried once without it and the model is remembered.
- a 429 (quota exhausted) is never retried here: the registry falls back to the next
  provider at once and puts Gemini in a cool-down instead of waiting on backoff.
"""

from __future__ import annotations

import asyncio
import io
import json
import random
import struct
from typing import Any

from app.config import Settings
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.providers.base import LLMRequest, LLMResult

log = get_logger(__name__)

_NO_THINKING_CONFIG: set[str] = set()  # models that reject thinking_config


class GeminiLLM:
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        from google import genai

        self.model = settings.gemini_model
        self.thinking_budget = settings.gemini_thinking_budget
        self.max_retries = min(settings.max_retries, 1)
        self.timeout_ms = int(settings.http_timeout_s * 1000)
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_options={"timeout": self.timeout_ms},
        )

    def _config(self, req: LLMRequest, thinking: bool) -> Any:
        from google.genai import types

        config: dict[str, Any] = {
            "system_instruction": req.system,
            "response_mime_type": "application/json",
            "temperature": req.temperature,
        }
        if req.schema is not None and req.strict_schema:
            config["response_schema"] = req.schema
        if thinking and self.thinking_budget >= 0 and self.model not in _NO_THINKING_CONFIG:
            config["thinking_config"] = types.ThinkingConfig(thinking_budget=self.thinking_budget)
        return types.GenerateContentConfig(**config)

    async def complete_json(self, req: LLMRequest) -> LLMResult:
        from google.genai import errors as genai_errors

        attempt = 0
        thinking = True
        while True:
            try:
                resp = await self._client.aio.models.generate_content(
                    model=self.model, contents=req.user, config=self._config(req, thinking)
                )
                text = resp.text or ""
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ProviderError("Gemini returned non-object JSON", provider=self.name)
                return LLMResult(data=data, provider=self.name, model=self.model, raw_text=text)
            except genai_errors.APIError as exc:
                code = int(getattr(exc, "code", None) or 0)
                if code == 400 and thinking and "thinking" in str(exc).lower():
                    _NO_THINKING_CONFIG.add(self.model)
                    thinking = False
                    continue
                if code == 429:
                    raise ProviderError(
                        "Gemini quota exhausted", provider=self.name, retryable=True, status=429
                    )
                retryable = code in (500, 502, 503, 504)
                if not retryable or attempt >= self.max_retries:
                    raise ProviderError(
                        f"Gemini API error {code}",
                        provider=self.name,
                        retryable=retryable,
                        status=code or None,
                    )
                await asyncio.sleep(0.6 + random.uniform(0, 0.3))
                attempt += 1
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Gemini returned invalid JSON: {exc}", provider=self.name)
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001  network / SDK errors
                if attempt >= self.max_retries:
                    raise ProviderError(
                        f"Gemini call failed: {type(exc).__name__}",
                        provider=self.name,
                        retryable=True,
                    )
                await asyncio.sleep(0.6)
                attempt += 1

    async def aclose(self) -> None:
        return None


def pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    buf.write(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE")
    buf.write(
        b"fmt "
        + struct.pack(
            "<IHHIIHH", 16, 1, channels, rate, rate * channels * width, channels * width, width * 8
        )
    )
    buf.write(b"data" + struct.pack("<I", len(pcm)) + pcm)
    return buf.getvalue()


class GeminiTTS:
    """Speak a short line in the witness's language (used when the browser has no voice)."""

    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        from google import genai

        self.model = settings.gemini_tts_model
        self.voice = settings.gemini_tts_voice
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_options={"timeout": int(settings.http_timeout_s * 1000)},
        )

    async def synthesize(self, text: str, language: str) -> tuple[bytes, str]:
        from google.genai import errors as genai_errors
        from google.genai import types

        cfg = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                )
            ),
        )
        prompt = f"Say calmly and slowly, in a gentle voice: {text}"
        try:
            resp = await self._client.aio.models.generate_content(
                model=self.model, contents=prompt, config=cfg
            )
        except genai_errors.APIError as exc:
            code = int(getattr(exc, "code", None) or 0)
            raise ProviderError(
                f"Gemini TTS error {code}",
                provider=self.name,
                retryable=code == 429,
                status=code or None,
            )
        part: Any = None
        try:
            r: Any = resp
            part = r.candidates[0].content.parts[0].inline_data
        except (AttributeError, IndexError, TypeError):
            part = None
        if part is None or not part.data:
            raise ProviderError("Gemini TTS returned no audio", provider=self.name)
        data: bytes = part.data if isinstance(part.data, bytes) else bytes(part.data)
        mime = str(part.mime_type or "").lower()
        if "wav" in mime or data[:4] == b"RIFF":
            return data, "audio/wav"
        rate = 24000
        if "rate=" in mime:
            try:
                rate = int(mime.split("rate=")[1].split(";")[0])
            except ValueError:
                pass
        return pcm_to_wav(data, rate=rate), "audio/wav"

    async def aclose(self) -> None:
        return None


class GeminiVision:
    """Analyse an image with a structured-JSON response (used for floor-plan extraction)."""

    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        from google import genai

        self.model = settings.gemini_model
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_options={"timeout": 60_000},
        )

    async def analyze(self, image_bytes: bytes, mime_type: str, prompt: str) -> dict[str, Any]:
        """Send an image + text prompt to Gemini and return parsed JSON."""
        from google.genai import errors as genai_errors
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        )
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt,
        ]
        try:
            resp = await self._client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            code = int(getattr(exc, "code", None) or 0)
            raise ProviderError(f"Gemini vision error {code}", provider=self.name, status=code or None)
        text = resp.text or ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Gemini vision returned invalid JSON: {exc}", provider=self.name)
        if not isinstance(data, dict):
            raise ProviderError("Gemini vision returned non-object JSON", provider=self.name)
        return data

    async def aclose(self) -> None:
        return None
