from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Scope
from app.db.models.cases import Case, CaseAssignment, Witness
from app.db.models.sessions import InterviewSession
from app.db.models.users import User
from app.db.repositories.common import apply_cursor, page


async def get_case(db: AsyncSession, case_id: str) -> Case | None:
    return await db.get(Case, case_id)


async def add_case(db: AsyncSession, case: Case) -> Case:
    db.add(case)
    return case


async def list_cases_for_user(
    db: AsyncSession, user: User, cursor: str | None, limit: int
) -> tuple[list[Case], str | None]:
    stmt = select(Case)
    if user.role == "supervisor":
        # jurisdiction = any case whose creator belongs to the supervisor's jurisdiction
        stmt = stmt.join(User, User.id == Case.created_by).where(
            User.jurisdiction == user.jurisdiction
        )
    elif user.role in ("officer", "artist"):
        assigned = select(CaseAssignment.case_id).where(CaseAssignment.user_id == user.id)
        stmt = stmt.where((Case.created_by == user.id) | (Case.id.in_(assigned)))
    else:
        stmt = stmt.where(Case.id == "")  # admins see no cases
    stmt = apply_cursor(stmt, Case.created_at, Case.id, cursor, limit)
    rows = list((await db.execute(stmt)).scalars())
    return page(rows, limit)


async def list_assignments(db: AsyncSession, case_id: str) -> list[CaseAssignment]:
    res = await db.execute(select(CaseAssignment).where(CaseAssignment.case_id == case_id))
    return list(res.scalars())


async def upsert_assignment(
    db: AsyncSession, case_id: str, user_id: str, role_on_case: str
) -> CaseAssignment:
    existing = await db.get(CaseAssignment, {"case_id": case_id, "user_id": user_id})
    if existing:
        existing.role_on_case = role_on_case
        return existing
    a = CaseAssignment(case_id=case_id, user_id=user_id, role_on_case=role_on_case)
    db.add(a)
    return a


async def add_witness(db: AsyncSession, witness: Witness) -> Witness:
    db.add(witness)
    return witness


async def get_witness(db: AsyncSession, witness_id: str) -> Witness | None:
    return await db.get(Witness, witness_id)


async def list_witnesses(db: AsyncSession, case_id: str) -> list[Witness]:
    res = await db.execute(
        select(Witness).where(Witness.case_id == case_id).order_by(Witness.created_at)
    )
    return list(res.scalars())


async def scope_for_case(db: AsyncSession, case: Case, session_id: str | None = None) -> Scope:
    """Build the RBAC scope for a case: station, creator jurisdiction, assignees."""
    creator = await db.get(User, case.created_by)
    assignments = await list_assignments(db, case.id)
    return Scope(
        case_id=case.id,
        station=case.station,
        jurisdiction=creator.jurisdiction if creator else "",
        assigned_user_ids={a.user_id for a in assignments},
        created_by=case.created_by,
        session_id=session_id,
    )


async def scope_for_session(db: AsyncSession, session: InterviewSession) -> Scope:
    case = await get_case(db, session.case_id)
    assert case is not None
    return await scope_for_case(db, case, session_id=session.id)
