"""FastAPI dependencies: container, db session, principals (staff JWT or witness token)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import Forbidden, Unauthorized
from app.core.logging import get_logger, request_id_var
from app.core.security import Principal, decode_access_token, token_hash
from app.db.repositories import sessions as session_repo
from app.db.repositories import users as user_repo

log = get_logger(__name__)


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_db(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.db.session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            if session.in_transaction():
                # Services commit explicitly; anything left is discarded on purpose.
                await session.rollback()


DbDep = Annotated[AsyncSession, Depends(get_db)]


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.headers.get("X-Witness-Token") or None


def _client_meta(request: Request) -> tuple[str, str, str]:
    ip = request.client.host if request.client else ""
    ua = request.headers.get("User-Agent", "")
    return ip, ua, request_id_var.get()


async def resolve_principal(
    container: Container, db: AsyncSession, token: str | None, ip: str, ua: str, rid: str
) -> Principal:
    if not token:
        raise Unauthorized("Missing credentials")
    if token.count(".") == 2:  # JWT
        payload = decode_access_token(container.settings, token)
        user = await user_repo.get_user(db, str(payload.get("sub")))
        if user is None or not user.is_active:
            raise Unauthorized("User not found or inactive", code="token_invalid")
        return Principal(
            kind="user",
            user_id=user.id,
            role=user.role,
            station=user.station,
            jurisdiction=user.jurisdiction,
            ip=ip,
            user_agent=ua,
            request_id=rid,
        )
    # Witness token
    sess = await session_repo.get_session_by_token_hash(db, token_hash(token))
    if sess is None:
        raise Unauthorized("Invalid witness token", code="token_invalid")
    now = datetime.now(UTC)
    if sess.witness_token_expires_at is None or sess.witness_token_expires_at < now:
        raise Unauthorized("Witness token expired", code="token_expired")
    if sess.status not in ("active", "paused"):
        raise Unauthorized("Session is no longer open", code="session_closed")
    return Principal(
        kind="witness",
        role="witness",
        session_id=sess.id,
        case_id=sess.case_id,
        ip=ip,
        user_agent=ua,
        request_id=rid,
    )


async def get_principal(request: Request, container: ContainerDep, db: DbDep) -> Principal:
    ip, ua, rid = _client_meta(request)
    return await resolve_principal(container, db, _bearer(request), ip, ua, rid)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_staff(principal: PrincipalDep) -> Principal:
    if principal.kind != "user":
        raise Forbidden("Staff credentials required")
    return principal


StaffDep = Annotated[Principal, Depends(get_staff)]


def require_roles(*roles: str):  # type: ignore[no-untyped-def]
    async def _dep(principal: PrincipalDep) -> Principal:
        if principal.kind != "user" or principal.role not in roles:
            raise Forbidden(f"Requires role: {', '.join(roles)}")
        return principal

    return _dep
