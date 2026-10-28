"""Scene JSON schema (rendered by the frontend with three.js).

Coordinates are metres: x across the room width, z across the depth, y up (floor y = 0).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Vec3 = list[float]
Wall = Literal["north", "south", "east", "west"]


def _vec3(v: list[float], name: str) -> list[float]:
    if len(v) != 3:
        raise ValueError(f"{name} must have 3 components")
    return [float(x) for x in v]


class Door(BaseModel):
    id: str
    wall: Wall = "south"
    offset_m: float = 1.0
    width_m: float = 1.0


class Window(BaseModel):
    id: str
    wall: Wall = "north"
    offset_m: float = 1.0
    width_m: float = 1.2


class Room(BaseModel):
    width_m: float = Field(gt=0.5, le=200)
    depth_m: float = Field(gt=0.5, le=200)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)


class SceneObject(BaseModel):
    id: str
    type: str
    pos: Vec3
    rot_y_deg: float = 0.0
    size: Vec3 = Field(default_factory=lambda: [1.0, 1.0, 1.0])  # w, h, d
    locked: bool = False

    @field_validator("pos")
    @classmethod
    def _pos(cls, v: list[float]) -> list[float]:
        return _vec3(v, "pos")

    @field_validator("size")
    @classmethod
    def _size(cls, v: list[float]) -> list[float]:
        v = _vec3(v, "size")
        if any(x <= 0 for x in v):
            raise ValueError("size components must be positive")
        return v


class Person(BaseModel):
    id: str
    role: Literal["witness", "suspect", "other"] = "other"
    pos: Vec3
    facing_deg: float = 0.0
    eye_height_m: float = 1.5

    @field_validator("pos")
    @classmethod
    def _pos(cls, v: list[float]) -> list[float]:
        return _vec3(v, "pos")


class Evidence(BaseModel):
    id: str
    label: str
    pos: Vec3

    @field_validator("pos")
    @classmethod
    def _pos(cls, v: list[float]) -> list[float]:
        return _vec3(v, "pos")


class Lighting(BaseModel):
    type: Literal["indoor", "outdoor"] = "indoor"
    level: Literal["bright", "normal", "dim", "dark"] = "normal"
    sources: list[str] = Field(default_factory=list)


class SceneEvent(BaseModel):
    step: int
    text: str
    positions: dict[str, Vec3] = Field(default_factory=dict)


def _coerce_vec(v: object) -> object:
    """Accept {"x","y","z"} dicts and 2-vectors [x, z] from LLM output."""
    if isinstance(v, dict):
        return [float(v.get("x", 0.0)), float(v.get("y", 0.0)), float(v.get("z", 0.0))]
    if isinstance(v, list | tuple) and len(v) == 2:
        return [float(v[0]), 0.0, float(v[1])]
    return v


def coerce_scene_input(data: object) -> object:
    """Normalise common LLM variations before strict validation."""
    if not isinstance(data, dict):
        return data
    d = dict(data)
    room = d.get("room")
    if isinstance(room, dict):
        room = dict(room)
        for k_from, k_to in (("width", "width_m"), ("depth", "depth_m")):
            if k_from in room and k_to not in room:
                room[k_to] = room.pop(k_from)
        d["room"] = room
    for coll in ("objects", "people", "evidence"):
        items = d.get(coll)
        if not isinstance(items, list):
            continue
        out = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            item = dict(item)
            if "pos" in item:
                item["pos"] = _coerce_vec(item["pos"])
            elif "position" in item:
                item["pos"] = _coerce_vec(item.pop("position"))
            if coll == "objects":
                item.setdefault("type", str(item.get("id", "object")))
                item.setdefault("id", f"{item['type']}_{i}")
                if "size" in item:
                    item["size"] = _coerce_vec(item["size"])
            if coll == "people":
                role = str(item.get("role", "other")).lower()
                item["role"] = (
                    role
                    if role in ("witness", "suspect", "other")
                    else (
                        "suspect"
                        if "suspect" in role or "accused" in role
                        else "witness"
                        if "witness" in role
                        else "other"
                    )
                )
                item.setdefault("id", f"{item['role']}_{i}")
            if coll == "evidence":
                item.setdefault("label", str(item.get("id", "evidence")))
                item.setdefault("id", f"evidence_{i}")
            out.append(item)
        d[coll] = out
    events = d.get("events")
    if isinstance(events, list):
        fixed = []
        for i, ev in enumerate(events, start=1):
            if isinstance(ev, str):
                fixed.append({"step": i, "text": ev})
            elif isinstance(ev, dict):
                ev = dict(ev)
                ev.setdefault("step", i)
                ev.setdefault("text", str(ev.get("description", "")))
                fixed.append(ev)
        d["events"] = fixed
    lighting = d.get("lighting")
    if isinstance(lighting, str):
        d["lighting"] = {
            "level": lighting if lighting in ("bright", "normal", "dim", "dark") else "normal"
        }
    return d


class Scene(BaseModel):
    template: str = "room"
    room: Room
    objects: list[SceneObject] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    lighting: Lighting = Field(default_factory=Lighting)
    events: list[SceneEvent] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data: object) -> object:
        return coerce_scene_input(data)

    @field_validator("objects")
    @classmethod
    def _unique_ids(cls, v: list[SceneObject]) -> list[SceneObject]:
        ids = [o.id for o in v]
        if len(ids) != len(set(ids)):
            raise ValueError("object ids must be unique")
        return v
