"""Deterministic mock image understanding (no AI): every sketch matches its description."""

from __future__ import annotations

from typing import Any

from app.providers.base import LLMResult, VisionRequest


class MockVision:
    name = "mock"
    model = "mock-vision"

    async def vision_json(self, req: VisionRequest) -> LLMResult:
        data: dict[str, Any] = (
            {"matches": True, "mismatches": []} if req.task == "sketch_check" else {}
        )
        return LLMResult(data=data, provider=self.name, model=self.model)
