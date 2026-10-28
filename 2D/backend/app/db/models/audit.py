from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class AuditLog(Base):
    """Append-only, hash-chained audit log.

    No foreign keys on purpose: audit rows must never be blocked or cascaded by anything.
    SQLite triggers (see ``app.db.session.AUDIT_TRIGGERS_SQL`` and the Alembic migration)
    abort any UPDATE or DELETE.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
