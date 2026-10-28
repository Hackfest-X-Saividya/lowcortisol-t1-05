"""In-process background job runner backed by the ``jobs`` table.

A job is a row plus an ``asyncio.Task``. Handlers are registered per ``kind`` and run
with their own database session. ``ProviderError`` becomes a clean failed job; any other
exception is logged and also fails the job without leaking internals. With
``JOBS_INLINE=true`` (tests) the handler runs before ``submit`` returns.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import AppError, ProviderError
from app.core.events import EventBus
from app.core.logging import get_logger, request_id_var
from app.core.security import Principal
from app.db.models.jobs import Job
from app.db.session import Database, commit_tx

log = get_logger(__name__)


@dataclass
class JobContext:
    job_id: str
    kind: str
    session_id: str | None
    payload: dict[str, Any]
    actor: Principal
    db: Database
    bus: EventBus
    runner: JobRunner

    @property
    def container(self) -> Any:
        """The application container (set by ``app.container.Container``)."""
        return self.runner.container

    async def progress(self, pct: float, message: str = "") -> None:
        await self.runner._set_progress(self.job_id, pct, message)
        self.bus.publish(
            self.session_id,
            "job.progress",
            {
                "job_id": self.job_id,
                "kind": self.kind,
                "status": "running",
                "progress": pct,
                "message": message,
            },
        )


JobHandler = Callable[[JobContext, AsyncSession], Awaitable[dict[str, Any]]]


class JobRunner:
    def __init__(self, db: Database, bus: EventBus, inline: bool = False) -> None:
        self.db = db
        self.bus = bus
        self.inline = inline
        self._handlers: dict[str, JobHandler] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self.container: Any = None

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def handler(self, kind: str) -> Callable[[JobHandler], JobHandler]:
        def deco(fn: JobHandler) -> JobHandler:
            self.register(kind, fn)
            return fn

        return deco

    async def submit(
        self,
        kind: str,
        *,
        session_id: str | None,
        payload: dict[str, Any],
        actor: Principal,
    ) -> Job:
        if kind not in self._handlers:
            raise AppError(
                f"no handler for job kind {kind}", code="job_kind_unknown", status_code=500
            )
        async with self.db.session() as s:
            job = Job(session_id=session_id, kind=kind, status="queued", progress=0.0)
            s.add(job)
            audit.record(
                s,
                actor,
                "job.submitted",
                object_type="job",
                object_id=job.id,
                session_id=session_id,
                details={"kind": kind},
            )
            await audit.commit_with_audit(s)
            job_id = job.id
        ctx = JobContext(
            job_id=job_id,
            kind=kind,
            session_id=session_id,
            payload=payload,
            actor=actor,
            db=self.db,
            bus=self.bus,
            runner=self,
        )
        if self.inline:
            await self._run(ctx)
        else:
            task = asyncio.create_task(self._run(ctx), name=f"job:{kind}:{job_id[:8]}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        async with self.db.session() as s:
            refreshed = await s.get(Job, job_id)
            assert refreshed is not None
            return refreshed

    async def _set_progress(self, job_id: str, pct: float, message: str = "") -> None:
        async with self.db.session() as s:
            job = await s.get(Job, job_id)
            if job is not None:
                job.progress = max(0.0, min(100.0, float(pct)))
                if job.status == "queued":
                    job.status = "running"
                await commit_tx(s)

    async def _finish(
        self, job_id: str, status: str, result: dict[str, Any] | None, error: str | None
    ) -> None:
        async with self.db.session() as s:
            job = await s.get(Job, job_id)
            if job is not None:
                job.status = status
                job.progress = 100.0 if status == "done" else job.progress
                job.result = result
                job.error = error
                await commit_tx(s)

    async def _run(self, ctx: JobContext) -> None:
        token = request_id_var.set(ctx.actor.request_id or f"job-{ctx.job_id[:8]}")
        try:
            await self._set_progress(ctx.job_id, 1.0)
            handler = self._handlers[ctx.kind]
            async with self.db.session() as s:
                try:
                    result = await handler(ctx, s)
                except Exception:
                    await s.rollback()
                    raise
            await self._finish(ctx.job_id, "done", result, None)
            self.bus.publish(
                ctx.session_id,
                "job.progress",
                {
                    "job_id": ctx.job_id,
                    "kind": ctx.kind,
                    "status": "done",
                    "progress": 100.0,
                    "result": result,
                },
            )
        except ProviderError as exc:
            msg = f"{exc.provider or 'provider'}: {exc.message}"
            log.warning(
                "job %s (%s) failed: provider error from %s", ctx.job_id, ctx.kind, exc.provider
            )
            await self._finish(ctx.job_id, "failed", None, msg)
            self._publish_error(ctx, "provider_error", msg)
        except AppError as exc:
            log.warning("job %s (%s) failed: %s", ctx.job_id, ctx.kind, exc.code)
            await self._finish(ctx.job_id, "failed", None, exc.message)
            self._publish_error(ctx, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s (%s) crashed: %s", ctx.job_id, ctx.kind, type(exc).__name__)
            await self._finish(ctx.job_id, "failed", None, f"internal error: {type(exc).__name__}")
            self._publish_error(ctx, "internal_error", "Job failed")
        finally:
            request_id_var.reset(token)

    def _publish_error(self, ctx: JobContext, code: str, message: str) -> None:
        self.bus.publish(
            ctx.session_id,
            "job.progress",
            {"job_id": ctx.job_id, "kind": ctx.kind, "status": "failed", "error": message},
        )
        self.bus.publish(
            ctx.session_id, "error", {"job_id": ctx.job_id, "code": code, "message": message}
        )

    async def wait_all(self, timeout: float = 30.0) -> None:
        if self._tasks:
            await asyncio.wait(list(self._tasks), timeout=timeout)

    async def shutdown(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
