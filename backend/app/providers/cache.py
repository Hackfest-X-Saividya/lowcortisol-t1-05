"""Provider response cache.

Key = SHA-256 of (provider, model, normalized request). Responses are stored encrypted
through the file store and indexed in ``provider_cache``. Audio transcription keys include
the SHA-256 of the audio bytes, so a transcript is only ever reused for identical audio.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.files import ProviderCache
from app.db.session import Database, commit_tx
from app.services.storage import FileStore

log = get_logger(__name__)


def cache_key(provider: str, model: str, request: dict[str, Any]) -> str:
    normalized = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{provider}|{model}|{normalized}".encode()).hexdigest()


class ProviderCacheStore:
    def __init__(self, files: FileStore, db: Database, enabled: bool = True) -> None:
        self.files = files
        self.db = db
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

    async def get(self, key: str) -> bytes | None:
        if not self.enabled:
            return None
        async with self.db.session() as s:
            row = await s.get(ProviderCache, key)
            if row is None:
                self.misses += 1
                return None
            rec = await self.files.get(s, row.file_id)
            data = await self.files.load_bytes(rec)
        self.hits += 1
        return data

    async def put(self, key: str, provider: str, model: str, data: bytes, mime: str) -> None:
        if not self.enabled:
            return
        async with self.db.session() as s:
            if await s.get(ProviderCache, key) is not None:
                return
            rec = await self.files.save(s, data, kind="cache", mime=mime)
            s.add(ProviderCache(key=key, provider=provider, model=model, file_id=rec.id))
            await commit_tx(s)

    async def put_session(
        self, s: AsyncSession, key: str, provider: str, model: str, data: bytes, mime: str
    ) -> None:
        """Variant for callers that already hold a session (flushes, does not commit)."""
        if not self.enabled:
            return
        if await s.get(ProviderCache, key) is not None:
            return
        rec = await self.files.save(s, data, kind="cache", mime=mime)
        s.add(ProviderCache(key=key, provider=provider, model=model, file_id=rec.id))
