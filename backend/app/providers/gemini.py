"""Google Gemini LLM via the official google-genai SDK (JSON output mode).

Model name comes from ``GEMINI_MODEL``; verify it in Google AI Studio because names change.
The SDK talks to ``https://generativelanguage.googleapis.com`` over httpx, which is what
``respx`` mocks in the unit tests.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

from app.config import Settings
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.providers.base import LLMRequest, LLMResult

log = get_logger(__name__)


class GeminiLLM:
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        from google import genai

        self.model = settings.gemini_model
        self.max_retries = settings.max_retries
        self.timeout_ms = int(settings.http_timeout_s * 1000)
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_options={"timeout": self.timeout_ms},
        )

    async def complete_json(self, req: LLMRequest) -> LLMResult:
        from google.genai import errors as genai_errors
        from google.genai import types

        config: dict[str, Any] = {
            "system_instruction": req.system,
            "response_mime_type": "application/json",
            "temperature": req.temperature,
        }
        if req.schema is not None and req.strict_schema:
            config["response_schema"] = req.schema
        attempt = 0
        while True:
            try:
                resp = await self._client.aio.models.generate_content(
                    model=self.model,
                    contents=req.user,
                    config=types.GenerateContentConfig(**config),
                )
                text = resp.text or ""
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ProviderError("Gemini returned non-object JSON", provider=self.name)
                return LLMResult(data=data, provider=self.name, model=self.model, raw_text=text)
            except genai_errors.APIError as exc:
                code = getattr(exc, "code", None) or 0
                retryable = code in (429, 500, 502, 503, 504)
                if not retryable or attempt >= self.max_retries:
                    raise ProviderError(
                        f"Gemini API error {code}",
                        provider=self.name,
                        retryable=retryable,
                        status=int(code) if code else None,
                    )
                delay = min(20.0, (2**attempt)) + random.uniform(0, 0.25)
                log.info(
                    "gemini retry %d/%d in %.1fs (HTTP %s)",
                    attempt + 1,
                    self.max_retries,
                    delay,
                    code,
                )
                await asyncio.sleep(delay)
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
                await asyncio.sleep(min(20.0, 2**attempt))
                attempt += 1

    async def aclose(self) -> None:
        return None
