"""Deterministic mock speech-to-text.

Returns fixed transcripts per language from ``tests/fixtures/transcripts.json``. The kind
of transcript defaults to ``free_recall``; a marker ``nishaan-mock:<kind>`` anywhere in the
audio bytes selects another fixture (``edit_command``, ``scene_command``, ``answer``).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.providers.base import Segment, Transcript

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "transcripts.json"
_MARKER = re.compile(rb"nishaan-mock:([a-z_]+)")


@lru_cache(maxsize=1)
def load_fixtures() -> dict[str, Any]:
    with FIXTURES.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


class MockASR:
    name = "mock"
    model = "mock-asr"

    async def transcribe(self, audio: bytes, mime: str, language: str) -> Transcript:
        fixtures = load_fixtures()
        lang = language if language in fixtures else "en"
        kind = "free_recall"
        m = _MARKER.search(audio)
        if m:
            kind = m.group(1).decode()
        entry = fixtures[lang].get(kind) or fixtures[lang]["free_recall"]
        text = entry["original"]
        sentences = [s.strip() for s in re.split(r"(?<=[।.!?])\s+", text) if s.strip()]
        segments = []
        t = 0.0
        for s in sentences:
            dur = max(1.0, len(s) / 12.0)
            segments.append(
                Segment(start=round(t, 2), end=round(t + dur, 2), text=s, confidence=0.92)
            )
            t += dur
        return Transcript(
            text=text, language=lang, segments=segments, provider=self.name, model=self.model
        )
