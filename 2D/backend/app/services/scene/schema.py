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


def _vec2(v: object) -> object:
    """[x, z] from [x, z], [x, y, z] or {"x", "z"}."""
    if isinstance(v, dict):
        return [float(v.get("x", 0.0)), float(v["z"] if "z" in v else v.get("y", 0.0))]
    if isinstance(v, list | tuple) and len(v) == 3:
        return [float(v[0]), float(v[2])]
    return v


class Opening(BaseModel):
    """A door or window in a plan wall, measured from the wall's start point `a`."""

    id: str
    kind: Literal["door", "window"] = "door"
    offset_m: float = 0.0
    width_m: float = Field(default=0.9, gt=0.1)
    hinge: Literal["start", "end"] = "start"  # door: hinged at the edge nearer a, or nearer b
    opens: Wall | None = None  # door: the side of the wall its leaf swings into


class PlanWall(BaseModel):
    """A straight wall from a to b ([x, z] in metres) in a multi-room floor plan."""

    id: str
    a: list[float]
    b: list[float]
    exterior: bool = True
    openings: list[Opening] = Field(default_factory=list)

    @field_validator("a", "b", mode="before")
    @classmethod
    def _point(cls, v: object) -> object:
        return _vec2(v)

    @field_validator("a", "b")
    @classmethod
    def _two(cls, v: list[float]) -> list[float]:
        if len(v) != 2:
            raise ValueError("wall points must be [x, z]")
        return [float(x) for x in v]


class Area(BaseModel):
    """A named space on the plan (bedroom, hall, ...); rect is [x0, z0, x1, z1]."""

    id: str
    name: str
    rect: list[float]

    @field_validator("rect")
    @classmethod
    def _rect(cls, v: list[float]) -> list[float]:
        if len(v) != 4:
            raise ValueError("rect must be [x0, z0, x1, z1]")
        return [float(x) for x in v]


class Room(BaseModel):
    """The place. A plain room is width x depth with doors/windows on its four sides; a floor
    plan also lists `walls` (outer and inner, each with its openings), which then replace the
    four sides, an `outline` polygon of the floor and named `areas`."""

    width_m: float = Field(gt=0.5, le=200)
    depth_m: float = Field(gt=0.5, le=200)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    walls: list[PlanWall] = Field(default_factory=list)
    outline: list[list[float]] = Field(default_factory=list)
    areas: list[Area] = Field(default_factory=list)

    @field_validator("outline", mode="before")
    @classmethod
    def _outline(cls, v: object) -> object:
        return [_vec2(p) for p in v] if isinstance(v, list) else v


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


_SIDES = {"top": "north", "bottom": "south", "left": "west", "right": "east"}


def _side(v: object, default: str | None) -> str | None:
    s = str(v or "").lower()
    if s in ("north", "south", "east", "west"):
        return s
    return _SIDES.get(s, default)


def _coerce_plan(room: dict[str, object]) -> None:
    """Tidy plan walls from LLM output: wall names, unique ids, bounding size from the walls."""
    for key in ("doors", "windows"):
        items = room.get(key)
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    it["wall"] = _side(it.get("wall"), "south" if key == "doors" else "north")
    walls = room.get("walls")
    if not isinstance(walls, list):
        return
    seen: set[str] = set()

    def unique(base: str) -> str:
        new, k = base, 2
        while new in seen:
            new, k = f"{base}_{k}", k + 1
        seen.add(new)
        return new

    xs: list[float] = []
    zs: list[float] = []
    fixed = []
    for i, w in enumerate(walls):
        if not isinstance(w, dict):
            continue
        w = dict(w)
        w["id"] = unique(str(w.get("id") or f"wall_{i + 1}"))
        for end in ("a", "b"):
            p = _vec2(w.get(end))
            if isinstance(p, list) and len(p) == 2:
                xs.append(float(p[0]))
                zs.append(float(p[1]))
        ops = []
        for j, op in enumerate(w.get("openings") or []):
            if not isinstance(op, dict):
                continue
            op = dict(op)
            kind = str(op.get("kind") or op.get("type") or "door").lower()
            op["kind"] = "window" if "window" in kind else "door"
            op["id"] = unique(str(op.get("id") or f"{op['kind']}_{i + 1}_{j + 1}"))
            if "opens" in op:
                op["opens"] = _side(op.get("opens"), None)
            if str(op.get("hinge", "start")).lower() not in ("start", "end"):
                op["hinge"] = "start"
            ops.append(op)
        w["openings"] = ops
        fixed.append(w)
    room["walls"] = fixed
    if xs and zs:
        room.setdefault("width_m", max(xs))
        room.setdefault("depth_m", max(zs))


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
        _coerce_plan(room)
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
