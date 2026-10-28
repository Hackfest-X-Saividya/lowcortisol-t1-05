from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SceneBuildRequest(BaseModel):
    template: Literal["shop", "room", "street", "junction"] | None = None


class ScenePatchRequest(BaseModel):
    patch: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    source: Literal["patch", "drag", "text", "template"] = "patch"


class SceneCommandRequest(BaseModel):
    utterance_original: str = Field(min_length=1, max_length=1000)
    language: Literal["hi", "kn", "en"] = "en"


class SceneTreeNode(BaseModel):
    id: str
    parent_id: str | None
    source: str
    utterance_original: str | None
    created_by_role: str
    created_at: datetime
    ops: int


class SceneVersionOut(BaseModel):
    id: str
    session_id: str
    parent_id: str | None
    scene: dict[str, Any]
    patch: list[Any]
    source: str
    utterance_original: str | None
    created_by_role: str
    created_at: datetime
    analysis: dict[str, Any]
