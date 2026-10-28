from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sessions import DisplayEvent, Export, InterviewSession, Signoff


async def get_session(db: AsyncSession, session_id: str) -> InterviewSession | None:
    return await db.get(InterviewSession, session_id)


async def get_session_by_token_hash(db: AsyncSession, token_hash: str) -> InterviewSession | None:
    res = await db.execute(
        select(InterviewSession).where(InterviewSession.witness_token_hash == token_hash)
    )
    return res.scalar_one_or_none()


async def add_session(db: AsyncSession, session: InterviewSession) -> InterviewSession:
    db.add(session)
    return session


async def list_sessions_for_case(db: AsyncSession, case_id: str) -> list[InterviewSession]:
    res = await db.execute(
        select(InterviewSession)
        .where(InterviewSession.case_id == case_id)
        .order_by(InterviewSession.started_at)
    )
    return list(res.scalars())


async def add_display_event(db: AsyncSession, ev: DisplayEvent) -> DisplayEvent:
    db.add(ev)
    return ev


async def count_display_events(db: AsyncSession, session_id: str) -> int:
    res = await db.execute(
        select(func.count()).select_from(DisplayEvent).where(DisplayEvent.session_id == session_id)
    )
    return int(res.scalar() or 0)


async def add_signoff(db: AsyncSession, s: Signoff) -> Signoff:
    db.add(s)
    return s


async def latest_signoff(db: AsyncSession, session_id: str) -> Signoff | None:
    res = await db.execute(
        select(Signoff).where(Signoff.session_id == session_id).order_by(Signoff.created_at.desc())
    )
    return res.scalars().first()


async def add_export(db: AsyncSession, e: Export) -> Export:
    db.add(e)
    return e


async def get_export(db: AsyncSession, export_id: str) -> Export | None:
    return await db.get(Export, export_id)


async def list_exports(db: AsyncSession, session_id: str) -> list[Export]:
    res = await db.execute(
        select(Export).where(Export.session_id == session_id).order_by(Export.created_at)
    )
    return list(res.scalars())
