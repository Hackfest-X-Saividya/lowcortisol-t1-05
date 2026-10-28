"""Scene builder: LLM output -> validate -> snap to 0.25 m grid -> resolve overlaps -> clamp."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import ValidationError

from app.core.errors import ValidationFailed
from app.services.scene.geometry import obb_overlap
from app.services.scene.schema import Scene, SceneObject

GRID_M = 0.25


def snap(v: float, grid: float = GRID_M) -> float:
    return round(round(v / grid) * grid, 4)


def validate(scene_dict: dict[str, Any]) -> Scene:
    try:
        return Scene.model_validate(scene_dict)
    except ValidationError as exc:
        raise ValidationFailed("Invalid scene JSON", details={"errors": exc.errors()[:10]})


def snap_scene(scene: Scene) -> Scene:
    s = scene.model_copy(deep=True)
    for o in s.objects:
        o.pos = [snap(o.pos[0]), 0.0 if abs(o.pos[1]) < 1e-6 else snap(o.pos[1]), snap(o.pos[2])]
    for p in s.people:
        p.pos = [snap(p.pos[0]), 0.0, snap(p.pos[2])]
    for e in s.evidence:
        e.pos = [snap(e.pos[0]), 0.0, snap(e.pos[2])]
    return s


def clamp_scene(scene: Scene) -> Scene:
    s = scene.model_copy(deep=True)
    w, d = s.room.width_m, s.room.depth_m
    for o in s.objects:
        hw, hd = min(o.size[0] / 2, w / 2), min(o.size[2] / 2, d / 2)
        o.pos[0] = min(max(o.pos[0], hw), w - hw)
        o.pos[2] = min(max(o.pos[2], hd), d - hd)
    for p in s.people:
        p.pos[0] = min(max(p.pos[0], 0.25), w - 0.25)
        p.pos[2] = min(max(p.pos[2], 0.25), d - 0.25)
    for e in s.evidence:
        e.pos[0] = min(max(e.pos[0], 0.0), w)
        e.pos[2] = min(max(e.pos[2], 0.0), d)
    return s


def resolve_overlaps(scene: Scene, max_iter: int = 40) -> Scene:
    """Nudge unlocked objects along +x (then +z) by one grid step until no two overlap."""
    s = scene.model_copy(deep=True)
    movable = [o for o in s.objects if o.type != "road"]
    for _ in range(max_iter):
        moved = False
        for i, a in enumerate(movable):
            for b in movable[i + 1 :]:
                if not obb_overlap(a, b):
                    continue
                target: SceneObject | None = b if not b.locked else (a if not a.locked else None)
                if target is None:
                    continue
                if target.pos[0] + GRID_M + target.size[0] / 2 <= s.room.width_m:
                    target.pos[0] = snap(target.pos[0] + GRID_M)
                elif target.pos[2] + GRID_M + target.size[2] / 2 <= s.room.depth_m:
                    target.pos[2] = snap(target.pos[2] + GRID_M)
                else:
                    target.pos[0] = snap(max(target.size[0] / 2, target.pos[0] - GRID_M))
                moved = True
        if not moved:
            break
    return s


def normalize(scene_dict: dict[str, Any]) -> Scene:
    scene = validate(copy.deepcopy(scene_dict))
    scene = snap_scene(scene)
    scene = clamp_scene(scene)
    scene = resolve_overlaps(scene)
    return clamp_scene(scene)
