"""Provider registry: builds providers from settings and routes calls through the
fallback chains (LLM: Gemini -> Groq -> mock; image: Cloudflare -> Pollinations -> mock)
with response validation and the optional response cache.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.db.session import Database
from app.providers.base import (
    ASRProvider,
    ImageGenProvider,
    ImageRequest,
    ImageResult,
    InpaintProvider,
    InpaintRequest,
    LLMProvider,
    LLMRequest,
    LLMResult,
    Transcript,
)
from app.providers.cache import ProviderCacheStore, cache_key
from app.providers.mock import MockASR, MockImageGen, MockInpainter, MockLLM
from app.services.storage import FileStore

log = get_logger(__name__)

INPAINT_UNAVAILABLE_MSG = (
    "This change needs online image editing, which is unavailable. "
    "Try a shape edit or an accessory instead."
)


class ProviderRegistry:
    def __init__(self, settings: Settings, cache: ProviderCacheStore) -> None:
        self.settings = settings
        self.cache = cache
        self.llms: dict[str, LLMProvider] = {}
        self.asrs: dict[str, ASRProvider] = {}
        self.images: dict[str, ImageGenProvider] = {}
        self.inpainters: dict[str, InpaintProvider] = {}
        self._closeables: list[Any] = []

    # ---- LLM -----------------------------------------------------------------------------

    def _validate(self, req: LLMRequest, data: dict[str, Any]) -> dict[str, Any]:
        if req.schema is None:
            return data
        return req.schema.model_validate(data).model_dump()

    async def llm_json(self, req: LLMRequest) -> LLMResult:
        """Try each provider in the chain; validate; retry once with the validation error."""
        errors: list[str] = []
        for name in self.settings.llm_chain:
            provider = self.llms.get(name)
            if provider is None:
                continue
            use_cache = name != "mock"
            key = cache_key(
                name,
                provider.model,
                {
                    "task": req.task,
                    "system": req.system,
                    "user": req.user,
                    "temperature": req.temperature,
                    "schema": req.schema.__name__ if req.schema else None,
                },
            )
            if use_cache:
                cached = await self.cache.get(key)
                if cached is not None:
                    try:
                        data = self._validate(req, json.loads(cached.decode("utf-8")))
                        return LLMResult(
                            data=data, provider=name, model=provider.model, cached=True
                        )
                    except (ValueError, ValidationError):
                        pass
            attempt_req = req
            for attempt in range(2):
                try:
                    result = await provider.complete_json(attempt_req)
                    result.data = self._validate(req, result.data)
                    if use_cache:
                        await self.cache.put(
                            key,
                            name,
                            provider.model,
                            json.dumps(result.data, ensure_ascii=False).encode(),
                            "application/json",
                        )
                    return result
                except ValidationError as exc:
                    errors.append(f"{name}: invalid response ({exc.error_count()} errors)")
                    if attempt == 0:
                        attempt_req = LLMRequest(
                            task=req.task,
                            system=req.system,
                            user=req.user
                            + "\n\nYour previous answer failed validation: "
                            + str(exc)[:800]
                            + "\nReturn corrected JSON only.",
                            payload=req.payload,
                            schema=req.schema,
                            strict_schema=req.strict_schema,
                            temperature=req.temperature,
                        )
                        continue
                    break
                except ProviderError as exc:
                    errors.append(f"{name}: {exc.message}")
                    log.warning("LLM provider %s failed for task %s; falling back", name, req.task)
                    break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{name}: {type(exc).__name__}")
                    log.warning(
                        "LLM provider %s crashed for task %s (%s); falling back",
                        name,
                        req.task,
                        type(exc).__name__,
                    )
                    break
        raise ProviderError("All LLM providers failed: " + "; ".join(errors), provider="llm")

    # ---- ASR -----------------------------------------------------------------------------

    async def transcribe(self, audio: bytes, mime: str, language: str) -> Transcript:
        import hashlib

        errors: list[str] = []
        for name in self.settings.asr_chain:
            provider = self.asrs.get(name)
            if provider is None:
                continue
            use_cache = name != "mock"
            key = cache_key(
                name,
                provider.model,
                {
                    "audio_sha256": hashlib.sha256(audio).hexdigest(),
                    "language": language,
                },
            )
            if use_cache:
                cached = await self.cache.get(key)
                if cached is not None:
                    d = json.loads(cached.decode("utf-8"))
                    from app.providers.base import Segment

                    return Transcript(
                        text=d["text"],
                        language=d["language"],
                        segments=[Segment(**s) for s in d.get("segments", [])],
                        provider=name,
                        model=provider.model,
                        cached=True,
                    )
            try:
                t = await provider.transcribe(audio, mime, language)
                if use_cache:
                    payload = {
                        "text": t.text,
                        "language": t.language,
                        "segments": t.segments_json(),
                    }
                    await self.cache.put(
                        key,
                        name,
                        provider.model,
                        json.dumps(payload, ensure_ascii=False).encode(),
                        "application/json",
                    )
                return t
            except ProviderError as exc:
                errors.append(f"{name}: {exc.message}")
                log.warning("ASR provider %s failed; falling back", name)
        raise ProviderError("All ASR providers failed: " + "; ".join(errors), provider="asr")

    # ---- images ---------------------------------------------------------------------------

    async def generate_image(self, req: ImageRequest) -> ImageResult:
        errors: list[str] = []
        for name in self.settings.image_chain:
            provider = self.images.get(name)
            if provider is None:
                continue
            use_cache = name != "mock"
            key = cache_key(
                name,
                provider.model,
                {
                    "prompt": req.prompt,
                    "negative_prompt": req.negative_prompt,
                    "width": req.width,
                    "height": req.height,
                    "seed": req.seed,
                    "num_steps": req.num_steps,
                },
            )
            if use_cache:
                cached = await self.cache.get(key)
                if cached is not None:
                    return ImageResult(
                        png=cached, provider=name, model=provider.model, seed=req.seed, cached=True
                    )
            try:
                res = await provider.generate(req)
                if use_cache:
                    await self.cache.put(key, name, provider.model, res.png, "image/png")
                return res
            except ProviderError as exc:
                errors.append(f"{name}: {exc.message}")
                log.warning("image provider %s failed; falling back", name)
        raise ProviderError("All image providers failed: " + "; ".join(errors), provider="image")

    async def inpaint(self, req: InpaintRequest) -> ImageResult:
        chain = self.settings.inpaint_chain
        if not chain:
            raise ProviderError(INPAINT_UNAVAILABLE_MSG, provider="inpaint")
        errors: list[str] = []
        for name in chain:
            provider = self.inpainters.get(name)
            if provider is None:
                continue
            try:
                return await provider.inpaint(req)
            except ProviderError as exc:
                errors.append(f"{name}: {exc.message}")
        raise ProviderError(
            INPAINT_UNAVAILABLE_MSG + " (" + "; ".join(errors) + ")", provider="inpaint"
        )

    async def aclose(self) -> None:
        for c in self._closeables:
            try:
                await c.aclose()
            except Exception:  # noqa: BLE001
                pass


def build_registry(settings: Settings, files: FileStore, db: Database) -> ProviderRegistry:
    cache = ProviderCacheStore(files, db, enabled=settings.provider_cache)
    reg = ProviderRegistry(settings, cache)
    reg.llms["mock"] = MockLLM()
    reg.asrs["mock"] = MockASR()
    reg.images["mock"] = MockImageGen()
    reg.inpainters["mock"] = MockInpainter()
    if settings.mock_mode or not settings.cloud_mode_ack:
        return reg
    if settings.gemini_configured:
        try:
            from app.providers.gemini import GeminiLLM

            g = GeminiLLM(settings)
            reg.llms["gemini"] = g
            reg._closeables.append(g)
        except Exception as exc:  # noqa: BLE001
            log.warning("Gemini client could not be created (%s); skipping", type(exc).__name__)
    if settings.groq_configured:
        from app.providers.groq import GroqASR, GroqLLM

        reg.asrs["groq"] = GroqASR(settings)
        reg.llms["groq"] = GroqLLM(settings)
        reg._closeables += [reg.asrs["groq"], reg.llms["groq"]]
    if settings.cloudflare_configured:
        from app.providers.cloudflare import CloudflareImageGen, CloudflareInpainter

        reg.images["cloudflare"] = CloudflareImageGen(settings)
        reg.inpainters["cloudflare"] = CloudflareInpainter(settings)
        reg._closeables += [reg.images["cloudflare"], reg.inpainters["cloudflare"]]
    from app.providers.pollinations import PollinationsImageGen

    reg.images["pollinations"] = PollinationsImageGen(settings)
    reg._closeables.append(reg.images["pollinations"])
    return reg
