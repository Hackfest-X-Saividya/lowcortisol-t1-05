from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.statements import FeatureSheet, Question, Statement


async def add_statement(db: AsyncSession, st: Statement) -> Statement:
    db.add(st)
    return st


async def get_statement(db: AsyncSession, statement_id: str) -> Statement | None:
    return await db.get(Statement, statement_id)


async def list_statements(
    db: AsyncSession, session_id: str, kind: str | None = None
) -> list[Statement]:
    stmt = select(Statement).where(Statement.session_id == session_id)
    if kind:
        stmt = stmt.where(Statement.kind == kind)
    res = await db.execute(stmt.order_by(Statement.created_at.asc()))
    return list(res.scalars())


async def has_free_recall(db: AsyncSession, session_id: str) -> bool:
    res = await db.execute(
        select(Statement.id)
        .where(
            Statement.session_id == session_id,
            Statement.kind == "free_recall",
            Statement.status.in_(("transcribed", "extracted")),
        )
        .limit(1)
    )
    return res.scalar() is not None


async def get_feature_sheet(db: AsyncSession, session_id: str) -> FeatureSheet | None:
    res = await db.execute(select(FeatureSheet).where(FeatureSheet.session_id == session_id))
    return res.scalar_one_or_none()


async def get_or_create_feature_sheet(db: AsyncSession, session_id: str) -> FeatureSheet:
    fs = await get_feature_sheet(db, session_id)
    if fs is None:
        fs = FeatureSheet(session_id=session_id, sheet={})
        db.add(fs)
    return fs


async def add_question(db: AsyncSession, q: Question) -> Question:
    db.add(q)
    return q


async def get_question(db: AsyncSession, question_id: str) -> Question | None:
    return await db.get(Question, question_id)


async def list_questions(db: AsyncSession, session_id: str) -> list[Question]:
    res = await db.execute(
        select(Question).where(Question.session_id == session_id).order_by(Question.asked_at.asc())
    )
    return list(res.scalars())


async def open_question(db: AsyncSession, session_id: str) -> Question | None:
    res = await db.execute(
        select(Question)
        .where(Question.session_id == session_id, Question.answered_at.is_(None))
        .order_by(Question.asked_at.desc())
    )
    return res.scalars().first()
