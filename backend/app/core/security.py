"""Passwords (argon2id), JWTs, refresh tokens, witness tokens and the Principal type."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from app.config import Settings
from app.core.errors import Unauthorized

_hasher = PasswordHasher(time_cost=2, memory_cost=64 * 1024, parallelism=2)

PrincipalKind = Literal["user", "witness", "system"]


@dataclass
class Principal:
    """Who is acting. Built by the API dependencies, consumed by services and audit."""

    kind: PrincipalKind
    user_id: str | None = None
    role: str = "system"  # officer | supervisor | artist | admin | witness | system
    station: str = ""
    jurisdiction: str = ""
    session_id: str | None = None  # witness principals are bound to one session
    case_id: str | None = None
    ip: str = ""
    user_agent: str = ""
    request_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_witness(self) -> bool:
        return self.kind == "witness"

    @property
    def is_staff(self) -> bool:
        return self.kind == "user"

    @classmethod
    def system(cls) -> Principal:
        return cls(kind="system", role="system")


# ---- passwords --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


# ---- JWT access tokens ------------------------------------------------------------------


def create_access_token(settings: Settings, user_id: str, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_access_ttl_min)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_value(), algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_value(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Access token expired", code="token_expired")
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid access token", code="token_invalid")
    if payload.get("type") != "access":
        raise Unauthorized("Invalid token type", code="token_invalid")
    return payload


# ---- opaque tokens (refresh + witness) -------------------------------------------------


def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.jwt_refresh_ttl_days)


def witness_token_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=settings.witness_token_ttl_min)
