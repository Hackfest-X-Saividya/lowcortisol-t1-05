"""Encrypted file store.

Every blob is AES-256-GCM encrypted with a per-file key (see ``app.core.crypto``) and
written under ``FILE_STORE_DIR/<first two chars of id>/<id>.bin``. Only ids are ever
exposed to clients; bytes are served through ``GET /files/{file_id}``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.crypto import decrypt_bytes, encrypt_bytes, sha256_hex
from app.core.errors import NotFound, UnsupportedMedia
from app.db.base import new_id
from app.db.models.files import File

AUDIO_MIMES = {
    "audio/webm": [b"\x1a\x45\xdf\xa3"],
    "audio/ogg": [b"OggS"],
    "audio/wav": [b"RIFF"],
    "audio/mpeg": [b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa"],
    "audio/mp4": [],  # ftyp at offset 4, handled below
}
IMAGE_MIMES = {
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/webp": [b"RIFF"],
}
AUDIO_EXT = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
}


def sniff_audio(data: bytes) -> str | None:
    head = data[:16]
    if head.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "audio/mp4"
    for mime, magics in AUDIO_MIMES.items():
        for m in magics:
            if mime != "audio/wav" and head.startswith(m):
                return mime
    return None


def sniff_image(data: bytes) -> str | None:
    head = data[:16]
    if head.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    for mime, magics in IMAGE_MIMES.items():
        for m in magics:
            if mime != "image/webp" and head.startswith(m):
                return mime
    return None


def require_audio(data: bytes, max_mb: int) -> str:
    if len(data) > max_mb * 1024 * 1024:
        from app.core.errors import PayloadTooLarge

        raise PayloadTooLarge(f"Audio larger than {max_mb} MB")
    mime = sniff_audio(data)
    if not mime:
        raise UnsupportedMedia("Audio must be webm, ogg, wav, mp3 or m4a")
    return mime


class FileStore:
    def __init__(self, settings: Settings) -> None:
        self.root: Path = settings.file_store_path
        self.root.mkdir(parents=True, exist_ok=True)
        self._master = settings.file_master_key()

    def _path_for(self, file_id: str) -> Path:
        return self.root / file_id[:2] / f"{file_id}.bin"

    async def save(
        self,
        db: AsyncSession,
        data: bytes,
        *,
        kind: str,
        mime: str,
        session_id: str | None = None,
        created_by: str | None = None,
    ) -> File:
        file_id = new_id()
        blob = encrypt_bytes(self._master, file_id, data)
        path = self._path_for(file_id)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(blob)
            tmp.replace(path)

        await asyncio.to_thread(_write)
        rec = File(
            id=file_id,
            session_id=session_id,
            kind=kind,
            mime=mime,
            size_bytes=len(data),
            sha256_plain=sha256_hex(data),
            storage_path=str(path.relative_to(self.root)).replace("\\", "/"),
            created_by=created_by,
        )
        db.add(rec)
        return rec

    async def load_bytes(self, rec: File) -> bytes:
        path = self.root / rec.storage_path
        blob = await asyncio.to_thread(path.read_bytes)
        return decrypt_bytes(self._master, rec.id, blob)

    async def get(self, db: AsyncSession, file_id: str) -> File:
        rec = await db.get(File, file_id)
        if rec is None:
            raise NotFound("File not found")
        return rec

    async def load(self, db: AsyncSession, file_id: str) -> tuple[File, bytes]:
        rec = await self.get(db, file_id)
        return rec, await self.load_bytes(rec)
