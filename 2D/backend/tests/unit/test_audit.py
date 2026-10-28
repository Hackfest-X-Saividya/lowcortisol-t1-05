from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.container import Container
from app.core import audit
from app.core.security import Principal
from app.db.models.audit import AuditLog


def test_canonical_json_sorted_compact_utf8() -> None:
    s = audit.canonical_json({"b": 1, "a": {"z": "ಕನ್ನಡ", "y": [1, 2]}})
    assert s == '{"a":{"y":[1,2],"z":"ಕನ್ನಡ"},"b":1}'
    assert json.loads(s)["a"]["z"] == "ಕನ್ನಡ"


def test_hash_is_sha256_of_prev_plus_canonical() -> None:
    import hashlib

    entry = {"action": "x", "at": "2026-01-01T00:00:00.000000+00:00"}
    expected = hashlib.sha256(
        (audit.GENESIS_HASH + audit.canonical_json(entry)).encode("utf-8")
    ).hexdigest()
    assert audit.compute_hash(audit.GENESIS_HASH, entry) == expected
    assert audit.GENESIS_HASH == "0" * 64


@pytest.mark.asyncio
async def test_chain_verifies_and_rolls_back_with_business_change(container: Container) -> None:
    actor = Principal(kind="user", user_id="u1", role="officer", request_id="r1")
    async with container.db.session() as db:
        for i in range(5):
            audit.record(db, actor, f"test.{i}", object_type="t", object_id=str(i))
            await audit.commit_with_audit(db)
        res = await audit.verify_chain(db)
        assert res.ok and res.checked == 5
        rows = list((await db.execute(select(AuditLog).order_by(AuditLog.id))).scalars())
        assert rows[0].prev_hash == audit.GENESIS_HASH
        for a, b in zip(rows, rows[1:], strict=False):
            assert b.prev_hash == a.hash
        # a failing business change must not leave an audit row behind
        audit.record(db, actor, "test.fail", object_type="t")
        from app.db.models.users import User

        db.add(User(username="dup", password_hash="x", role="officer"))
        db.add(User(username="dup", password_hash="x", role="officer"))
        with pytest.raises(IntegrityError):
            await audit.commit_with_audit(db)
        res = await audit.verify_chain(db)
        assert res.ok and res.checked == 5


@pytest.mark.asyncio
async def test_triggers_block_update_and_delete(container: Container) -> None:
    actor = Principal(kind="system", role="system")
    async with container.db.session() as db:
        audit.record(db, actor, "t.1", object_type="t")
        await audit.commit_with_audit(db)
        with pytest.raises(IntegrityError, match="append-only"):
            await db.execute(text("UPDATE audit_log SET action='x'"))
        await db.rollback()
        with pytest.raises(IntegrityError, match="append-only"):
            await db.execute(text("DELETE FROM audit_log"))
        await db.rollback()


@pytest.mark.asyncio
async def test_tamper_detection_reports_exact_id(container: Container) -> None:
    actor = Principal(kind="user", user_id="u1", role="officer")
    async with container.db.session() as db:
        for i in range(6):
            audit.record(db, actor, f"t.{i}", object_type="t")
            await audit.commit_with_audit(db)
        ids = list((await db.execute(select(AuditLog.id).order_by(AuditLog.id))).scalars())
        target = ids[3]
    # tamper on a raw connection: drop trigger, edit, recreate trigger
    async with container.db.engine.begin() as conn:
        await conn.execute(text("DROP TRIGGER audit_no_update"))
        await conn.execute(
            text("UPDATE audit_log SET action='tampered' WHERE id=:id"), {"id": target}
        )
        await conn.execute(
            text(
                "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log "
                "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;"
            )
        )
    async with container.db.session() as db:
        res = await audit.verify_chain(db)
        assert not res.ok
        assert res.first_broken_id == target
        assert res.reason == "hash mismatch"


@pytest.mark.asyncio
async def test_timestamps_iso_utc_microseconds(container: Container) -> None:
    actor = Principal(kind="system", role="system")
    async with container.db.session() as db:
        audit.record(db, actor, "t.ts", object_type="t")
        await audit.commit_with_audit(db)
        row = (await db.execute(select(AuditLog))).scalars().first()
        assert row is not None
        d = audit.entry_dict_from_row(row)
        assert d["at"].endswith("+00:00") and "." in d["at"]
        parsed = datetime.fromisoformat(d["at"])
        assert parsed.tzinfo is not None and parsed.utcoffset() == UTC.utcoffset(None)
