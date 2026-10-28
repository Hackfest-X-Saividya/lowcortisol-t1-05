from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, TimestampMixin, UTCDateTime, utcnow

CASE_STATUSES = ("open", "closed", "archived")
ASSIGNMENT_ROLES = ("lead", "assisting", "artist")
LANGUAGES = ("hi", "kn", "en")


class Case(IdMixin, TimestampMixin, Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("station", "case_number", name="uq_case_station_number"),)

    case_number: Mapped[str] = mapped_column(String(64), nullable=False)
    station: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    crime_type: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    location_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )


class CaseAssignment(Base):
    __tablename__ = "case_assignments"

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id"), primary_key=True, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True, index=True
    )
    role_on_case: Mapped[str] = mapped_column(String(20), nullable=False, default="assisting")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class Witness(IdMixin, CreatedMixin, Base):
    __tablename__ = "witnesses"

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    consent_recorded_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    consent_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
