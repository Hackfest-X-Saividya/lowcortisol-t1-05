"""Cases, assignments, witnesses, sessions and display events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import audit
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.rbac import Action, Scope, can, require
from app.core.security import Principal, new_opaque_token, token_hash, witness_token_expiry
from app.db.models.cases import Case, Witness
from app.db.models.sessions import DisplayEvent, InterviewSession
from app.db.models.users import User
from app.db.repositories import cases as repo
from app.db.repositories import sessions as session_repo
from app.db.repositories import sketch as sketch_repo
from app.db.repositories import statements as statement_repo
from app.schemas.cases import AssignmentCreate, CaseCreate, CaseUpdate, WitnessCreate
from app.schemas.sessions import DisplayEventCreate

# ---- cases ---------------------------------------------------------------------------------


async def create_case(db: AsyncSession, actor: Principal, data: CaseCreate) -> Case:
    station = data.station or actor.station
    require(actor, Action.CREATE_CASE, Scope(station=station))
    case = Case(
        case_number=data.case_number,
        station=station,
        crime_type=data.crime_type,
        occurred_at=data.occurred_at,
        location_text=data.location_text,
        created_by=actor.user_id or "",
    )
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    dup = await db.execute(
        select(Case.id).where(Case.station == station, Case.case_number == data.case_number)
    )
    if dup.scalar() is not None:
        raise Conflict("A case with this number already exists at this station")
    await repo.add_case(db, case)
    await repo.upsert_assignment(db, case.id, actor.user_id or "", "lead")
    audit.record(
        db,
        actor,
        "case.created",
        object_type="case",
        object_id=case.id,
        case_id=case.id,
        details={"case_number": case.case_number},
    )
    try:
        await audit.commit_with_audit(db)
    except IntegrityError:
        raise Conflict("A case with this number already exists at this station")
    return case


async def load_case(
    db: AsyncSession, actor: Principal, case_id: str, action: Action = Action.VIEW_CASE
) -> tuple[Case, Scope]:
    case = await repo.get_case(db, case_id)
    if case is None:
        raise NotFound("Case not found")
    scope = await repo.scope_for_case(db, case, session_id=actor.session_id)
    if not can(actor, action, scope):
        raise Forbidden("You are not assigned to this case")
    return case, scope


async def get_case(db: AsyncSession, actor: Principal, case_id: str) -> dict[str, Any]:
    case, _ = await load_case(db, actor, case_id)
    assignments = await repo.list_assignments(db, case.id)
    witnesses = await repo.list_witnesses(db, case.id)
    sessions = await session_repo.list_sessions_for_case(db, case.id)
    audit.record(db, actor, "case.viewed", object_type="case", object_id=case.id, case_id=case.id)
    await audit.commit_with_audit(db)
    return {
        **{c.name: getattr(case, c.name) for c in Case.__table__.columns},
        "assignments": assignments,
        "witnesses": witnesses,
        "session_ids": [s.id for s in sessions],
    }


async def list_cases(
    db: AsyncSession, actor: Principal, cursor: str | None, limit: int
) -> tuple[list[Case], str | None]:
    user = await db.get(User, actor.user_id or "")
    if user is None:
        raise Forbidden("Staff only")
    rows, next_cursor = await repo.list_cases_for_user(db, user, cursor, limit)
    audit.record(db, actor, "case.listed", object_type="case", details={"count": len(rows)})
    await audit.commit_with_audit(db)
    return rows, next_cursor


async def update_case(db: AsyncSession, actor: Principal, case_id: str, data: CaseUpdate) -> Case:
    case, _ = await load_case(db, actor, case_id, Action.EDIT_SKETCH_OR_SCENE)
    if actor.kind != "user":
        raise Forbidden("Staff only")
    changed = []
    for field in ("crime_type", "occurred_at", "location_text", "status"):
        val = getattr(data, field)
        if val is not None:
            setattr(case, field, val)
            changed.append(field)
    audit.record(
        db,
        actor,
        "case.updated",
        object_type="case",
        object_id=case.id,
        case_id=case.id,
        details={"fields": changed},
    )
    await audit.commit_with_audit(db)
    return case


async def assign(db: AsyncSession, actor: Principal, case_id: str, data: AssignmentCreate) -> Any:
    case, scope = await load_case(db, actor, case_id)
    if actor.role != "officer" or not scope.is_assigned(actor.user_id):
        raise Forbidden("Only an assigned officer can assign staff")
    target = await db.get(User, data.user_id)
    if target is None or not target.is_active:
        raise NotFound("User not found")
    a = await repo.upsert_assignment(db, case.id, data.user_id, data.role_on_case)
    audit.record(
        db,
        actor,
        "case.assigned",
        object_type="case",
        object_id=case.id,
        case_id=case.id,
        details={"user_id": data.user_id, "role": data.role_on_case},
    )
    await audit.commit_with_audit(db)
    return a


# ---- witnesses ---------------------------------------------------------------------------------


async def add_witness(
    db: AsyncSession, actor: Principal, case_id: str, data: WitnessCreate
) -> Witness:
    case, scope = await load_case(db, actor, case_id)
    require(actor, Action.ADD_WITNESS, Scope(station=case.station))
    if not scope.is_assigned(actor.user_id):
        raise Forbidden("You are not assigned to this case")
    w = Witness(
        case_id=case.id,
        display_name=data.display_name,
        preferred_language=data.preferred_language,
        consent_given=data.consent_given,
        consent_at=datetime.now(UTC) if data.consent_given else None,
        consent_recorded_by=actor.user_id if data.consent_given else None,
        consent_note=data.consent_note,
    )
    await repo.add_witness(db, w)
    audit.record(
        db,
        actor,
        "witness.added",
        object_type="witness",
        object_id=w.id,
        case_id=case.id,
        details={"consent_given": w.consent_given, "language": w.preferred_language},
    )
    await audit.commit_with_audit(db)
    return w


# ---- sessions ---------------------------------------------------------------------------------


async def create_session(
    db: AsyncSession, settings: Settings, actor: Principal, case_id: str, witness_id: str
) -> tuple[InterviewSession, str]:
    case, scope = await load_case(db, actor, case_id)
    require(actor, Action.START_SESSION, Scope(station=case.station))
    if not scope.is_assigned(actor.user_id):
        raise Forbidden("You are not assigned to this case")
    witness = await repo.get_witness(db, witness_id)
    if witness is None or witness.case_id != case.id:
        raise NotFound("Witness not found on this case")
    if not witness.consent_given:
        raise ValidationFailed(
            "Witness consent must be recorded before starting a session", code="consent_required"
        )
    token = new_opaque_token(32)
    sess = InterviewSession(
        case_id=case.id,
        witness_id=witness.id,
        officer_id=actor.user_id or "",
        witness_token_hash=token_hash(token),
        witness_token_expires_at=witness_token_expiry(settings),
        status="active",
    )
    await session_repo.add_session(db, sess)
    audit.record(
        db,
        actor,
        "session.started",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=case.id,
        details={"witness_id": witness.id},
    )
    await audit.commit_with_audit(db)
    return sess, token


async def load_session(
    db: AsyncSession, actor: Principal, session_id: str, action: Action = Action.VIEW_CASE
) -> tuple[InterviewSession, Scope]:
    sess = await session_repo.get_session(db, session_id)
    if sess is None:
        raise NotFound("Session not found")
    scope = await repo.scope_for_session(db, sess)
    if not can(actor, action, scope):
        raise Forbidden("No access to this session")
    return sess, scope


async def get_session_detail(db: AsyncSession, actor: Principal, session_id: str) -> dict[str, Any]:
    sess, _ = await load_session(db, actor, session_id)
    from app.db.repositories import scene as scene_repo

    latest_sketch = await sketch_repo.latest_version(db, sess.id)
    latest_scene = await scene_repo.latest_version(db, sess.id)
    locks = await sketch_repo.get_locks(db, sess.id)
    questions = await statement_repo.list_questions(db, sess.id)
    audit.record(
        db,
        actor,
        "session.viewed",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
    )
    await audit.commit_with_audit(db)
    return {
        **{c.name: getattr(sess, c.name) for c in InterviewSession.__table__.columns},
        "has_free_recall": await statement_repo.has_free_recall(db, sess.id),
        "latest_sketch_version_id": latest_sketch.id if latest_sketch else None,
        "latest_scene_version_id": latest_scene.id if latest_scene else None,
        "locks": {f: {"locked": lk.locked, "confidence": lk.confidence} for f, lk in locks.items()},
        "question_count": len(questions),
    }


async def set_session_status(
    db: AsyncSession, actor: Principal, session_id: str, new_status: str
) -> InterviewSession:
    sess, scope = await load_session(db, actor, session_id)
    if actor.kind != "user" or not scope.is_assigned(actor.user_id):
        raise Forbidden("Only the assigned officer can change session status")
    allowed = {
        "pause": ({"active"}, "paused"),
        "resume": ({"paused"}, "active"),
        "close": ({"active", "paused", "signed_off"}, "closed"),
    }
    from_states, to_state = allowed[new_status]
    if sess.status not in from_states:
        raise Conflict(f"Cannot {new_status} a session in status {sess.status}")
    sess.status = to_state
    if to_state == "closed":
        sess.ended_at = datetime.now(UTC)
        sess.witness_token_expires_at = datetime.now(UTC)
    audit.record(
        db,
        actor,
        f"session.{new_status}",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
    )
    await audit.commit_with_audit(db)
    return sess


async def require_open_session(
    db: AsyncSession,
    actor: Principal,
    session_id: str,
    action: Action = Action.EDIT_SKETCH_OR_SCENE,
) -> tuple[InterviewSession, Scope]:
    sess, scope = await load_session(db, actor, session_id, action)
    if sess.status not in ("active",):
        raise Conflict(f"Session is {sess.status}", code="session_not_active")
    return sess, scope


# ---- display events --------------------------------------------------------------------------


async def record_display_event(
    db: AsyncSession, actor: Principal, session_id: str, data: DisplayEventCreate
) -> DisplayEvent:
    sess, _ = await load_session(db, actor, session_id, Action.EDIT_SKETCH_OR_SCENE)
    if data.sketch_version_id:
        v = await sketch_repo.get_version(db, data.sketch_version_id)
        if v is None or v.session_id != sess.id:
            raise NotFound("Sketch version not found")
    ev = DisplayEvent(
        session_id=sess.id,
        sketch_version_id=data.sketch_version_id,
        scene_version_id=data.scene_version_id,
        screen=data.screen,
        shown_at=datetime.now(UTC),
    )
    await session_repo.add_display_event(db, ev)
    if data.sketch_version_id and sess.first_image_shown_at is None:
        sess.first_image_shown_at = ev.shown_at
    audit.record(
        db,
        actor,
        "image.shown",
        object_type="display_event",
        object_id=ev.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={
            "sketch_version_id": data.sketch_version_id,
            "scene_version_id": data.scene_version_id,
            "screen": data.screen,
        },
    )
    await audit.commit_with_audit(db)
    return ev
