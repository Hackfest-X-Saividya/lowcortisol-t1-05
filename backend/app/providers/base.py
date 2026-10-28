"""Provider interfaces (Protocols) and result types.

A police deployment can swap any provider for a self-hosted model by implementing the
matching Protocol and registering it in ``app.providers.registry`` - services never
import a concrete provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass
class LLMRequest:
    task: str  # task name (see services/interview/prompts.py)
    system: str
    user: str
    payload: dict[str, Any]  # structured input (mock providers use it directly)
    schema: type[BaseModel] | None = None
    strict_schema: bool = False  # pass the schema to the provider's constrained decoding
    temperature: float = 0.2


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    cached: bool = False
    raw_text: str = ""


@dataclass
class Segment:
    start: float
    end: float
    text: str
    confidence: float | None = None


@dataclass
class Transcript:
    text: str
    language: str
    segments: list[Segment] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    cached: bool = False

    def segments_json(self) -> list[dict[str, Any]]:
        return [
            {"start": s.start, "end": s.end, "text": s.text, "confidence": s.confidence}
            for s in self.segments
        ]


@dataclass
class ImageRequest:
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    seed: int | None = None
    num_steps: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResult:
    png: bytes
    provider: str
    model: str
    seed: int | None = None
    cached: bool = False


@dataclass
class InpaintRequest:
    image_png: bytes
    mask_png: bytes
    prompt: str
    negative_prompt: str = ""
    seed: int | None = None
    strength: float = 0.9


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete_json(self, req: LLMRequest) -> LLMResult: ...


class ASRProvider(Protocol):
    name: str
    model: str

    async def transcribe(self, audio: bytes, mime: str, language: str) -> Transcript: ...


class ImageGenProvider(Protocol):
    name: str
    model: str

    async def generate(self, req: ImageRequest) -> ImageResult: ...


class InpaintProvider(Protocol):
    name: str
    model: str

    async def inpaint(self, req: InpaintRequest) -> ImageResult: ...
