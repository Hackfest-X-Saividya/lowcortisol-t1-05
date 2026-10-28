"""Audit log viewing and chain verification (with their own audit entries)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import Forbidden
from app.core.rbac import Action, can
from app.core.security import Principal
from app.db.models.audit import AuditLog
from app.db.models.cases import Case, CaseAssignment
from app.db.models.users import User
from app.db.repositories import audit as repo


async def _visible_case_ids(db: AsyncSession, actor: Principal) -> set[str]:
    if actor.role == "officer":
        assigned = select(CaseAssignment.case_id).where(CaseAssignment.user_id == actor.user_id)
        res = await db.execute(
            select(Case.id).where((Case.created_by == actor.user_id) | (Case.id.in_(assigned)))
        )
        return {r for r in res.scalars()}
    if actor.role == "supervisor":
        res = await db.execute(
            select(Case.id)
            .join(User, User.id == Case.created_by)
            .where(User.jurisdiction == actor.jurisdiction)
        )
        return {r for r in res.scalars()}
    return set()


async def list_audit(
    db: AsyncSession,
    actor: Principal,
    *,
    case_id: str | None,
    session_id: str | None,
    action: str | None,
    cursor: int | None,
    limit: int,
) -> tuple[list[AuditLog], int | None]:
    if actor.role not in ("officer", "supervisor"):
        raise Forbidden("Not allowed to view the audit log")
    visible = await _visible_case_ids(db, actor)
    if case_id:
        if case_id not in visible:
            raise Forbidden("Not allowed to view this case's audit log")
        visible = {case_id}
    rows, next_cursor = await repo.list_audit(
        db,
        case_ids=visible,
        session_id=session_id,
        action=action,
        before_id=cursor,
        limit=limit,
    )
    audit.record(
        db,
        actor,
        "audit.viewed",
        object_type="audit_log",
        details={"case_id": case_id, "count": len(rows)},
    )
    await audit.commit_with_audit(db)
    return rows, next_cursor


async def verify(db: AsyncSession, actor: Principal) -> audit.VerifyResult:
    if not can(actor, Action.VERIFY_AUDIT):
        raise Forbidden("Only supervisors and admins can verify the audit chain")
    result = await audit.verify_chain(db)
    audit.record(db, actor, "audit.verified", object_type="audit_log", details=result.as_dict())
    await audit.commit_with_audit(db)
    return result
