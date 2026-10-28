from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, UTCDateTime, utcnow

SESSION_STATUSES = ("active", "paused", "signed_off", "closed")
EXPORT_KINDS = ("png", "pdf", "scene_png", "photoreal_png")


class InterviewSession(IdMixin, Base):
    __tablename__ = "sessions"

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id"), nullable=False, index=True
    )
    witness_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("witnesses.id"), nullable=False, index=True
    )
    officer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    witness_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    witness_token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    first_image_shown_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class DisplayEvent(IdMixin, Base):
    __tablename__ = "display_events"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    sketch_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sketch_versions.id"), nullable=True, index=True
    )
    scene_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scene_versions.id"), nullable=True, index=True
    )
    screen: Mapped[str] = mapped_column(String(40), nullable=False, default="witness")
    shown_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Signoff(IdMixin, CreatedMixin, Base):
    __tablename__ = "signoffs"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    sketch_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sketch_versions.id"), nullable=True, index=True
    )
    scene_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scene_versions.id"), nullable=True, index=True
    )
    confidences: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    witness_statement: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Export(IdMixin, CreatedMixin, Base):
    __tablename__ = "exports"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id"), nullable=False, index=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
