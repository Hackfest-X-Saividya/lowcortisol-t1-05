"""Groq: Whisper speech-to-text and OpenAI-compatible chat completions (backup LLM).

Endpoints (OpenAI-compatible, see https://console.groq.com/docs):
  POST {GROQ_BASE_URL}/audio/transcriptions   multipart: file, model, language,
                                              response_format=verbose_json
  POST {GROQ_BASE_URL}/chat/completions       JSON with response_format json_object
"""

from __future__ import annotations

import json

import httpx

from app.config import Settings
from app.core.errors import ProviderError
from app.providers.base import LLMRequest, LLMResult, Segment, Transcript
from app.providers.http import request_with_retries
from app.services.storage import AUDIO_EXT


class GroqClientMixin:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = settings.groq_base_url.rstrip("/")
        self.max_retries = settings.max_retries
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.http_timeout_s,
            headers={"Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}"},
        )

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()


class GroqASR(GroqClientMixin):
    name = "groq"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.groq_asr_model

    async def transcribe(self, audio: bytes, mime: str, language: str) -> Transcript:
        ext = AUDIO_EXT.get(mime, "webm")
        files = {"file": (f"audio.{ext}", audio, mime)}
        data = {
            "model": self.model,
            "language": language,
            "response_format": "verbose_json",
            "temperature": "0",
        }
        resp = await request_with_retries(
            self._client,
            "POST",
            f"{self.base_url}/audio/transcriptions",
            provider=self.name,
            max_retries=self.max_retries,
            files=files,
            data=data,
        )
        try:
            body = resp.json()
        except json.JSONDecodeError:
            raise ProviderError("Groq ASR returned non-JSON", provider=self.name)
        segments = []
        for seg in body.get("segments") or []:
            conf = None
            if "avg_logprob" in seg:
                # avg_logprob is <= 0; map to a 0..1 confidence estimate
                try:
                    conf = max(0.0, min(1.0, 1.0 + float(seg["avg_logprob"])))
                except (TypeError, ValueError):
                    conf = None
            segments.append(
                Segment(
                    start=float(seg.get("start", 0.0)),
                    end=float(seg.get("end", 0.0)),
                    text=str(seg.get("text", "")).strip(),
                    confidence=conf,
                )
            )
        return Transcript(
            text=str(body.get("text", "")).strip(),
            language=str(body.get("language") or language),
            segments=segments,
            provider=self.name,
            model=self.model,
        )


class GroqLLM(GroqClientMixin):
    name = "groq"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.groq_llm_model

    async def complete_json(self, req: LLMRequest) -> LLMResult:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": req.system + "\nRespond with a single JSON object."},
                {"role": "user", "content": req.user},
            ],
            "temperature": req.temperature,
            "response_format": {"type": "json_object"},
        }
        resp = await request_with_retries(
            self._client,
            "POST",
            f"{self.base_url}/chat/completions",
            provider=self.name,
            max_retries=self.max_retries,
            json=body,
        )
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Groq LLM returned unexpected payload: {exc}", provider=self.name)
        if not isinstance(data, dict):
            raise ProviderError("Groq LLM returned non-object JSON", provider=self.name)
        return LLMResult(data=data, provider=self.name, model=self.model, raw_text=content)
