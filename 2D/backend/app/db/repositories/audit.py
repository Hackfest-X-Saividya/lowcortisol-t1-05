from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditLog


async def list_audit(
    db: AsyncSession,
    *,
    case_ids: set[str] | None = None,
    session_id: str | None = None,
    action: str | None = None,
    before_id: int | None = None,
    limit: int = 50,
) -> tuple[list[AuditLog], int | None]:
    """Keyset pagination on the integer id (descending). Returns rows and next cursor id."""
    stmt = select(AuditLog)
    if case_ids is not None:
        stmt = stmt.where(AuditLog.case_id.in_(case_ids))
    if session_id:
        stmt = stmt.where(AuditLog.session_id == session_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    stmt = stmt.order_by(AuditLog.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars())
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor
