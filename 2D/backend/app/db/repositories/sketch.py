from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sketch import FEATURES, FeatureLock, SketchVersion


async def add_version(db: AsyncSession, v: SketchVersion) -> SketchVersion:
    db.add(v)
    return v


async def get_version(db: AsyncSession, version_id: str) -> SketchVersion | None:
    return await db.get(SketchVersion, version_id)


async def list_versions(db: AsyncSession, session_id: str) -> list[SketchVersion]:
    res = await db.execute(
        select(SketchVersion)
        .where(SketchVersion.session_id == session_id)
        .order_by(SketchVersion.created_at.asc())
    )
    return list(res.scalars())


async def latest_version(db: AsyncSession, session_id: str) -> SketchVersion | None:
    res = await db.execute(
        select(SketchVersion)
        .where(SketchVersion.session_id == session_id)
        .order_by(SketchVersion.created_at.desc())
    )
    return res.scalars().first()


async def get_locks(db: AsyncSession, session_id: str) -> dict[str, FeatureLock]:
    res = await db.execute(select(FeatureLock).where(FeatureLock.session_id == session_id))
    return {lock.feature: lock for lock in res.scalars()}


async def locked_features(db: AsyncSession, session_id: str) -> set[str]:
    locks = await get_locks(db, session_id)
    return {f for f, lock in locks.items() if lock.locked}


async def set_lock(
    db: AsyncSession,
    session_id: str,
    feature: str,
    *,
    locked: bool | None,
    confidence: str | None,
    role: str,
) -> FeatureLock:
    if feature not in FEATURES:
        from app.core.errors import ValidationFailed

        raise ValidationFailed(f"Unknown feature {feature}")
    lock = await db.get(FeatureLock, {"session_id": session_id, "feature": feature})
    if lock is None:
        lock = FeatureLock(session_id=session_id, feature=feature, locked=False)
        db.add(lock)
    if locked is not None:
        lock.locked = locked
    if confidence is not None:
        lock.confidence = confidence
    lock.updated_by_role = role
    return lock
