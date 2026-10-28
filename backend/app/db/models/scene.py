from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin

SCENE_SOURCES = ("initial", "patch", "voice", "text", "template")


class SceneVersion(IdMixin, CreatedMixin, Base):
    __tablename__ = "scene_versions"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scene_versions.id"), nullable=True, index=True
    )
    scene: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    patch: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="initial")
    utterance_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_role: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
