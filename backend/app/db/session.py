"""Async engine and session factory.

SQLite specifics applied on every connection: ``PRAGMA journal_mode=WAL`` and
``PRAGMA foreign_keys=ON``. Connections run in autocommit mode; ``commit_tx`` (and
``app.core.audit.commit_with_audit``) open a ``BEGIN IMMEDIATE`` write transaction right
before flushing so the audit insert and the business change commit atomically.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.db.base import Base

AUDIT_TRIGGERS_SQL = [
    "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;",
    "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;",
]


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def make_engine(url: str | None = None, settings: Settings | None = None) -> AsyncEngine:
    settings = settings or get_settings()
    url = url or settings.resolved_database_url
    kwargs: dict[str, Any] = {"future": True}
    if _is_sqlite(url):
        db_path = url.split("///", 1)[-1]
        if ":memory:" not in db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"timeout": 30}
    engine = create_async_engine(url, **kwargs)

    if _is_sqlite(url):

        @event.listens_for(engine.sync_engine, "connect")
        def _on_connect(dbapi_connection: Any, _record: Any) -> None:
            # Let us control transactions ourselves (BEGIN IMMEDIATE below).
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


async def commit_tx(db: AsyncSession) -> None:
    """Flush and commit inside one ``BEGIN IMMEDIATE`` write transaction (SQLite).

    Reads run in autocommit mode and never hold a snapshot, so a session can await
    background work (or other sessions) without blocking writers. The write transaction
    is opened only here, immediately before the flush, and closed by the commit; on any
    error the whole transaction is rolled back.
    """
    conn = await db.connection()
    is_sqlite = conn.dialect.name == "sqlite"
    try:
        if is_sqlite:
            await conn.exec_driver_sql("BEGIN IMMEDIATE")
        await db.flush()
        await db.commit()
    except BaseException:
        await db.rollback()
        raise


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def create_schema(engine: AsyncEngine) -> None:
    """Create all tables and the append-only audit triggers (dev convenience and tests).

    Production deployments should run ``alembic upgrade head`` instead; both paths
    produce the same schema.
    """
    from app.db import models  # noqa: F401  (register all models)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            for stmt in AUDIT_TRIGGERS_SQL:
                await conn.execute(text(stmt))


class Database:
    """Holds the engine and session factory for the app lifetime."""

    def __init__(self, url: str | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.engine = make_engine(url, self.settings)
        self.session_factory = make_session_factory(self.engine)

    async def sessions(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    def session(self) -> AsyncSession:
        return self.session_factory()

    async def dispose(self) -> None:
        await self.engine.dispose()
