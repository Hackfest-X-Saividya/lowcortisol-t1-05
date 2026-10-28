from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import ContainerDep, DbDep, StaffDep
from app.core.logging import request_id_var
from app.core.ratelimit import limiter
from app.core.security import Principal
from app.db.repositories import users as user_repo
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserOut,
)
from app.services import auth as auth_service

router = APIRouter()


def _anon(request: Request) -> Principal:
    return Principal(
        kind="system",
        role="anonymous",
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("User-Agent", ""),
        request_id=request_id_var.get(),
    )


def _token_response(container: ContainerDep, user, access: str, refresh: str) -> TokenResponse:  # type: ignore[no-untyped-def]
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=container.settings.jwt_access_ttl_min * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(lambda: "10/minute")
async def login(
    request: Request, body: LoginRequest, container: ContainerDep, db: DbDep
) -> TokenResponse:
    user, access, refresh = await auth_service.login(
        db, container.settings, _anon(request), body.username, body.password
    )
    return _token_response(container, user, access, refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request, body: RefreshRequest, container: ContainerDep, db: DbDep
) -> TokenResponse:
    user, access, new_refresh = await auth_service.refresh(
        db, container.settings, _anon(request), body.refresh_token
    )
    return _token_response(container, user, access, new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, body: LogoutRequest, db: DbDep) -> Response:
    await auth_service.logout(db, _anon(request), body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(principal: StaffDep, db: DbDep) -> UserOut:
    user = await user_repo.get_user(db, principal.user_id or "")
    assert user is not None
    return UserOut.model_validate(user)
