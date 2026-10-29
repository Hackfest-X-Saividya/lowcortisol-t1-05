"""Groq: Whisper speech-to-text and OpenAI-compatible chat completions (backup LLM).

Endpoints (OpenAI-compatible, see https://console.groq.com/docs):
  POST {GROQ_BASE_URL}/audio/transcriptions   multipart: file, model, language,
                                              response_format=verbose_json
  POST {GROQ_BASE_URL}/chat/completions       JSON with response_format json_object
"""

from __future__ import annotations

import base64
import json
import time

import httpx

from app.config import Settings
from app.core.errors import ProviderError
from app.providers.base import LLMRequest, LLMResult, Segment, Transcript, VisionRequest
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
        backups = [m.strip() for m in settings.groq_llm_backup_models.split(",")]
        ordered = [settings.groq_llm_model, settings.groq_llm_fallback_model, *backups]
        self.models = list(dict.fromkeys(m for m in ordered if m))
        self.reasoning_effort = settings.groq_reasoning_effort
        self._limited: dict[str, float] = {}  # model -> monotonic time its rate limit clears

    async def complete_json(self, req: LLMRequest) -> LLMResult:
        """Groq rate limits are per model: on a 429 the next model is tried at once, and the
        limited model is skipped for a minute, so a busy interview never stalls."""
        now = time.monotonic()
        ready = [m for m in self.models if self._limited.get(m, 0.0) <= now] or self.models[-1:]
        last: ProviderError | None = None
        for model in ready:
            try:
                return await self._complete(req, model)
            except ProviderError as exc:
                last = exc
                bad_json = "json_validate_failed" in exc.message or "validate JSON" in exc.message
                if (exc.status == 400 and bad_json) or "returned" in exc.message:
                    continue  # this model wrote invalid JSON: the next one may not
                if exc.status != 429:
                    raise
                self._limited[model] = time.monotonic() + 60.0
        assert last is not None
        raise last

    async def _complete(self, req: LLMRequest, model: str) -> LLMResult:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": req.system + "\nRespond with a single JSON object."},
                {"role": "user", "content": req.user},
            ],
            "temperature": req.temperature,
            "response_format": {"type": "json_object"},
        }
        if "gpt-oss" in model and self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort  # "low" keeps a live turn ~1 s
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
            data = json.loads(_strip_think(content))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Groq LLM returned unexpected payload: {exc}", provider=self.name)
        if not isinstance(data, dict):
            raise ProviderError("Groq LLM returned non-object JSON", provider=self.name)
        return LLMResult(data=data, provider=self.name, model=model, raw_text=content)


def _strip_think(text: str) -> str:
    """Qwen can put a <think>...</think> block before the JSON answer."""
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def _image_part(data: bytes) -> dict[str, object]:
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    return {"type": "image_url", "image_url": {"url": url}}


JSON_ONLY = "\nRespond with a single JSON object."


class GroqVision(GroqClientMixin):
    """Image understanding (Qwen 3.8 on Groq), JSON out: checks a sketch against a description."""

    name = "groq"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.groq_vision_model

    async def vision_json(self, req: VisionRequest) -> LLMResult:
        content: list[dict[str, object]] = [{"type": "text", "text": req.user}]
        content += [_image_part(img) for img in req.images]
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": req.system + JSON_ONLY},
                {"role": "user", "content": content},
            ],
            "temperature": req.temperature,
            "max_completion_tokens": req.max_tokens,
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
            text = resp.json()["choices"][0]["message"]["content"] or ""
            data = json.loads(_strip_think(text))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Groq vision: unexpected payload: {exc}", provider=self.name)
        if not isinstance(data, dict):
            raise ProviderError("Groq vision returned non-object JSON", provider=self.name)
        return LLMResult(data=data, provider=self.name, model=self.model, raw_text=text)
