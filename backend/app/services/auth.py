"""Login, refresh, logout, user management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import audit
from app.core.errors import Conflict, Locked, NotFound, Unauthorized
from app.core.security import (
    Principal,
    create_access_token,
    hash_password,
    new_opaque_token,
    refresh_expiry,
    token_hash,
    verify_password,
)
from app.db.models.users import User
from app.db.repositories import users as repo
from app.schemas.admin import UserCreate, UserUpdate


async def login(
    db: AsyncSession, settings: Settings, actor: Principal, username: str, password: str
) -> tuple[User, str, str]:
    user = await repo.get_user_by_username(db, username)
    now = datetime.now(UTC)
    if user is None:
        audit.record(
            db, actor, "auth.login_failed", object_type="user", details={"reason": "unknown_user"}
        )
        await audit.commit_with_audit(db)
        raise Unauthorized("Invalid username or password", code="invalid_credentials")
    if user.locked_until and user.locked_until > now:
        audit.record(db, actor, "auth.login_locked", object_type="user", object_id=user.id)
        await audit.commit_with_audit(db)
        raise Locked(
            "Account locked. Try again later.",
            code="account_locked",
            details={"locked_until": user.locked_until.isoformat()},
        )
    if not user.is_active or not verify_password(user.password_hash, password):
        user.failed_logins += 1
        reason = "inactive" if not user.is_active else "bad_password"
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
            reason = "locked"
        audit.record(
            db,
            actor,
            "auth.login_failed",
            object_type="user",
            object_id=user.id,
            details={"reason": reason},
        )
        await audit.commit_with_audit(db)
        raise Unauthorized("Invalid username or password", code="invalid_credentials")

    user.failed_logins = 0
    user.locked_until = None
    access = create_access_token(settings, user.id, user.role)
    refresh = new_opaque_token(48)
    await repo.add_refresh_token(db, user.id, token_hash(refresh), refresh_expiry(settings))
    acting = Principal(
        kind="user",
        user_id=user.id,
        role=user.role,
        station=user.station,
        jurisdiction=user.jurisdiction,
        ip=actor.ip,
        user_agent=actor.user_agent,
        request_id=actor.request_id,
    )
    audit.record(db, acting, "auth.login", object_type="user", object_id=user.id)
    await audit.commit_with_audit(db)
    return user, access, refresh


async def refresh(
    db: AsyncSession, settings: Settings, actor: Principal, refresh_token: str
) -> tuple[User, str, str]:
    rt = await repo.get_refresh_token(db, token_hash(refresh_token))
    now = datetime.now(UTC)
    if rt is None or rt.revoked_at is not None or rt.expires_at < now:
        raise Unauthorized("Refresh token invalid or expired", code="token_invalid")
    user = await repo.get_user(db, rt.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("User inactive", code="token_invalid")
    rt.revoked_at = now  # rotate
    new_refresh = new_opaque_token(48)
    await repo.add_refresh_token(db, user.id, token_hash(new_refresh), refresh_expiry(settings))
    access = create_access_token(settings, user.id, user.role)
    acting = Principal(
        kind="user",
        user_id=user.id,
        role=user.role,
        ip=actor.ip,
        user_agent=actor.user_agent,
        request_id=actor.request_id,
    )
    audit.record(db, acting, "auth.refresh", object_type="user", object_id=user.id)
    await audit.commit_with_audit(db)
    return user, access, new_refresh


async def logout(db: AsyncSession, actor: Principal, refresh_token: str) -> None:
    rt = await repo.get_refresh_token(db, token_hash(refresh_token))
    if rt is not None and rt.revoked_at is None:
        rt.revoked_at = datetime.now(UTC)
        acting = Principal(
            kind="user",
            user_id=rt.user_id,
            role=actor.role,
            ip=actor.ip,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
        )
        audit.record(db, acting, "auth.logout", object_type="user", object_id=rt.user_id)
    await audit.commit_with_audit(db)


# ---- admin user management -----------------------------------------------------------


async def create_user(db: AsyncSession, actor: Principal, data: UserCreate) -> User:
    if await repo.get_user_by_username(db, data.username):
        raise Conflict("Username already exists")
    user = User(
        username=data.username,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
        station=data.station,
        jurisdiction=data.jurisdiction,
    )
    await repo.add_user(db, user)
    audit.record(
        db,
        actor,
        "user.created",
        object_type="user",
        object_id=user.id,
        details={"role": user.role},
    )
    await audit.commit_with_audit(db)
    return user


async def update_user(db: AsyncSession, actor: Principal, user_id: str, data: UserUpdate) -> User:
    user = await repo.get_user(db, user_id)
    if user is None:
        raise NotFound("User not found")
    changed: list[str] = []
    for field in ("full_name", "role", "station", "jurisdiction", "is_active"):
        val = getattr(data, field)
        if val is not None:
            setattr(user, field, val)
            changed.append(field)
    if data.password:
        user.password_hash = hash_password(data.password)
        changed.append("password")
    if data.unlock:
        user.locked_until = None
        user.failed_logins = 0
        changed.append("unlock")
    audit.record(
        db,
        actor,
        "user.updated",
        object_type="user",
        object_id=user.id,
        details={"fields": changed},
    )
    await audit.commit_with_audit(db)
    return user


async def list_users(db: AsyncSession, actor: Principal) -> list[User]:
    users = await repo.list_users(db)
    audit.record(db, actor, "user.listed", object_type="user")
    await audit.commit_with_audit(db)
    return users
