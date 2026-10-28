from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbDep, require_roles
from app.core.security import Principal
from app.schemas.admin import UserCreate, UserUpdate
from app.schemas.auth import UserOut
from app.services import auth as auth_service

router = APIRouter()
AdminDep = Annotated[Principal, Depends(require_roles("admin"))]


@router.get("/users", response_model=list[UserOut])
async def list_users(principal: AdminDep, db: DbDep) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in await auth_service.list_users(db, principal)]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, principal: AdminDep, db: DbDep) -> UserOut:
    return UserOut.model_validate(await auth_service.create_user(db, principal, body))


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: UserUpdate, principal: AdminDep, db: DbDep) -> UserOut:
    return UserOut.model_validate(await auth_service.update_user(db, principal, user_id, body))
