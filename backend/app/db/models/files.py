from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, UTCDateTime, utcnow

FILE_KINDS = (
    "audio",
    "master_image",
    "base_master_image",
    "sketch_image",
    "mask",
    "preview",
    "overlay_render",
    "export_png",
    "export_pdf",
    "scene_image",
    "cache",
)


class File(IdMixin, CreatedMixin, Base):
    __tablename__ = "files"

    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    mime: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_plain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )


class ProviderCache(Base):
    __tablename__ = "provider_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
