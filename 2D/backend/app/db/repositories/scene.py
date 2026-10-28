from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.scene import SceneVersion


async def add_version(db: AsyncSession, v: SceneVersion) -> SceneVersion:
    db.add(v)
    return v


async def get_version(db: AsyncSession, version_id: str) -> SceneVersion | None:
    return await db.get(SceneVersion, version_id)


async def list_versions(db: AsyncSession, session_id: str) -> list[SceneVersion]:
    res = await db.execute(
        select(SceneVersion)
        .where(SceneVersion.session_id == session_id)
        .order_by(SceneVersion.created_at.asc())
    )
    return list(res.scalars())


async def latest_version(db: AsyncSession, session_id: str) -> SceneVersion | None:
    res = await db.execute(
        select(SceneVersion)
        .where(SceneVersion.session_id == session_id)
        .order_by(SceneVersion.created_at.desc())
    )
    return res.scalars().first()
