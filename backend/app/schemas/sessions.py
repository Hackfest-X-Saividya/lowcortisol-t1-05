from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SessionCreate(BaseModel):
    witness_id: str


class SessionOut(ORMModel):
    id: str
    case_id: str
    witness_id: str
    officer_id: str
    status: str
    first_image_shown_at: datetime | None
    started_at: datetime
    ended_at: datetime | None
    witness_token_expires_at: datetime | None


class SessionCreated(BaseModel):
    session: SessionOut
    witness_token: str = Field(description="Shown once. Give it to the witness device.")


class SessionDetail(SessionOut):
    has_free_recall: bool = False
    latest_sketch_version_id: str | None = None
    latest_scene_version_id: str | None = None
    locks: dict[str, Any] = {}
    question_count: int = 0


class DisplayEventCreate(BaseModel):
    sketch_version_id: str | None = None
    scene_version_id: str | None = None
    screen: str = Field(default="witness", max_length=40)


class DisplayEventOut(ORMModel):
    id: str
    session_id: str
    sketch_version_id: str | None
    scene_version_id: str | None
    screen: str
    shown_at: datetime


class SignoffCreate(BaseModel):
    sketch_version_id: str | None = None
    scene_version_id: str | None = None
    confidences: dict[str, str] = Field(
        default_factory=dict,
        description="feature -> sure | somewhat | guessing | not_remembered",
    )
    witness_statement: str = Field(default="", max_length=4000)


class SignoffOut(ORMModel):
    id: str
    session_id: str
    sketch_version_id: str | None
    scene_version_id: str | None
    confidences: dict[str, Any]
    witness_statement: str
    created_at: datetime


class ExportCreate(BaseModel):
    kind: str = Field(default="png", pattern="^(png|pdf|scene_png|photoreal_png)$")
    sketch_version_id: str | None = None
    scene_version_id: str | None = None


class ExportOut(ORMModel):
    id: str
    session_id: str
    kind: str
    file_id: str
    sha256: str
    created_by: str | None
    created_at: datetime


class JobOut(ORMModel):
    id: str
    session_id: str | None
    kind: str
    status: str
    progress: float
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
