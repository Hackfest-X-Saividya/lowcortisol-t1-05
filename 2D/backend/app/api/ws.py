"""WebSocket per session: ``/ws/sessions/{id}?token=...``.

Server events: statement.transcribed, feature_sheet.updated, question.next, job.progress,
version.created, stability.result, preview.ready, scene.updated, export.ready, error.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import resolve_principal
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.rbac import Action, can
from app.db.repositories import cases as case_repo
from app.db.repositories import sessions as session_repo

log = get_logger(__name__)
ws_router = APIRouter()


@ws_router.websocket("/ws/sessions/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str, token: str = Query(...)) -> None:
    container = websocket.app.state.container
    async with container.db.session() as db:
        try:
            principal = await resolve_principal(
                container,
                db,
                token,
                websocket.client.host if websocket.client else "",
                websocket.headers.get("User-Agent", ""),
                "ws",
            )
            sess = await session_repo.get_session(db, session_id)
            if sess is None:
                raise AppError("session not found", status_code=404)
            scope = await case_repo.scope_for_session(db, sess)
            if not can(principal, Action.VIEW_CASE, scope):
                raise AppError("forbidden", status_code=403)
        except AppError as exc:
            await websocket.close(code=4401 if exc.status_code == 401 else 4403)
            return
    await websocket.accept()
    queue = container.bus.subscribe(session_id)
    await websocket.send_text(json.dumps({"type": "connected", "session_id": session_id}))

    async def _reader() -> None:
        # Drain client messages (pings); the client never drives state over the socket.
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    reader = asyncio.create_task(_reader())
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event, ensure_ascii=False))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        reader.cancel()
        container.bus.unsubscribe(session_id, queue)
