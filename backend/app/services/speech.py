"""Speech-to-text wrapper over the provider registry."""

from __future__ import annotations

from app.providers.base import Transcript
from app.providers.registry import ProviderRegistry
from app.services.storage import require_audio


async def transcribe(
    registry: ProviderRegistry, audio: bytes, mime: str | None, language: str, max_mb: int
) -> Transcript:
    detected = require_audio(audio, max_mb)
    return await registry.transcribe(audio, mime or detected, language)
