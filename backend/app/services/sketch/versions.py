"""Sketch version service: generation, edits, previews, tree, locks, ratings, compare.

Every version stores a ``base_master`` (no overlays), the ``master`` (base + overlays),
the pencil ``sketch`` the witness sees, the landmarks, the edit that produced it, the
overlay list and cumulative slider values. Versions are never deleted; every edit creates
a child of the version it was applied to, so the tree can branch.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import audit
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.jobs import JobContext
from app.core.rbac import Action, can
from app.core.security import Principal
from app.db.models.jobs import Job
from app.db.models.sessions import InterviewSession
from app.db.models.sketch import CONFIDENCES, FEATURES, SketchVersion
from app.db.models.statements import Statement
from app.db.repositories import sketch as repo
from app.db.repositories import statements as statement_repo
from app.services import cases as case_service
from app.services import language
from app.services.interview import prompts
from app.services.sketch import overlays as overlay_service
from app.services.sketch import stability as stability_service
from app.services.sketch.edit_router import (
    PREVIEW_AMOUNTS,
    ResolvedEdit,
    resolve_structured,
    route_utterance,
)
from app.services.sketch.generation import generate_master
from app.services.sketch.inpaint import inpaint_region
from app.services.sketch.landmarks import landmarks_from_json, landmarks_to_json
from app.services.sketch.masks import exclude_locked, mask_to_png_bytes, region_mask
from app.services.sketch.regions import SLIDERS, handle_positions, slider_moves
from app.services.sketch.render import decode_png, encode_png, pencil_sketch
from app.services.sketch.warp import compute_displacement, warp_image, warp_image_ex

EDIT_SOURCES = ("voice", "text", "drag", "slider", "accessory", "artist")


# ---- helpers ------------------------------------------------------------------------------


async def _load_image(
    container: Container, db: AsyncSession, file_id: str, gray: bool = False
) -> np.ndarray:
    _, data = await container.files.load(db, file_id)
    return decode_png(data, gray=gray)


async def _save_png(
    container: Container,
    db: AsyncSession,
    img: np.ndarray,
    kind: str,
    session_id: str,
    created_by: str | None,
) -> str:
    rec = await container.files.save(
        db,
        encode_png(img),
        kind=kind,
        mime="image/png",
        session_id=session_id,
        created_by=created_by,
    )
    return rec.id


async def _create_version(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    sess: InterviewSession,
    *,
    parent: SketchVersion | None,
    base_master: np.ndarray,
    master: np.ndarray,
    landmarks: np.ndarray,
    mask: np.ndarray | None,
    edit: dict[str, Any],
    edit_source: str,
    utterance: str | None,
    seed: int | None,
    provider_info: dict[str, Any],
    stability: dict[str, Any],
    overlays: list[dict[str, Any]],
    sliders: dict[str, float],
) -> SketchVersion:
    settings = container.settings
    sketch = pencil_sketch(master, settings)
    base_id = await _save_png(
        container, db, base_master, "base_master_image", sess.id, actor.user_id
    )
    master_id = await _save_png(container, db, master, "master_image", sess.id, actor.user_id)
    sketch_id = await _save_png(container, db, sketch, "sketch_image", sess.id, actor.user_id)
    mask_id = None
    if mask is not None:
        rec = await container.files.save(
            db,
            mask_to_png_bytes(mask),
            kind="mask",
            mime="image/png",
            session_id=sess.id,
            created_by=actor.user_id,
        )
        mask_id = rec.id
    v = SketchVersion(
        session_id=sess.id,
        parent_id=parent.id if parent else None,
        master_file_id=master_id,
        base_master_file_id=base_id,
        sketch_file_id=sketch_id,
        mask_file_id=mask_id,
        landmarks=landmarks_to_json(landmarks),
        edit=edit,
        edit_source=edit_source,
        utterance_original=utterance,
        seed=seed,
        provider_info=provider_info,
        stability=stability,
        overlays=overlays,
        sliders=sliders,
        created_by_user_id=actor.user_id,
        created_by_role=actor.role,
    )
    await repo.add_version(db, v)
    audit.record(
        db,
        actor,
        "version.created",
        object_type="sketch_version",
        object_id=v.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={
            "parent_id": v.parent_id,
            "edit_source": edit_source,
            "edit_type": edit.get("type"),
            "provider": provider_info.get("provider"),
            "stability_warning": stability.get("warning", False),
        },
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id,
        "version.created",
        {
            "version_id": v.id,
            "parent_id": v.parent_id,
            "sketch_file_id": sketch_id,
            "edit_source": edit_source,
        },
    )
    if stability:
        container.bus.publish(sess.id, "stability.result", {"version_id": v.id, **stability})
    return v


def _version_payload(v: SketchVersion, staff_master: bool) -> dict[str, Any]:
    lm = landmarks_from_json(v.landmarks) if v.landmarks else None
    return {
        "id": v.id,
        "session_id": v.session_id,
        "parent_id": v.parent_id,
        "sketch_file_id": v.sketch_file_id,
        "master_file_id": v.master_file_id if staff_master else None,
        "base_master_file_id": v.base_master_file_id if staff_master else None,
        "mask_file_id": v.mask_file_id,
        "landmarks": v.landmarks,
        "handle_positions": handle_positions(lm) if lm is not None else {},
        "sliders": v.sliders or {},
        "overlays": v.overlays or [],
        "edit": v.edit or {},
        "edit_source": v.edit_source,
        "utterance_original": v.utterance_original,
        "seed": v.seed,
        "provider_info": v.provider_info or {},
        "stability": v.stability or {},
        "witness_rating": v.witness_rating,
        "created_by_role": v.created_by_role,
        "created_at": v.created_at,
        "quality_warning": bool((v.provider_info or {}).get("quality_warning", False)),
    }


# ---- generation -----------------------------------------------------------------------------


async def request_sketch(
    db: AsyncSession, container: Container, actor: Principal, session_id: str, seed: int | None
) -> Job:
    sess, _ = await case_service.require_open_session(db, actor, session_id)
    if not await statement_repo.has_free_recall(db, sess.id):
        raise Conflict(
            "A free-recall statement must be saved before any face is generated",
            code="free_recall_required",
        )
    return await container.jobs.submit(
        "sketch.generate", session_id=sess.id, payload={"seed": seed}, actor=actor
    )


async def generate_sketch_job(ctx: JobContext, db: AsyncSession) -> dict[str, Any]:
    container: Container = ctx.container
    settings = container.settings
    sess = await db.get(InterviewSession, ctx.session_id or "")
    if sess is None:
        raise NotFound("Session not found")
    if not await statement_repo.has_free_recall(db, sess.id):
        raise Conflict("No free-recall statement", code="free_recall_required")
    fs = await statement_repo.get_feature_sheet(db, sess.id)
    sheet = fs.sheet if fs else {}
    await ctx.progress(10, "generating face")
    landmarker = None if settings.mock_mode else container.landmarker
    gen = await generate_master(
        container.providers, landmarker, settings, sheet, ctx.payload.get("seed")
    )
    await ctx.progress(70, "rendering sketch")
    provider_info = {
        "type": "generation",
        "provider": gen.provider,
        "model": gen.model,
        "seed": gen.seed,
        "attempts": gen.attempts,
        "quality_warning": gen.quality_warning,
        "landmark_source": gen.landmark_source,
        "prompt_version": prompts.PROMPT_VERSION,
    }
    edit = {
        "type": "initial",
        "prompt": gen.prompt.prompt,
        "negative_prompt": gen.prompt.negative_prompt,
        "notes": gen.prompt.notes,
        "used_fields": gen.prompt.used_fields,
    }
    v = await _create_version(
        db,
        container,
        ctx.actor,
        sess,
        parent=None,
        base_master=gen.master,
        master=gen.master,
        landmarks=gen.landmarks,
        mask=None,
        edit=edit,
        edit_source="initial",
        utterance=None,
        seed=gen.seed,
        provider_info=provider_info,
        stability={},
        overlays=[],
        sliders={},
    )
    await ctx.progress(100, "done")
    return {
        "version_id": v.id,
        "sketch_file_id": v.sketch_file_id,
        "quality_warning": gen.quality_warning,
        "provider_info": provider_info,
    }


# ---- edits ------------------------------------------------------------------------------------


async def _load_version_for(
    db: AsyncSession, actor: Principal, version_id: str, action: Action = Action.VIEW_CASE
) -> tuple[SketchVersion, InterviewSession]:
    v = await repo.get_version(db, version_id)
    if v is None:
        raise NotFound("Sketch version not found")
    sess, _ = await case_service.load_session(db, actor, v.session_id, action)
    return v, sess


async def request_edit(
    db: AsyncSession, container: Container, actor: Principal, version_id: str, body: dict[str, Any]
) -> Job:
    v, sess = await _load_version_for(db, actor, version_id, Action.EDIT_SKETCH_OR_SCENE)
    if sess.status != "active":
        raise Conflict(f"Session is {sess.status}", code="session_not_active")
    if body.get("source") not in EDIT_SOURCES:
        raise ValidationFailed(f"source must be one of {EDIT_SOURCES}")
    if not body.get("edit") and not body.get("utterance_original"):
        raise ValidationFailed("Provide either edit or utterance_original")
    return await container.jobs.submit(
        "sketch.edit", session_id=sess.id, payload={"version_id": v.id, "body": body}, actor=actor
    )


async def request_previews(
    db: AsyncSession, container: Container, actor: Principal, version_id: str, body: dict[str, Any]
) -> Job:
    v, sess = await _load_version_for(db, actor, version_id, Action.EDIT_SKETCH_OR_SCENE)
    if sess.status != "active":
        raise Conflict(f"Session is {sess.status}", code="session_not_active")
    return await container.jobs.submit(
        "sketch.previews",
        session_id=sess.id,
        payload={"version_id": v.id, "body": body},
        actor=actor,
    )


async def _resolve(
    container: Container,
    db: AsyncSession,
    sess: InterviewSession,
    body: dict[str, Any],
    locks: set[str],
) -> tuple[ResolvedEdit, str]:
    settings = container.settings
    utterance = str(body.get("utterance_original") or "").strip()
    lang = str(body.get("language") or "en")
    english = ""
    if utterance:
        english, _ = await language.to_english(container.providers, utterance, lang)
    edit = body.get("edit")
    if edit:
        return resolve_structured(settings, dict(edit), locks, f"{utterance} {english}"), english
    if not utterance:
        raise ValidationFailed("Provide either edit or utterance_original")
    return await route_utterance(
        container.providers, settings, utterance, english, lang, locks
    ), english


def _edit_source(body: dict[str, Any], resolved: ResolvedEdit) -> str:
    src = str(body.get("source") or "text")
    if resolved.type == "overlay":
        return "accessory"
    if resolved.type == "inpaint":
        return "inpaint"
    return src


async def apply_resolved(
    container: Container,
    db: AsyncSession,
    actor: Principal,
    sess: InterviewSession,
    parent: SketchVersion,
    resolved: ResolvedEdit,
    locks: set[str],
    *,
    source: str,
    utterance: str | None,
    utterance_en: str = "",
    language_code: str = "en",
) -> SketchVersion:
    settings = container.settings
    size = (settings.face_size_px, settings.face_size_px)
    base = await _load_image(container, db, parent.base_master_file_id)
    old_master = await _load_image(container, db, parent.master_file_id)
    lm = landmarks_from_json(parent.landmarks)
    overlays: list[dict[str, Any]] = [dict(o) for o in (parent.overlays or [])]
    sliders: dict[str, float] = dict(parent.sliders or {})
    seed = parent.seed
    mask: np.ndarray | None
    if resolved.type == "geometric":
        disp = compute_displacement(lm, resolved.handle_moves, locks, symmetric=resolved.symmetric)
        new_base, new_lm, moved = warp_image_ex(base, lm, disp.delta, settings.warp_internal_px)
        region = resolved.region.split(",")[0] if resolved.region else "face_shape"
        if resolved.param:
            region = SLIDERS[resolved.param][0]
            sliders[resolved.param] = round(
                sliders.get(resolved.param, 0.0) + float(resolved.amount or 0.0), 4
            )
        # The edit mask covers the region hull plus every pixel the warp actually moved,
        # minus locked regions (which the warp never touches).
        mask = exclude_locked(
            np.maximum(region_mask(new_lm, region, locks, size), moved), new_lm, locks, size
        )
        new_master, _ = overlay_service.apply_overlays(settings, new_base, new_lm, overlays)
        provider_info = {"type": "geometric", "provider": "local"}
    elif resolved.type == "overlay":
        params = dict(resolved.overlay_params)
        if params.pop("remove", False):
            overlays = [o for o in overlays if o.get("overlay_id") != resolved.overlay_id]
        else:
            overlays = [o for o in overlays if o.get("overlay_id") != resolved.overlay_id]
            overlays.append({"overlay_id": resolved.overlay_id, "params": params})
        new_base, new_lm = base, lm
        new_master, _ = overlay_service.apply_overlays(settings, new_base, new_lm, overlays)
        _, mask = overlay_service.apply_overlays(
            settings, new_base, new_lm, [{"overlay_id": resolved.overlay_id, "params": params}]
        )
        provider_info = {"type": "overlay", "provider": "local", "overlay_id": resolved.overlay_id}
    elif resolved.type == "inpaint":
        mask = region_mask(lm, resolved.region, locks, size)
        new_base, prov, model = await inpaint_region(
            container.providers, base, mask, resolved.prompt, seed
        )
        new_lm = lm
        new_master, _ = overlay_service.apply_overlays(settings, new_base, new_lm, overlays)
        provider_info = {
            "type": "inpaint",
            "provider": prov,
            "model": model,
            "prompt_version": prompts.PROMPT_VERSION,
        }
    else:
        raise ValidationFailed(resolved.message or "Edit could not be applied")
    if resolved.router_provider:
        provider_info["router_provider"] = resolved.router_provider
    stab = stability_service.evaluate(
        old_master,
        new_master,
        lm,
        new_lm,
        mask,
        locks,
        max_drift_px=settings.stability_max_drift_px,
        min_ssim=settings.stability_min_ssim_outside,
    ).as_dict()
    edit = {
        **resolved.as_dict(),
        "source": source,
        "language": language_code,
        "utterance_en": utterance_en,
        "locks": sorted(locks),
    }
    return await _create_version(
        db,
        container,
        actor,
        sess,
        parent=parent,
        base_master=new_base,
        master=new_master,
        landmarks=new_lm,
        mask=mask,
        edit=edit,
        edit_source=_edit_source({"source": source}, resolved),
        utterance=utterance,
        seed=seed,
        provider_info=provider_info,
        stability=stab,
        overlays=overlays,
        sliders=sliders,
    )


def _edit_result(v: SketchVersion) -> dict[str, Any]:
    return {
        "status": "created",
        "new_version_id": v.id,
        "parent_version_id": v.parent_id,
        "sketch_file_id": v.sketch_file_id,
        "stability": v.stability,
        "provider_info": v.provider_info,
    }


async def _render_previews(
    container: Container,
    db: AsyncSession,
    actor: Principal,
    sess: InterviewSession,
    parent: SketchVersion,
    resolved: ResolvedEdit,
    locks: set[str],
) -> list[dict[str, Any]]:
    settings = container.settings
    base = await _load_image(container, db, parent.base_master_file_id)
    lm = landmarks_from_json(parent.landmarks)
    overlays = [dict(o) for o in (parent.overlays or [])]
    sign = -1.0 if (resolved.amount or 0) < 0 else 1.0
    out = []
    for amt in PREVIEW_AMOUNTS:
        amount = sign * amt
        moves = (
            slider_moves(resolved.param, amount)
            if resolved.param
            else [
                {
                    "handle": m["handle"],
                    "dx": float(m["dx"]) * amt / 0.05,
                    "dy": float(m["dy"]) * amt / 0.05,
                }
                for m in resolved.handle_moves
            ]
        )
        disp = compute_displacement(lm, moves, locks, symmetric=resolved.symmetric)
        img, _ = warp_image(base, lm, disp.delta, settings.warp_internal_px)
        img, _ = overlay_service.apply_overlays(settings, img, lm + disp.delta, overlays)
        sketch = pencil_sketch(img, settings)
        fid = await _save_png(container, db, sketch, "preview", sess.id, actor.user_id)
        out.append({"amount": amount, "sketch_file_id": fid})
    audit.record(
        db,
        actor,
        "previews.created",
        object_type="sketch_version",
        object_id=parent.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"param": resolved.param, "count": len(out)},
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id,
        "preview.ready",
        {"version_id": parent.id, "param": resolved.param, "previews": out},
    )
    return out


async def sketch_edit_job(ctx: JobContext, db: AsyncSession) -> dict[str, Any]:
    container: Container = ctx.container
    parent = await repo.get_version(db, ctx.payload["version_id"])
    if parent is None:
        raise NotFound("Sketch version not found")
    sess = await db.get(InterviewSession, parent.session_id)
    assert sess is not None
    body = dict(ctx.payload.get("body") or {})
    locks = await repo.locked_features(db, sess.id)
    await ctx.progress(20, "resolving edit")
    resolved, english = await _resolve(container, db, sess, body, locks)
    if resolved.type in ("refused", "unknown"):
        audit.record(
            db,
            ctx.actor,
            "edit.refused",
            object_type="sketch_version",
            object_id=parent.id,
            session_id=sess.id,
            case_id=sess.case_id,
            details={"reason": resolved.type, "region": resolved.region},
        )
        await audit.commit_with_audit(db)
        container.bus.publish(
            sess.id,
            "error",
            {"code": f"edit_{resolved.type}", "message": resolved.message, "version_id": parent.id},
        )
        return {
            "status": resolved.type,
            "message": resolved.message,
            "region": resolved.region,
            "parent_version_id": parent.id,
        }
    if resolved.type == "needs_choice":
        previews = await _render_previews(container, db, ctx.actor, sess, parent, resolved, locks)
        return {
            "status": "needs_choice",
            "message": resolved.message,
            "param": resolved.param,
            "parent_version_id": parent.id,
            "previews": previews,
        }
    await ctx.progress(50, "applying edit")
    v = await apply_resolved(
        container,
        db,
        ctx.actor,
        sess,
        parent,
        resolved,
        locks,
        source=str(body.get("source") or "text"),
        utterance=body.get("utterance_original"),
        utterance_en=english,
        language_code=str(body.get("language") or "en"),
    )
    await ctx.progress(100, "done")
    return _edit_result(v)


async def previews_job(ctx: JobContext, db: AsyncSession) -> dict[str, Any]:
    container: Container = ctx.container
    parent = await repo.get_version(db, ctx.payload["version_id"])
    if parent is None:
        raise NotFound("Sketch version not found")
    sess = await db.get(InterviewSession, parent.session_id)
    assert sess is not None
    body = dict(ctx.payload.get("body") or {})
    locks = await repo.locked_features(db, sess.id)
    resolved, _ = await _resolve(container, db, sess, body, locks)
    if resolved.type in ("refused", "unknown"):
        return {"status": resolved.type, "message": resolved.message}
    if resolved.type not in ("geometric", "needs_choice"):
        raise ValidationFailed("Previews are only available for shape (geometric) edits")
    previews = await _render_previews(container, db, ctx.actor, sess, parent, resolved, locks)
    return {
        "status": "ok",
        "param": resolved.param,
        "parent_version_id": parent.id,
        "previews": previews,
    }


async def apply_edit_from_statement(
    db: AsyncSession, ctx: JobContext, sess: InterviewSession, st: Statement
) -> dict[str, Any]:
    container: Container = ctx.container
    parent = await repo.get_version(db, st.target_version_id or "")
    if parent is None or parent.session_id != sess.id:
        raise NotFound("Target sketch version not found")
    locks = await repo.locked_features(db, sess.id)
    utterance = st.corrected_transcript_original or st.transcript_original
    resolved = await route_utterance(
        container.providers,
        container.settings,
        utterance,
        st.transcript_english,
        st.language,
        locks,
    )
    if resolved.type in ("refused", "unknown"):
        container.bus.publish(
            sess.id, "error", {"code": f"edit_{resolved.type}", "message": resolved.message}
        )
        return {"edit_status": resolved.type, "message": resolved.message}
    if resolved.type == "needs_choice":
        previews = await _render_previews(container, db, ctx.actor, sess, parent, resolved, locks)
        return {"edit_status": "needs_choice", "previews": previews, "param": resolved.param}
    v = await apply_resolved(
        container,
        db,
        ctx.actor,
        sess,
        parent,
        resolved,
        locks,
        source="voice",
        utterance=utterance,
        utterance_en=st.transcript_english,
        language_code=st.language,
    )
    return {"edit_status": "created", **_edit_result(v)}


# ---- reads ---------------------------------------------------------------------------------------


async def get_tree(db: AsyncSession, actor: Principal, session_id: str) -> list[dict[str, Any]]:
    sess, _ = await case_service.load_session(db, actor, session_id)
    versions = await repo.list_versions(db, sess.id)
    audit.record(
        db,
        actor,
        "sketch_tree.viewed",
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
            "edit_source": v.edit_source,
            "edit_type": (v.edit or {}).get("type"),
            "sketch_file_id": v.sketch_file_id,
            "witness_rating": v.witness_rating,
            "created_by_role": v.created_by_role,
            "created_at": v.created_at,
            "stability_warning": bool((v.stability or {}).get("warning")),
            "utterance_original": v.utterance_original,
        }
        for v in versions
    ]


async def get_version(db: AsyncSession, actor: Principal, version_id: str) -> dict[str, Any]:
    v, sess = await _load_version_for(db, actor, version_id)
    from app.db.repositories.cases import scope_for_session

    scope = await scope_for_session(db, sess)
    staff_master = actor.kind == "user" and can(actor, Action.VIEW_MASTER_IMAGE, scope)
    audit.record(
        db,
        actor,
        "version.viewed",
        object_type="sketch_version",
        object_id=v.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"master": staff_master},
    )
    await audit.commit_with_audit(db)
    return _version_payload(v, staff_master)


async def rate_version(
    db: AsyncSession, actor: Principal, version_id: str, rating: str
) -> SketchVersion:
    if rating not in ("closer", "further"):
        raise ValidationFailed("rating must be closer or further")
    v, sess = await _load_version_for(db, actor, version_id, Action.EDIT_SKETCH_OR_SCENE)
    v.witness_rating = rating
    audit.record(
        db,
        actor,
        "version.rated",
        object_type="sketch_version",
        object_id=v.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"rating": rating},
    )
    await audit.commit_with_audit(db)
    return v


async def get_locks(db: AsyncSession, actor: Principal, session_id: str) -> list[dict[str, Any]]:
    sess, _ = await case_service.load_session(db, actor, session_id)
    locks = await repo.get_locks(db, sess.id)
    audit.record(
        db,
        actor,
        "locks.viewed",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
    )
    await audit.commit_with_audit(db)
    return [
        {
            "feature": f,
            "locked": locks[f].locked if f in locks else False,
            "confidence": locks[f].confidence if f in locks else None,
            "updated_by_role": locks[f].updated_by_role if f in locks else None,
            "updated_at": locks[f].updated_at if f in locks else None,
        }
        for f in FEATURES
    ]


async def put_locks(
    db: AsyncSession, actor: Principal, session_id: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    sess, _ = await case_service.load_session(db, actor, session_id, Action.EDIT_SKETCH_OR_SCENE)
    if sess.status != "active":
        raise Conflict(f"Session is {sess.status}", code="session_not_active")
    changed = []
    for item in items:
        feature = str(item.get("feature"))
        if feature not in FEATURES:
            raise ValidationFailed(f"Unknown feature {feature}")
        conf = item.get("confidence")
        if conf is not None and conf not in CONFIDENCES:
            raise ValidationFailed(f"Invalid confidence {conf}")
        await repo.set_lock(
            db, sess.id, feature, locked=item.get("locked"), confidence=conf, role=actor.role
        )
        changed.append({"feature": feature, "locked": item.get("locked"), "confidence": conf})
    audit.record(
        db,
        actor,
        "locks.updated",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"changes": changed},
    )
    await audit.commit_with_audit(db)
    locks = await repo.get_locks(db, sess.id)
    return [
        {
            "feature": f,
            "locked": locks[f].locked if f in locks else False,
            "confidence": locks[f].confidence if f in locks else None,
            "updated_by_role": locks[f].updated_by_role if f in locks else None,
            "updated_at": locks[f].updated_at if f in locks else None,
        }
        for f in FEATURES
    ]


async def compare(
    db: AsyncSession, container: Container, actor: Principal, a_id: str, b_id: str
) -> dict[str, Any]:
    a, sess = await _load_version_for(db, actor, a_id)
    b = await repo.get_version(db, b_id)
    if b is None or b.session_id != sess.id:
        raise NotFound("Second version not found in this session")
    img_a = await _load_image(container, db, a.master_file_id)
    img_b = await _load_image(container, db, b.master_file_id)
    lm_a, lm_b = landmarks_from_json(a.landmarks), landmarks_from_json(b.landmarks)
    locks = await repo.locked_features(db, sess.id)
    mask = None
    if b.mask_file_id:
        mask = (await _load_image(container, db, b.mask_file_id, gray=True)).astype(
            np.float32
        ) / 255
    stab = stability_service.evaluate(
        img_a,
        img_b,
        lm_a,
        lm_b,
        mask,
        locks,
        max_drift_px=container.settings.stability_max_drift_px,
        min_ssim=container.settings.stability_min_ssim_outside,
    ).as_dict()
    drift = np.linalg.norm((lm_b - lm_a) * container.settings.face_size_px, axis=1)
    audit.record(
        db,
        actor,
        "versions.compared",
        object_type="sketch_version",
        object_id=a.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"other": b.id},
    )
    await audit.commit_with_audit(db)
    sliders_a, sliders_b = a.sliders or {}, b.sliders or {}
    return {
        "a": a.id,
        "b": b.id,
        "stability": stab,
        "landmark_drift_px": {
            "mean": round(float(drift.mean()), 3),
            "max": round(float(drift.max()), 3),
        },
        "slider_delta": {
            k: round(float(sliders_b.get(k, 0)) - float(sliders_a.get(k, 0)), 4)
            for k in set(sliders_a) | set(sliders_b)
        },
        "overlays_a": a.overlays or [],
        "overlays_b": b.overlays or [],
    }


def overlay_catalog(container: Container) -> list[dict[str, Any]]:
    return overlay_service.catalog_public(container.settings)


def check_edit_permission(actor: Principal) -> None:
    if actor.kind == "user" and actor.role not in ("officer", "artist"):
        raise Forbidden("Only witnesses, officers and artists can edit the sketch")


# ---- live (client-drawn) sketch ------------------------------------------------------------


async def save_live_sketch(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    session_id: str,
    png: bytes,
    params: dict[str, Any],
) -> SketchVersion:
    """Store the pencil sketch drawn live during the voice interview as a sketch version.

    The witness approved exactly this drawing, so it is stored as-is (master = sketch = the
    uploaded PNG) with the drawing parameters in ``edit`` so it can be redrawn or audited.
    """
    from app.services.sketch.landmarks import load_template
    from app.services.storage import sniff_image

    sess, _ = await case_service.require_open_session(db, actor, session_id)
    if len(png) > container.settings.max_image_mb * 1024 * 1024:
        from app.core.errors import PayloadTooLarge

        raise PayloadTooLarge("Sketch image too large")
    if sniff_image(png) != "image/png":
        from app.core.errors import UnsupportedMedia

        raise UnsupportedMedia("The live sketch must be a PNG")
    parent = await repo.latest_version(db, sess.id)
    rec = await container.files.save(
        db, png, kind="sketch_image", mime="image/png", session_id=sess.id, created_by=actor.user_id
    )
    master = await container.files.save(
        db, png, kind="master_image", mime="image/png", session_id=sess.id, created_by=actor.user_id
    )
    v = SketchVersion(
        session_id=sess.id,
        parent_id=parent.id if parent else None,
        master_file_id=master.id,
        base_master_file_id=master.id,
        sketch_file_id=rec.id,
        mask_file_id=None,
        landmarks=landmarks_to_json(load_template().landmarks),
        edit={"type": "live", "params": params},
        edit_source="voice",
        utterance_original=None,
        seed=None,
        provider_info={"type": "live_sketch", "provider": "browser"},
        stability={},
        overlays=[],
        sliders={},
        created_by_user_id=actor.user_id,
        created_by_role=actor.role,
    )
    await repo.add_version(db, v)
    audit.record(
        db,
        actor,
        "version.created",
        object_type="sketch_version",
        object_id=v.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={"parent_id": v.parent_id, "edit_source": "voice", "edit_type": "live"},
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id,
        "version.created",
        {
            "version_id": v.id,
            "parent_id": v.parent_id,
            "sketch_file_id": v.sketch_file_id,
            "edit_source": "voice",
        },
    )
    return v
