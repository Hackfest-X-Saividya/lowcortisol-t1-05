"""Witness sign-off with per-feature confidence."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import audit
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.rbac import Action
from app.core.security import Principal
from app.db.models.sessions import Signoff
from app.db.models.sketch import CONFIDENCES, FEATURES
from app.db.repositories import scene as scene_repo
from app.db.repositories import sessions as session_repo
from app.db.repositories import sketch as sketch_repo
from app.schemas.sessions import SignoffCreate
from app.services import cases as case_service


async def sign_off(
    db: AsyncSession, container: Container, actor: Principal, session_id: str, data: SignoffCreate
) -> Signoff:
    sess, _ = await case_service.load_session(db, actor, session_id, Action.EDIT_SKETCH_OR_SCENE)
    if sess.status not in ("active", "paused"):
        raise Conflict(f"Session is {sess.status}", code="session_not_active")
    for feature, conf in data.confidences.items():
        if feature not in FEATURES:
            raise ValidationFailed(f"Unknown feature {feature}")
        if conf not in CONFIDENCES:
            raise ValidationFailed(f"Invalid confidence {conf} for {feature}")
    sketch_id = data.sketch_version_id
    if sketch_id is None:
        latest = await sketch_repo.latest_version(db, sess.id)
        sketch_id = latest.id if latest else None
    elif (v := await sketch_repo.get_version(db, sketch_id)) is None or v.session_id != sess.id:
        raise NotFound("Sketch version not found")
    scene_id = data.scene_version_id
    if scene_id is None:
        latest_scene = await scene_repo.latest_version(db, sess.id)
        scene_id = latest_scene.id if latest_scene else None
    elif (sv := await scene_repo.get_version(db, scene_id)) is None or sv.session_id != sess.id:
        raise NotFound("Scene version not found")
    for feature, conf in data.confidences.items():
        await sketch_repo.set_lock(
            db, sess.id, feature, locked=None, confidence=conf, role=actor.role
        )
    s = Signoff(
        session_id=sess.id,
        sketch_version_id=sketch_id,
        scene_version_id=scene_id,
        confidences=dict(data.confidences),
        witness_statement=data.witness_statement,
    )
    await session_repo.add_signoff(db, s)
    sess.status = "signed_off"
    sess.ended_at = datetime.now(UTC)
    sess.witness_token_expires_at = datetime.now(UTC)
    audit.record(
        db,
        actor,
        "session.signed_off",
        object_type="signoff",
        object_id=s.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={
            "sketch_version_id": sketch_id,
            "scene_version_id": scene_id,
            "confidences": dict(data.confidences),
        },
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id, "job.progress", {"kind": "signoff", "status": "done", "signoff_id": s.id}
    )
    return s
