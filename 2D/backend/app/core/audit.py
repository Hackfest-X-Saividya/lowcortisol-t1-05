"""Tamper-evident, hash-chained audit log.

``hash = sha256(prev_hash + canonical_json(entry_without_hashes))`` where canonical JSON
means sorted keys, compact separators, UTF-8 and ISO-8601 UTC timestamps with
microseconds. The first ``prev_hash`` is 64 zeros. The integer ``id`` is excluded from
the hashed entry because it is assigned by the database at insert time; ordering is
protected by the chain itself.

Writes are serialised with a module-level ``asyncio.Lock`` that is held from reading the
chain head until the transaction commits, so two concurrent requests can never both
chain onto the same head. Pending entries live on the SQLAlchemy session (``db.info``)
and are inserted inside the same transaction as the business change by
``commit_with_audit``: if the business change rolls back, so do the audit rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal
from app.db.base import iso_utc, utcnow
from app.db.models.audit import AuditLog
from app.db.session import commit_tx

GENESIS_HASH = "0" * 64
_PENDING_KEY = "audit_pending"
_write_lock = asyncio.Lock()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    payload = (prev_hash + canonical_json(entry)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def entry_dict_from_row(row: AuditLog) -> dict[str, Any]:
    return {
        "at": iso_utc(row.at),
        "actor_user_id": row.actor_user_id,
        "actor_role": row.actor_role,
        "session_id": row.session_id,
        "case_id": row.case_id,
        "action": row.action,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "request_id": row.request_id,
        "details": row.details or {},
    }


@dataclass
class PendingEntry:
    actor_user_id: str | None
    actor_role: str
    session_id: str | None
    case_id: str | None
    action: str
    object_type: str
    object_id: str | None
    ip: str
    user_agent: str
    request_id: str
    details: dict[str, Any]

    def to_dict(self, at: datetime) -> dict[str, Any]:
        return {
            "at": iso_utc(at),
            "actor_user_id": self.actor_user_id,
            "actor_role": self.actor_role,
            "session_id": self.session_id,
            "case_id": self.case_id,
            "action": self.action,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
            "details": self.details,
        }


def record(
    db: AsyncSession,
    actor: Principal,
    action: str,
    *,
    object_type: str = "",
    object_id: str | None = None,
    session_id: str | None = None,
    case_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Queue an audit entry on this session; it is written by ``commit_with_audit``."""
    merged = dict(details or {})
    if actor.request_id and "request_id" not in merged:
        merged["request_id"] = actor.request_id
    entry = PendingEntry(
        actor_user_id=actor.user_id,
        actor_role=actor.role,
        session_id=session_id or actor.session_id,
        case_id=case_id or actor.case_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        ip=actor.ip,
        user_agent=actor.user_agent[:300],
        request_id=actor.request_id,
        details=merged,
    )
    db.info.setdefault(_PENDING_KEY, []).append(entry)


def pending_count(db: AsyncSession) -> int:
    return len(db.info.get(_PENDING_KEY, []))


async def _chain_head(db: AsyncSession) -> str:
    res = await db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    return res.scalar() or GENESIS_HASH


async def commit_with_audit(db: AsyncSession) -> int:
    """Commit the unit of work: open the write transaction, flush the business change,
    chain the pending audit entries onto the head and commit. Returns the entry count."""
    pending: list[PendingEntry] = list(db.info.get(_PENDING_KEY, []))
    if not pending:
        await commit_tx(db)
        return 0
    async with _write_lock:
        conn = await db.connection()
        try:
            if conn.dialect.name == "sqlite":
                await conn.exec_driver_sql("BEGIN IMMEDIATE")
            await db.flush()
            prev = await _chain_head(db)
            for e in pending:
                at = utcnow()
                d = e.to_dict(at)
                h = compute_hash(prev, d)
                db.add(
                    AuditLog(
                        at=at,
                        actor_user_id=e.actor_user_id,
                        actor_role=e.actor_role,
                        session_id=e.session_id,
                        case_id=e.case_id,
                        action=e.action,
                        object_type=e.object_type,
                        object_id=e.object_id,
                        ip=e.ip,
                        user_agent=e.user_agent,
                        request_id=e.request_id,
                        details=e.details,
                        prev_hash=prev,
                        hash=h,
                    )
                )
                prev = h
            db.info[_PENDING_KEY] = []
            await db.flush()
            await db.commit()
        except BaseException:
            await db.rollback()
            db.info[_PENDING_KEY] = []
            raise
    return len(pending)


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    first_broken_id: int | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "first_broken_id": self.first_broken_id,
            "reason": self.reason,
        }


async def verify_chain(db: AsyncSession) -> VerifyResult:
    """Recompute every hash in id order; return the first id that does not verify."""
    res = await db.execute(select(AuditLog).order_by(AuditLog.id.asc()))
    prev = GENESIS_HASH
    checked = 0
    for row in res.scalars():
        if row.prev_hash != prev:
            return VerifyResult(False, checked, row.id, "prev_hash mismatch")
        expected = compute_hash(prev, entry_dict_from_row(row))
        if row.hash != expected:
            return VerifyResult(False, checked, row.id, "hash mismatch")
        prev = row.hash
        checked += 1
    return VerifyResult(True, checked)
