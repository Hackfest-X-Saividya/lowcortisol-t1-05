"""Exports: high-resolution sketch PNG, watermarked photoreal PNG (staff), PDF report,
top-down scene PNG."""

from __future__ import annotations

from typing import Any

import cv2
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import audit
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.jobs import JobContext
from app.core.rbac import Action, can
from app.core.security import Principal
from app.db.base import iso_utc, utcnow
from app.db.models.cases import Case, Witness
from app.db.models.jobs import Job
from app.db.models.sessions import Export, InterviewSession
from app.db.models.users import User
from app.db.repositories import scene as scene_repo
from app.db.repositories import sessions as session_repo
from app.db.repositories import sketch as sketch_repo
from app.db.repositories import statements as statement_repo
from app.services import cases as case_service
from app.services import reports
from app.services.scene import builder as scene_builder
from app.services.scene.render import render_top_down
from app.services.sketch.render import decode_png, encode_png, pencil_sketch, watermark

WATERMARK = "AI-generated approximation - not a photograph"
KINDS = ("png", "pdf", "scene_png", "photoreal_png")


async def request_export(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    session_id: str,
    kind: str,
    sketch_version_id: str | None,
    scene_version_id: str | None,
) -> Job:
    sess, scope = await case_service.load_session(db, actor, session_id, Action.VIEW_CASE)
    if actor.kind != "user" or not can(actor, Action.EXPORT, scope):
        raise Forbidden("Not allowed to export this session")
    if kind not in KINDS:
        raise ValidationFailed(f"kind must be one of {KINDS}")
    return await container.jobs.submit(
        "export.create",
        session_id=sess.id,
        payload={
            "kind": kind,
            "sketch_version_id": sketch_version_id,
            "scene_version_id": scene_version_id,
        },
        actor=actor,
    )


async def _sketch_version(db: AsyncSession, sess: InterviewSession, version_id: str | None):  # type: ignore[no-untyped-def]
    if version_id:
        v = await sketch_repo.get_version(db, version_id)
        if v is None or v.session_id != sess.id:
            raise NotFound("Sketch version not found")
        return v
    signoff = await session_repo.latest_signoff(db, sess.id)
    if signoff and signoff.sketch_version_id:
        v = await sketch_repo.get_version(db, signoff.sketch_version_id)
        if v is not None:
            return v
    return await sketch_repo.latest_version(db, sess.id)


async def _scene_version(db: AsyncSession, sess: InterviewSession, version_id: str | None):  # type: ignore[no-untyped-def]
    if version_id:
        v = await scene_repo.get_version(db, version_id)
        if v is None or v.session_id != sess.id:
            raise NotFound("Scene version not found")
        return v
    signoff = await session_repo.latest_signoff(db, sess.id)
    if signoff and signoff.scene_version_id:
        v = await scene_repo.get_version(db, signoff.scene_version_id)
        if v is not None:
            return v
    return await scene_repo.latest_version(db, sess.id)


async def _upscaled_sketch(container: Container, db: AsyncSession, master_file_id: str) -> bytes:
    _, data = await container.files.load(db, master_file_id)
    master = decode_png(data)
    size = container.settings.export_size_px
    big = cv2.resize(master, (size, size), interpolation=cv2.INTER_LANCZOS4)
    return encode_png(pencil_sketch(big, container.settings))


async def export_job(ctx: JobContext, db: AsyncSession) -> dict[str, Any]:
    container: Container = ctx.container
    settings = container.settings
    sess = await db.get(InterviewSession, ctx.session_id or "")
    if sess is None:
        raise NotFound("Session not found")
    kind = str(ctx.payload["kind"])
    await ctx.progress(20, f"building {kind}")
    if kind in ("png", "photoreal_png"):
        v = await _sketch_version(db, sess, ctx.payload.get("sketch_version_id"))
        if v is None:
            raise NotFound("No sketch version to export")
        if kind == "png":
            data = await _upscaled_sketch(container, db, v.master_file_id)
        else:
            _, raw = await container.files.load(db, v.master_file_id)
            master = decode_png(raw)
            big = cv2.resize(
                master,
                (settings.export_size_px, settings.export_size_px),
                interpolation=cv2.INTER_LANCZOS4,
            )
            data = encode_png(watermark(big, WATERMARK))
        file_kind, mime = "export_png", "image/png"
        detail: dict[str, Any] = {"sketch_version_id": v.id}
    elif kind == "scene_png":
        sv = await _scene_version(db, sess, ctx.payload.get("scene_version_id"))
        if sv is None:
            raise NotFound("No scene version to export")
        scene = scene_builder.validate(sv.scene)
        data = encode_png(render_top_down(scene))
        file_kind, mime = "scene_image", "image/png"
        detail = {"scene_version_id": sv.id}
    else:
        data, detail = await _build_pdf(container, db, sess, ctx.payload.get("sketch_version_id"))
        file_kind, mime = "export_pdf", "application/pdf"
    rec = await container.files.save(
        db, data, kind=file_kind, mime=mime, session_id=sess.id, created_by=ctx.actor.user_id
    )
    exp = Export(
        session_id=sess.id,
        kind=kind,
        file_id=rec.id,
        sha256=rec.sha256_plain,
        created_by=ctx.actor.user_id,
    )
    await session_repo.add_export(db, exp)
    audit.record(
        db,
        ctx.actor,
        "export.created",
        object_type="export",
        object_id=exp.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"kind": kind, "file_id": rec.id, "sha256": rec.sha256_plain, **detail},
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id,
        "export.ready",
        {"export_id": exp.id, "kind": kind, "file_id": rec.id, "sha256": rec.sha256_plain},
    )
    await ctx.progress(100, "done")
    return {"export_id": exp.id, "kind": kind, "file_id": rec.id, "sha256": rec.sha256_plain}


async def _build_pdf(
    container: Container, db: AsyncSession, sess: InterviewSession, sketch_version_id: str | None
) -> tuple[bytes, dict[str, Any]]:
    settings = container.settings
    case = await db.get(Case, sess.case_id)
    officer = await db.get(User, sess.officer_id)
    witness = await db.get(Witness, sess.witness_id)
    assert case is not None and witness is not None
    v = await _sketch_version(db, sess, sketch_version_id)
    sketch_png = None
    if v is not None:
        sketch_png = await _upscaled_sketch(container, db, v.master_file_id)
    signoff = await session_repo.latest_signoff(db, sess.id)
    locks = await sketch_repo.get_locks(db, sess.id)
    fs = await statement_repo.get_feature_sheet(db, sess.id)
    statements = await statement_repo.list_statements(db, sess.id, kind="free_recall")
    questions = await statement_repo.list_questions(db, sess.id)
    versions = await sketch_repo.list_versions(db, sess.id)
    exports = await session_repo.list_exports(db, sess.id)
    display_count = await session_repo.count_display_events(db, sess.id)
    pdf = reports.build_report(
        font_dir=settings.assets_path / "fonts",
        case={
            "case_number": case.case_number,
            "station": case.station,
            "crime_type": case.crime_type,
        },
        officer={
            "full_name": officer.full_name if officer else "",
            "username": officer.username if officer else "",
        },
        session={"id": sess.id},
        witness={
            "display_name": witness.display_name,
            "preferred_language": witness.preferred_language,
        },
        sketch_png=sketch_png,
        confidences=dict(signoff.confidences) if signoff else {},
        locks={f: {"locked": lk.locked, "confidence": lk.confidence} for f, lk in locks.items()},
        feature_sheet=fs.sheet if fs else {},
        statements=[
            {
                "kind": s.kind,
                "source": s.source,
                "language": s.language,
                "created_at": iso_utc(s.created_at)[:19],
                "original": s.corrected_transcript_original or s.transcript_original,
                "english": s.transcript_english,
            }
            for s in statements
        ],
        questions=[
            {
                "field_key": q.field_key,
                "text_en": q.text_en,
                "text_local": q.text_local,
                "answer": q.answer_text_en or q.answer_option_id or q.answer_type or "",
            }
            for q in questions
        ],
        versions=[
            {
                "created_at": iso_utc(x.created_at),
                "edit_source": x.edit_source,
                "summary": _summary(x.edit or {}),
                "provider": (x.provider_info or {}).get("provider", ""),
                "rating": x.witness_rating,
            }
            for x in versions
        ],
        display_event_count=display_count,
        export_hashes=[{"kind": e.kind, "sha256": e.sha256} for e in exports]
        + (
            [
                {
                    "kind": "sketch_png (embedded)",
                    "sha256": __import__("hashlib").sha256(sketch_png).hexdigest(),
                }
            ]
            if sketch_png
            else []
        ),
        cloud_used=settings.cloud_active,
        generated_at=utcnow(),
    )
    return pdf, {"sketch_version_id": v.id if v else None, "pages": "pdf"}


def _summary(edit: dict[str, Any]) -> str:
    t = edit.get("type", "")
    if t == "initial":
        return "initial generation"
    if t == "geometric":
        amount = edit.get("amount")
        return f"{edit.get('param') or 'drag'} {amount if amount is not None else ''}"
    if t == "overlay":
        return f"overlay {edit.get('overlay_id')}"
    if t == "inpaint":
        return f"inpaint: {edit.get('prompt', '')[:40]}"
    return str(t)


async def get_export(db: AsyncSession, actor: Principal, export_id: str) -> Export:
    exp = await session_repo.get_export(db, export_id)
    if exp is None:
        raise NotFound("Export not found")
    sess, scope = await case_service.load_session(db, actor, exp.session_id)
    if actor.kind != "user" or not (
        can(actor, Action.EXPORT, scope) or can(actor, Action.VIEW_CASE, scope)
    ):
        raise Forbidden("Not allowed to view this export")
    audit.record(
        db,
        actor,
        "export.viewed",
        object_type="export",
        object_id=exp.id,
        session_id=sess.id,
        case_id=sess.case_id,
    )
    await audit.commit_with_audit(db)
    return exp
