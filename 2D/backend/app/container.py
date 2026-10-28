"""Application container: everything with a lifetime (db, bus, jobs, file store, providers)."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.core.events import EventBus
from app.core.jobs import JobRunner
from app.core.logging import get_logger
from app.db.session import Database, create_schema
from app.providers.registry import ProviderRegistry, build_registry
from app.services.storage import FileStore

log = get_logger(__name__)


class Container:
    def __init__(self, settings: Settings | None = None, database_url: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = Database(database_url, self.settings)
        self.bus = EventBus()
        self.jobs = JobRunner(self.db, self.bus, inline=self.settings.jobs_inline)
        self.jobs.container = self
        self.files = FileStore(self.settings)
        self.providers: ProviderRegistry = build_registry(self.settings, self.files, self.db)
        self._landmarker: Any = None
        self._register_jobs()

    def _register_jobs(self) -> None:
        from app.services import jobs_registry

        jobs_registry.set_container(self)
        jobs_registry.register_all(self.jobs)

    async def start(self) -> None:
        if self.settings.auto_create_db:
            await create_schema(self.db.engine)

    async def stop(self) -> None:
        await self.jobs.shutdown()
        await self.providers.aclose()
        await self.db.dispose()

    @property
    def landmarker(self) -> Any:
        """Lazily created MediaPipe landmarker (None in mock mode or if the model is missing)."""
        if self._landmarker is None:
            from app.services.sketch.landmarks import Landmarker

            self._landmarker = Landmarker(self.settings)
        return self._landmarker
