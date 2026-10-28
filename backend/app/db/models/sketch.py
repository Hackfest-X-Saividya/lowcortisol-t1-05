from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, UTCDateTime, utcnow

EDIT_SOURCES = ("initial", "drag", "slider", "voice", "text", "accessory", "inpaint", "artist")
FEATURES = ("face_shape", "eyes", "brows", "nose", "mouth", "jaw", "hair", "ears", "skin", "marks")
CONFIDENCES = ("sure", "somewhat", "guessing", "not_remembered")


class SketchVersion(IdMixin, CreatedMixin, Base):
    __tablename__ = "sketch_versions"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sketch_versions.id"), nullable=True, index=True
    )
    # master = base_master + overlays (what staff see); witness only ever sees sketch.
    master_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id"), nullable=False, index=True
    )
    base_master_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id"), nullable=False, index=True
    )
    sketch_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id"), nullable=False, index=True
    )
    mask_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("files.id"), nullable=True, index=True
    )
    landmarks: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    edit: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    edit_source: Mapped[str] = mapped_column(String(20), nullable=False, default="initial")
    utterance_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_info: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stability: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    overlays: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    sliders: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    witness_rating: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    created_by_role: Mapped[str] = mapped_column(String(20), nullable=False, default="system")


class FeatureLock(Base):
    __tablename__ = "feature_locks"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), primary_key=True, index=True
    )
    feature: Mapped[str] = mapped_column(String(20), primary_key=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    updated_by_role: Mapped[str] = mapped_column(String(20), nullable=False, default="witness")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
