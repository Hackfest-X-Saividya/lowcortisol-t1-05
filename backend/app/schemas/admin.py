from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["officer", "supervisor", "artist", "admin"]


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    full_name: str = Field(default="", max_length=200)
    role: Role
    station: str = Field(default="", max_length=120)
    jurisdiction: str = Field(default="", max_length=120)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    station: str | None = Field(default=None, max_length=120)
    jurisdiction: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)
    unlock: bool | None = None


class AuditEntryOut(BaseModel):
    id: int
    at: str
    actor_user_id: str | None
    actor_role: str
    session_id: str | None
    case_id: str | None
    action: str
    object_type: str
    object_id: str | None
    ip: str
    request_id: str
    details: dict
    prev_hash: str
    hash: str


class AuditPage(BaseModel):
    items: list[AuditEntryOut]
    next_cursor: int | None = None


class AuditVerifyOut(BaseModel):
    ok: bool
    checked: int
    first_broken_id: int | None
    reason: str
