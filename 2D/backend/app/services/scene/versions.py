"""Scene version service: build (job), patches (sync), voice commands (job), tree, analysis."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import audit
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.jobs import JobContext
from app.core.rbac import Action
from app.core.security import Principal
from app.db.models.jobs import Job
from app.db.models.scene import SceneVersion
from app.db.models.sessions import InterviewSession
from app.db.models.statements import Statement
from app.db.repositories import scene as repo
from app.db.repositories import statements as statement_repo
from app.services import cases as case_service
from app.services import language
from app.services.interview import prompts
from app.services.scene import builder, geometry, patches
from app.services.scene.templates import load_templates


def _templates(container: Container) -> dict[str, dict[str, Any]]:
    return load_templates(str(container.settings.assets_path / "templates" / "scene_templates"))


async def _create_version(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    sess: InterviewSession,
    *,
    parent: SceneVersion | None,
    scene: dict[str, Any],
    patch: list[dict[str, Any]],
    source: str,
    utterance: str | None,
    details: dict[str, Any] | None = None,
) -> SceneVersion:
    v = SceneVersion(
        session_id=sess.id,
        parent_id=parent.id if parent else None,
        scene=scene,
        patch=patch,
        source=source,
        utterance_original=utterance,
        created_by_role=actor.role,
        created_by_user_id=actor.user_id,
    )
    await repo.add_version(db, v)
    audit.record(
        db,
        actor,
        "scene_version.created",
        object_type="scene_version",
        object_id=v.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"parent_id": v.parent_id, "source": source, "ops": len(patch), **(details or {})},
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id, "scene.updated", {"version_id": v.id, "parent_id": v.parent_id, "source": source}
    )
    return v


def _payload(v: SceneVersion) -> dict[str, Any]:
    scene = builder.validate(v.scene)
    return {
        "id": v.id,
        "session_id": v.session_id,
        "parent_id": v.parent_id,
        "scene": v.scene,
        "patch": v.patch,
        "source": v.source,
        "utterance_original": v.utterance_original,
        "created_by_role": v.created_by_role,
        "created_at": v.created_at,
        "analysis": geometry.analyse(scene),
    }


# ---- build ---------------------------------------------------------------------------------------


async def request_build(
    db: AsyncSession, container: Container, actor: Principal, session_id: str, template: str | None
) -> Job:
    sess, _ = await case_service.require_open_session(db, actor, session_id)
    if not await statement_repo.has_free_recall(db, sess.id):
        raise Conflict(
            "Record the free-recall statement before building the scene",
            code="free_recall_required",
        )
    if template and template not in _templates(container):
        raise ValidationFailed(f"Unknown template {template}")
    return await container.jobs.submit(
        "scene.build", session_id=sess.id, payload={"template": template}, actor=actor
    )


async def build_scene_job(ctx: JobContext, db: AsyncSession) -> dict[str, Any]:
    container: Container = ctx.container
    sess = await db.get(InterviewSession, ctx.session_id or "")
    if sess is None:
        raise NotFound("Session not found")
    statements = await statement_repo.list_statements(db, sess.id, kind="free_recall")
    description_en = "\n".join(s.transcript_english for s in statements if s.transcript_english)
    description_orig = "\n".join(
        s.corrected_transcript_original or s.transcript_original for s in statements
    )
    fs = await statement_repo.get_feature_sheet(db, sess.id)
    scene_fields = {
        k: v
        for k, v in (fs.sheet if fs else {}).items()
        if k in ("place_type", "layout_notes", "objects", "people_positions", "evidence", "events")
    }
    templates = _templates(container)
    wanted = ctx.payload.get("template")
    tpl = {wanted: templates[wanted]} if wanted else templates
    await ctx.progress(30, "building scene")
    res = await container.providers.llm_json(
        prompts.build_scene(description_en, description_orig, tpl, scene_fields)
    )
    scene = builder.normalize(res.data.get("scene") or {})
    v = await _create_version(
        db,
        container,
        ctx.actor,
        sess,
        parent=None,
        scene=scene.model_dump(),
        patch=[],
        source="initial",
        utterance=None,
        details={"provider": res.provider, "prompt_version": prompts.PROMPT_VERSION},
    )
    await ctx.progress(100, "done")
    return {
        "version_id": v.id,
        "template": scene.template,
        "provider": res.provider,
        "analysis": geometry.analyse(scene),
    }


# ---- patches and commands ------------------------------------------------------------------------


async def _load_version_for(
    db: AsyncSession, actor: Principal, version_id: str, action: Action = Action.VIEW_CASE
) -> tuple[SceneVersion, InterviewSession]:
    v = await repo.get_version(db, version_id)
    if v is None:
        raise NotFound("Scene version not found")
    sess, _ = await case_service.load_session(db, actor, v.session_id, action)
    return v, sess


async def apply_patch(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    version_id: str,
    patch_ops: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    parent, sess = await _load_version_for(db, actor, version_id, Action.EDIT_SKETCH_OR_SCENE)
    if sess.status != "active":
        raise Conflict(f"Session is {sess.status}", code="session_not_active")
    scene = patches.apply_patch(parent.scene, patch_ops)
    v = await _create_version(
        db,
        container,
        actor,
        sess,
        parent=parent,
        scene=scene.model_dump(),
        patch=patch_ops,
        source=source,
        utterance=None,
    )
    return _payload(v)


async def request_command(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    version_id: str,
    utterance: str,
    lang: str,
) -> Job:
    v, sess = await _load_version_for(db, actor, version_id, Action.EDIT_SKETCH_OR_SCENE)
    if sess.status != "active":
        raise Conflict(f"Session is {sess.status}", code="session_not_active")
    if not utterance.strip():
        raise ValidationFailed("utterance_original is required")
    return await container.jobs.submit(
        "scene.command",
        session_id=sess.id,
        payload={"version_id": v.id, "utterance": utterance, "language": lang},
        actor=actor,
    )


async def _command_to_version(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    sess: InterviewSession,
    parent: SceneVersion,
    utterance: str,
    english: str,
    lang: str,
    source: str,
) -> dict[str, Any]:
    res = await container.providers.llm_json(
        prompts.scene_command(utterance, english, parent.scene)
    )
    ops = res.data.get("patch") or []
    if not ops:
        container.bus.publish(
            sess.id,
            "error",
            {
                "code": "scene_command_unknown",
                "message": res.data.get("explanation") or "Could not understand the command",
            },
        )
        return {
            "status": "unknown",
            "message": res.data.get("explanation", ""),
            "parent_version_id": parent.id,
        }
    scene = patches.apply_patch(parent.scene, ops)
    v = await _create_version(
        db,
        container,
        actor,
        sess,
        parent=parent,
        scene=scene.model_dump(),
        patch=ops,
        source=source,
        utterance=utterance,
        details={
            "provider": res.provider,
            "language": lang,
            "prompt_version": prompts.PROMPT_VERSION,
        },
    )
    return {
        "status": "created",
        "version_id": v.id,
        "parent_version_id": parent.id,
        "patch": ops,
        "explanation": res.data.get("explanation", ""),
        "analysis": geometry.analyse(scene),
    }


async def scene_command_job(ctx: JobContext, db: AsyncSession) -> dict[str, Any]:
    container: Container = ctx.container
    parent = await repo.get_version(db, ctx.payload["version_id"])
    if parent is None:
        raise NotFound("Scene version not found")
    sess = await db.get(InterviewSession, parent.session_id)
    assert sess is not None
    utterance = str(ctx.payload["utterance"])
    lang = str(ctx.payload.get("language") or "en")
    english, _ = await language.to_english(container.providers, utterance, lang)
    await ctx.progress(40, "converting command")
    out = await _command_to_version(
        db, container, ctx.actor, sess, parent, utterance, english, lang, "voice"
    )
    await ctx.progress(100, "done")
    return out


async def apply_command_from_statement(
    db: AsyncSession, ctx: JobContext, sess: InterviewSession, st: Statement
) -> dict[str, Any]:
    container: Container = ctx.container
    parent = await repo.get_version(db, st.target_version_id or "")
    if parent is None or parent.session_id != sess.id:
        raise NotFound("Target scene version not found")
    utterance = st.corrected_transcript_original or st.transcript_original
    out = await _command_to_version(
        db,
        container,
        ctx.actor,
        sess,
        parent,
        utterance,
        st.transcript_english,
        st.language,
        "voice",
    )
    return {"scene_status": out.get("status"), **{k: v for k, v in out.items() if k != "status"}}


# ---- reads -------------------------------------------------------------------------------------


async def get_tree(db: AsyncSession, actor: Principal, session_id: str) -> list[dict[str, Any]]:
    sess, _ = await case_service.load_session(db, actor, session_id)
    versions = await repo.list_versions(db, sess.id)
    audit.record(
        db,
        actor,
        "scene_tree.viewed",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"count": len(versions)},
    )
    await audit.commit_with_audit(db)
    return [
        {
            "id": v.id,
            "parent_id": v.parent_id,
            "source": v.source,
            "utterance_original": v.utterance_original,
            "created_by_role": v.created_by_role,
            "created_at": v.created_at,
            "ops": len(v.patch or []),
        }
        for v in versions
    ]


async def get_version(db: AsyncSession, actor: Principal, version_id: str) -> dict[str, Any]:
    v, sess = await _load_version_for(db, actor, version_id)
    audit.record(
        db,
        actor,
        "scene_version.viewed",
        object_type="scene_version",
        object_id=v.id,
        session_id=sess.id,
        case_id=sess.case_id,
    )
    await audit.commit_with_audit(db)
    return _payload(v)


def templates_public(container: Container) -> dict[str, dict[str, Any]]:
    return _templates(container)
