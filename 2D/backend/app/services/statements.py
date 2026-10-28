"""Statements: upload (audio or text), processing job, corrections, feature sheet."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import audit
from app.core.errors import NotFound, ValidationFailed
from app.core.jobs import JobContext
from app.core.security import Principal
from app.db.base import iso_utc, utcnow
from app.db.models.jobs import Job
from app.db.models.sessions import InterviewSession
from app.db.models.statements import Statement
from app.db.repositories import statements as repo
from app.db.session import commit_tx
from app.services import cases as case_service
from app.services import language, speech
from app.services.interview import prompts
from app.services.interview.engine import merge_extracted
from app.services.storage import require_audio

KINDS = ("free_recall", "answer_audio", "edit_command", "scene_command")


async def create_statement(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    session_id: str,
    *,
    kind: str,
    source: str,
    lang: str,
    text: str | None = None,
    audio: bytes | None = None,
    target_version_id: str | None = None,
    question_id: str | None = None,
) -> tuple[Statement, Job]:
    sess, _ = await case_service.require_open_session(db, actor, session_id)
    if kind not in KINDS:
        raise ValidationFailed(f"Unknown statement kind {kind}")
    if lang not in ("hi", "kn", "en"):
        raise ValidationFailed("language must be hi, kn or en")
    st = Statement(
        session_id=sess.id,
        kind=kind,
        source=source,
        language=lang,
        target_version_id=target_version_id,
        status="pending",
    )
    if audio is not None:
        mime = require_audio(audio, container.settings.max_audio_mb)
        rec = await container.files.save(
            db, audio, kind="audio", mime=mime, session_id=sess.id, created_by=actor.user_id
        )
        st.audio_file_id = rec.id
        st.source = "audio"
    else:
        if not text or not text.strip():
            raise ValidationFailed("text is required for typed statements")
        if source not in ("typed", "browser_asr"):
            raise ValidationFailed("source must be typed or browser_asr for text statements")
        st.transcript_original = text.strip()
        st.status = "transcribed"
        st.provider = source
    await repo.add_statement(db, st)
    audit.record(
        db,
        actor,
        "statement.created",
        object_type="statement",
        object_id=st.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={
            "kind": kind,
            "source": st.source,
            "language": lang,
            "has_audio": audio is not None,
        },
    )
    await audit.commit_with_audit(db)
    job = await container.jobs.submit(
        "statement.process",
        session_id=sess.id,
        payload={
            "statement_id": st.id,
            "question_id": question_id,
            "target_version_id": target_version_id,
        },
        actor=actor,
    )
    return st, job


async def get_statement(
    db: AsyncSession, actor: Principal, session_id: str, statement_id: str
) -> Statement:
    sess, _ = await case_service.load_session(db, actor, session_id)
    st = await repo.get_statement(db, statement_id)
    if st is None or st.session_id != sess.id:
        raise NotFound("Statement not found")
    audit.record(
        db,
        actor,
        "statement.viewed",
        object_type="statement",
        object_id=st.id,
        session_id=sess.id,
        case_id=sess.case_id,
    )
    await audit.commit_with_audit(db)
    return st


async def correct_statement(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    session_id: str,
    statement_id: str,
    corrected_text: str,
    note: str,
) -> tuple[Statement, Job]:
    sess, _ = await case_service.require_open_session(db, actor, session_id)
    if actor.kind != "user":
        from app.core.errors import Forbidden

        raise Forbidden("Only staff can correct a transcript")
    st = await repo.get_statement(db, statement_id)
    if st is None or st.session_id != sess.id:
        raise NotFound("Statement not found")
    if not corrected_text.strip():
        raise ValidationFailed("corrected text is empty")
    corrections = list(st.corrections or [])
    corrections.append(
        {
            "at": iso_utc(utcnow()),
            "by": actor.user_id,
            "previous": st.corrected_transcript_original or st.transcript_original,
            "corrected": corrected_text.strip(),
            "note": note,
        }
    )
    st.corrections = corrections
    st.corrected_transcript_original = corrected_text.strip()
    st.status = "transcribed"
    audit.record(
        db,
        actor,
        "statement.corrected",
        object_type="statement",
        object_id=st.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"corrections": len(corrections)},
    )
    await audit.commit_with_audit(db)
    job = await container.jobs.submit(
        "statement.process",
        session_id=sess.id,
        payload={"statement_id": st.id, "rerun": True},
        actor=actor,
    )
    return st, job


async def list_statements(db: AsyncSession, actor: Principal, session_id: str) -> list[Statement]:
    """All statements of a session in time order (witness: own session; staff: case scope)."""
    sess, _ = await case_service.load_session(db, actor, session_id)
    rows = await repo.list_statements(db, sess.id)
    audit.record(
        db,
        actor,
        "statements.listed",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"count": len(rows)},
    )
    await audit.commit_with_audit(db)
    return rows


async def list_questions(db: AsyncSession, actor: Principal, session_id: str) -> list[Any]:
    """All interview questions of a session with their answers, in the order asked."""
    sess, _ = await case_service.load_session(db, actor, session_id)
    rows = await repo.list_questions(db, sess.id)
    audit.record(
        db,
        actor,
        "questions.listed",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"count": len(rows)},
    )
    await audit.commit_with_audit(db)
    return rows


async def get_feature_sheet(db: AsyncSession, actor: Principal, session_id: str) -> dict[str, Any]:
    sess, _ = await case_service.load_session(db, actor, session_id)
    fs = await repo.get_feature_sheet(db, sess.id)
    audit.record(
        db,
        actor,
        "feature_sheet.viewed",
        object_type="feature_sheet",
        object_id=fs.id if fs else None,
        session_id=sess.id,
        case_id=sess.case_id,
    )
    await audit.commit_with_audit(db)
    return {
        "session_id": sess.id,
        "sheet": fs.sheet if fs else {},
        "version": fs.version if fs else 0,
        "updated_at": fs.updated_at if fs else None,
    }


# ---- job handler -------------------------------------------------------------------------


async def process_statement_job(ctx: JobContext, db: AsyncSession) -> dict[str, Any]:
    container: Container = ctx.container
    reg = container.providers
    settings = container.settings
    st = await repo.get_statement(db, ctx.payload["statement_id"])
    if st is None:
        raise NotFound("Statement not found")
    sess = await db.get(InterviewSession, st.session_id)
    assert sess is not None
    result: dict[str, Any] = {"statement_id": st.id, "prompt_version": prompts.PROMPT_VERSION}

    # 1. transcription
    if st.audio_file_id and not st.transcript_original:
        st.status = "transcribing"
        await commit_tx(db)
        await ctx.progress(10, "transcribing")
        rec = await container.files.get(db, st.audio_file_id)
        audio = await container.files.load_bytes(rec)
        t = await speech.transcribe(reg, audio, rec.mime, st.language, settings.max_audio_mb)
        st.transcript_original = t.text
        st.segments = t.segments_json()
        st.provider = t.provider
        st.status = "transcribed"
        result["asr_provider"] = t.provider
        await commit_tx(db)
        ctx.bus.publish(
            sess.id,
            "statement.transcribed",
            {"statement_id": st.id, "kind": st.kind, "language": st.language},
        )

    original = st.corrected_transcript_original or st.transcript_original
    # 2. translation
    await ctx.progress(40, "translating")
    english, tprov = await language.to_english(reg, original, st.language)
    st.transcript_english = english
    result["translation_provider"] = tprov
    await commit_tx(db)

    # 3. kind-specific processing
    if st.kind == "free_recall":
        await ctx.progress(60, "extracting features")
        fs = await repo.get_or_create_feature_sheet(db, sess.id)
        res = await reg.llm_json(
            prompts.extract_feature_sheet(original, english, st.language, fs.sheet)
        )
        extracted = res.data.get("fields", {})
        fs.sheet = merge_extracted(fs.sheet, extracted, source=f"statement:{st.id}")
        st.status = "extracted"
        result["extracted_fields"] = sorted(extracted.keys())
        result["extraction_provider"] = res.provider
        audit.record(
            db,
            ctx.actor,
            "feature_sheet.updated",
            object_type="feature_sheet",
            object_id=fs.id,
            session_id=sess.id,
            case_id=sess.case_id,
            details={
                "fields": result["extracted_fields"],
                "provider": res.provider,
                "statement_id": st.id,
            },
        )
        await audit.commit_with_audit(db)
        ctx.bus.publish(
            sess.id,
            "feature_sheet.updated",
            {"fields": result["extracted_fields"], "statement_id": st.id},
        )
    elif st.kind == "answer_audio" and ctx.payload.get("question_id"):
        from app.services.interview import service as interview_service

        await interview_service.record_answer_from_statement(
            db, container, ctx.actor, sess, ctx.payload["question_id"], st
        )
        st.status = "extracted"
        await commit_tx(db)
    elif st.kind == "edit_command" and st.target_version_id:
        from app.services.sketch import versions as sketch_versions

        await ctx.progress(60, "routing edit")
        out = await sketch_versions.apply_edit_from_statement(db, ctx, sess, st)
        result.update(out)
        st.status = "extracted"
        await commit_tx(db)
    elif st.kind == "scene_command" and st.target_version_id:
        from app.services.scene import versions as scene_versions

        await ctx.progress(60, "converting command")
        out = await scene_versions.apply_command_from_statement(db, ctx, sess, st)
        result.update(out)
        st.status = "extracted"
        await commit_tx(db)
    else:
        st.status = "extracted"
        await commit_tx(db)
    await ctx.progress(100, "done")
    return result
