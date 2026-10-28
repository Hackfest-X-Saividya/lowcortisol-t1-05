"""In-process async event bus feeding the per-session WebSockets."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.db.base import iso_utc, utcnow

EVENT_TYPES = (
    "statement.transcribed",
    "feature_sheet.updated",
    "question.next",
    "job.progress",
    "version.created",
    "stability.result",
    "preview.ready",
    "scene.updated",
    "export.ready",
    "error",
)


class EventBus:
    def __init__(self, max_queue: int = 500) -> None:
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._max_queue = max_queue
        self.history: dict[str, list[dict[str, Any]]] = defaultdict(list)  # small ring, tests

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subs[session_id].add(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs[session_id].discard(q)
        if not self._subs[session_id]:
            self._subs.pop(session_id, None)

    def publish(self, session_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
        if not session_id:
            return
        event = {
            "type": event_type,
            "session_id": session_id,
            "at": iso_utc(utcnow()),
            "data": payload,
        }
        hist = self.history[session_id]
        hist.append(event)
        if len(hist) > 200:
            del hist[: len(hist) - 200]
        for q in list(self._subs.get(session_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop the oldest event rather than block producers.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def subscriber_count(self, session_id: str) -> int:
        return len(self._subs.get(session_id, ()))
