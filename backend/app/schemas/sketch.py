from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HandleMove(BaseModel):
    handle: str
    dx: float = Field(default=0.0, ge=-0.5, le=0.5, description="fraction of face width")
    dy: float = Field(default=0.0, ge=-0.5, le=0.5)


class EditSpec(BaseModel):
    region: str | None = None
    type: Literal["geometric", "overlay", "inpaint"] | None = None
    param: str | None = None
    amount: float | None = Field(default=None, ge=-0.5, le=0.5)
    handle_moves: list[HandleMove] | None = None
    overlay_id: str | None = None
    overlay_params: dict[str, Any] | None = None
    prompt: str | None = Field(default=None, max_length=300)
    symmetric: bool = True


class EditRequest(BaseModel):
    source: Literal["voice", "text", "drag", "slider", "accessory", "artist"] = "text"
    utterance_original: str | None = Field(default=None, max_length=1000)
    language: Literal["hi", "kn", "en"] = "en"
    edit: EditSpec | None = None


class SketchRequest(BaseModel):
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


class RatingRequest(BaseModel):
    rating: Literal["closer", "further"]


class LockItem(BaseModel):
    feature: str
    locked: bool | None = None
    confidence: Literal["sure", "somewhat", "guessing", "not_remembered"] | None = None


class LocksPut(BaseModel):
    locks: list[LockItem]


class LockOut(BaseModel):
    feature: str
    locked: bool
    confidence: str | None
    updated_by_role: str | None
    updated_at: datetime | None


class TreeNode(BaseModel):
    id: str
    parent_id: str | None
    edit_source: str
    edit_type: str | None
    sketch_file_id: str
    witness_rating: str | None
    created_by_role: str
    created_at: datetime
    stability_warning: bool
    utterance_original: str | None


class VersionOut(BaseModel):
    id: str
    session_id: str
    parent_id: str | None
    sketch_file_id: str
    master_file_id: str | None
    base_master_file_id: str | None
    mask_file_id: str | None
    landmarks: list[Any]
    handle_positions: dict[str, list[float]]
    sliders: dict[str, Any]
    overlays: list[Any]
    edit: dict[str, Any]
    edit_source: str
    utterance_original: str | None
    seed: int | None
    provider_info: dict[str, Any]
    stability: dict[str, Any]
    witness_rating: str | None
    created_by_role: str
    created_at: datetime
    quality_warning: bool


class OverlayInfo(BaseModel):
    id: str
    name: str
    region: str
    positional: bool
    positions: list[str]
    thumbnail: str
