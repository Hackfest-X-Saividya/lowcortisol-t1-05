from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep, DbDep, PrincipalDep
from app.core import audit
from app.core.errors import ValidationFailed
from app.services.interview import live
from app.services.sketch import versions as sketch_service

router = APIRouter()


class TurnText(BaseModel):
    text: str = Field(default="", max_length=6000)
    language: Literal["hi", "kn", "en"] | None = None
    source: Literal["browser_asr", "typed"] = "browser_asr"
    dont_remember: bool = False


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    language: Literal["hi", "kn", "en"] = "kn"


@router.get("/sessions/{session_id}/interview/live")
async def live_state(
    session_id: str, principal: PrincipalDep, db: DbDep, container: ContainerDep
) -> dict[str, Any]:
    return await live.state(db, container, principal, session_id)


@router.post("/sessions/{session_id}/interview/turn")
async def live_turn(
    session_id: str,
    request: Request,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
    audio: UploadFile | None = File(default=None),
    language: str | None = Form(default=None),
) -> dict[str, Any]:
    """One witness turn: JSON {text, language, source, dont_remember} or multipart audio."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        if audio is None:
            raise ValidationFailed("audio file required")
        return await live.turn(
            db,
            container,
            principal,
            session_id,
            text=None,
            language=language,
            source="audio",
            audio=await audio.read(),
        )
    body = TurnText.model_validate(await request.json())
    return await live.turn(
        db,
        container,
        principal,
        session_id,
        text=body.text,
        language=body.language,
        source=body.source,
        dont_remember=body.dont_remember,
    )


@router.post("/tts")
async def tts(
    body: TTSRequest, principal: PrincipalDep, db: DbDep, container: ContainerDep
) -> Response:
    """Spoken audio for a short interviewer line; 204 when no TTS provider is available."""
    out = await container.providers.tts(body.text, body.language)
    audit.record(
        db,
        principal,
        "tts.spoken",
        object_type="tts",
        details={"language": body.language, "chars": len(body.text), "served": out is not None},
    )
    await audit.commit_with_audit(db)
    if out is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    data, mime = out
    return Response(
        content=data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"}
    )


@router.post("/sessions/{session_id}/sketch/live", status_code=status.HTTP_201_CREATED)
async def save_live_sketch(
    session_id: str,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
    image: UploadFile = File(...),
    params: str = Form(default="{}"),
) -> dict[str, Any]:
    try:
        p = json.loads(params)
    except json.JSONDecodeError:
        raise ValidationFailed("params must be JSON")
    v = await sketch_service.save_live_sketch(
        db, container, principal, session_id, await image.read(), p if isinstance(p, dict) else {}
    )
    return {"version_id": v.id, "sketch_file_id": v.sketch_file_id}


class RenderRequest(BaseModel):
    text: str | None = Field(default=None, max_length=6000)
    commit: bool = False
    wait_s: float | None = Field(default=None, ge=0, le=55)


@router.post("/sessions/{session_id}/interview/render")
async def live_render(
    session_id: str,
    body: RenderRequest,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
) -> dict[str, Any]:
    """Realistic live sketch. ``text`` = words still being spoken (preview, not stored);
    ``commit`` = render the saved description and store it as a sketch version.

    Answers at once with the instant drawing (closest library face + corrections) while the
    realistic portrait is generated in the background (``pending``); poll
    ``GET .../interview/render/latest``. A commit waits up to ``wait_s`` (default 30 s) for
    the portrait before saving whatever is newest."""
    from app.services.interview import live_render as renderer

    return await renderer.render(
        db,
        container,
        principal,
        session_id,
        text=body.text,
        commit=body.commit,
        wait_s=body.wait_s,
    )


@router.get("/sessions/{session_id}/interview/render/latest")
async def live_render_latest(
    session_id: str,
    principal: PrincipalDep,
    db: DbDep,
    after: int = 0,
) -> dict[str, Any]:
    """Newest finished portrait for this session if newer than ``after`` (its ``seq``)."""
    from app.services import cases as case_service
    from app.services.interview import live_render as renderer

    sess, _ = await case_service.load_session(db, principal, session_id)
    return renderer.latest(sess.id, after)


@router.post("/sessions/{session_id}/transcribe")
async def interim_transcribe(
    session_id: str,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
    audio: UploadFile = File(...),
    language: str = Form(default="kn"),
) -> dict[str, Any]:
    """Words so far while the witness is still speaking (Groq Whisper). Not stored."""
    from app.services import cases as case_service
    from app.services import speech

    sess, _ = await case_service.require_open_session(db, principal, session_id)
    data = await audio.read()
    t = await speech.transcribe(
        container.providers,
        data,
        None,
        language if language in ("kn", "hi", "en") else "en",
        container.settings.max_audio_mb,
    )
    audit.record(
        db,
        principal,
        "transcribe.interim",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"bytes": len(data), "provider": t.provider},
    )
    await audit.commit_with_audit(db)
    return {"text": t.text, "provider": t.provider}
