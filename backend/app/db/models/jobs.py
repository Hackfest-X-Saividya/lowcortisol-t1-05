from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin

JOB_STATUSES = ("queued", "running", "done", "failed")


class Job(IdMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
