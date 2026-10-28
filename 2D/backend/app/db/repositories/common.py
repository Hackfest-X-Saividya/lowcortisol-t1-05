"""Cursor pagination helpers shared by list endpoints.

Cursor = base64url of ``"<iso created_at>|<id>"`` for the last row returned. Lists are
ordered by ``(created_at, id)`` descending.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import InstrumentedAttribute

from app.db.base import iso_utc


def encode_cursor(created_at: datetime, row_id: Any) -> str:
    raw = f"{iso_utc(created_at)}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str] | None:
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + pad).decode()
        ts, row_id = raw.split("|", 1)
        return datetime.fromisoformat(ts), row_id
    except Exception:  # noqa: BLE001
        return None


def apply_cursor(
    stmt: Select[Any],
    created_col: InstrumentedAttribute[Any],
    id_col: InstrumentedAttribute[Any],
    cursor: str | None,
    limit: int,
) -> Select[Any]:
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded:
            ts, row_id = decoded
            stmt = stmt.where(or_(created_col < ts, and_(created_col == ts, id_col < row_id)))
    return stmt.order_by(created_col.desc(), id_col.desc()).limit(limit + 1)


def page(
    rows: list[Any], limit: int, created_attr: str = "created_at"
) -> tuple[list[Any], str | None]:
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(getattr(last, created_attr), last.id)
    return rows, next_cursor
