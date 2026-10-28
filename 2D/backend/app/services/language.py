"""Translation via the LLM chain. The original text is always kept as the record."""

from __future__ import annotations

from app.providers.registry import ProviderRegistry
from app.services.interview import prompts


async def translate(
    registry: ProviderRegistry, text: str, source: str, target: str
) -> tuple[str, str]:
    """Return (translated_text, provider_name). Identity when languages match or text empty."""
    if not text.strip() or source == target:
        return text, "none"
    result = await registry.llm_json(prompts.translate(text, source, target))
    return str(result.data.get("translation", "")).strip() or text, result.provider


async def to_english(registry: ProviderRegistry, text: str, language: str) -> tuple[str, str]:
    return await translate(registry, text, language, "en")


async def from_english(registry: ProviderRegistry, text: str, language: str) -> tuple[str, str]:
    return await translate(registry, text, "en", language)
