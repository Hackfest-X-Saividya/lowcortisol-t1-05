"""Declarative base and shared column types.

Models stay database-agnostic: UUIDs as 36-char strings, timestamps as timezone-aware
UTC datetimes (stored as ISO text by SQLite, as timestamptz by Postgres), JSON via
SQLAlchemy's portable ``JSON`` type.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_utc(dt: datetime) -> str:
    """ISO-8601 UTC with microseconds, e.g. 2026-10-28T10:11:12.123456+00:00."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


class UTCDateTime(TypeDecorator[datetime]):
    """Always store and return timezone-aware UTC datetimes."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
        datetime: UTCDateTime,
    }


@event.listens_for(Base, "init", propagate=True)
def _assign_string_pk(target: Any, args: Any, kwargs: Any) -> None:
    """String UUID primary keys are assigned at construction so objects can be referenced
    before the first flush (nothing is flushed before the final commit)."""
    col = target.__table__.columns.get("id")
    if col is not None and isinstance(col.type, String) and kwargs.get("id") is None:
        kwargs["id"] = new_id()


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class TimestampMixin(CreatedMixin):
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
