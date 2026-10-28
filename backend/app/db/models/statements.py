from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, UTCDateTime, utcnow

STATEMENT_KINDS = ("free_recall", "answer_audio", "edit_command", "scene_command")
STATEMENT_SOURCES = ("audio", "typed", "browser_asr")
STATEMENT_STATUSES = ("pending", "transcribing", "transcribed", "extracted", "failed")
ANSWER_TYPES = ("voice", "text", "option", "not_remembered", "skipped")


class Statement(IdMixin, CreatedMixin, Base):
    __tablename__ = "statements"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    audio_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("files.id"), nullable=True, index=True
    )
    transcript_original: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transcript_english: Mapped[str] = mapped_column(Text, nullable=False, default="")
    segments: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    corrected_transcript_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrections: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # For kind=edit_command / scene_command: the version the command applies to.
    target_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class FeatureSheet(IdMixin, Base):
    __tablename__ = "feature_sheets"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, unique=True
    )
    sheet: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
    __mapper_args__ = {"version_id_col": version}


class Question(IdMixin, Base):
    __tablename__ = "questions"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    field_key: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    text_local: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    leading_check: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    answer_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    answer_text_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_option_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    asked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
