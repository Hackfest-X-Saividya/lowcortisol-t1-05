from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.users import RefreshToken, User


async def get_user(db: AsyncSession, user_id: str) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    res = await db.execute(select(User).where(User.username == username))
    return res.scalar_one_or_none()


async def list_users(db: AsyncSession) -> list[User]:
    res = await db.execute(select(User).order_by(User.created_at.asc()))
    return list(res.scalars())


async def add_user(db: AsyncSession, user: User) -> User:
    db.add(user)
    return user


async def add_refresh_token(
    db: AsyncSession, user_id: str, token_hash: str, expires_at: datetime
) -> RefreshToken:
    rt = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(rt)
    return rt


async def get_refresh_token(db: AsyncSession, token_hash: str) -> RefreshToken | None:
    res = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    return res.scalar_one_or_none()
