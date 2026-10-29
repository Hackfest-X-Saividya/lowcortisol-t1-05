"""Floor-plane geometry: oriented bounding boxes, overlap, line of sight, distance."""

from __future__ import annotations

import math
from typing import Any

from app.services.scene.schema import Scene, SceneObject

SUSPECT_HEAD_M = 1.3
DEFAULT_EYE_M = 1.5


def _rot(x: float, z: float, deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return c * x - s * z, s * x + c * z


def obb_corners(o: SceneObject) -> list[tuple[float, float]]:
    hw, hd = o.size[0] / 2, o.size[2] / 2
    cx, cz = o.pos[0], o.pos[2]
    out = []
    for dx, dz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
        rx, rz = _rot(dx, dz, o.rot_y_deg)
        out.append((cx + rx, cz + rz))
    return out


def _project(corners: list[tuple[float, float]], axis: tuple[float, float]) -> tuple[float, float]:
    vals = [c[0] * axis[0] + c[1] * axis[1] for c in corners]
    return min(vals), max(vals)


def obb_overlap(a: SceneObject, b: SceneObject) -> bool:
    """Separating axis test for two floor OBBs."""
    ca, cb = obb_corners(a), obb_corners(b)
    axes = []
    for corners in (ca, cb):
        for i in range(2):
            x1, z1 = corners[i]
            x2, z2 = corners[i + 1]
            ex, ez = x2 - x1, z2 - z1
            n = math.hypot(ex, ez) or 1.0
            axes.append((-ez / n, ex / n))
    for ax in axes:
        amin, amax = _project(ca, ax)
        bmin, bmax = _project(cb, ax)
        if amax <= bmin + 1e-6 or bmax <= amin + 1e-6:
            return False
    return True


def segment_hits_box(
    p0: tuple[float, float, float], p1: tuple[float, float, float], o: SceneObject
) -> bool:
    """Slab test of the segment p0->p1 against the object's rotated 3D box."""

    # move into the box's local frame (rotate by -rot about its centre)
    def local(p: tuple[float, float, float]) -> tuple[float, float, float]:
        lx, lz = _rot(p[0] - o.pos[0], p[2] - o.pos[2], -o.rot_y_deg)
        return lx, p[1] - o.pos[1], lz

    a, b = local(p0), local(p1)
    half = (o.size[0] / 2, o.size[1], o.size[2] / 2)  # y from 0..h
    lo = (-half[0], 0.0, -half[2])
    hi = (half[0], half[1], half[2])
    t0, t1 = 0.0, 1.0
    for i in range(3):
        d = b[i] - a[i]
        if abs(d) < 1e-9:
            if a[i] < lo[i] or a[i] > hi[i]:
                return False
            continue
        ta, tb = (lo[i] - a[i]) / d, (hi[i] - a[i]) / d
        if ta > tb:
            ta, tb = tb, ta
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return False
    return True


def _inside_polygon(poly: list[list[float]], x: float, z: float) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, zi = poly[i]
        xj, zj = poly[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi) + xi:
            inside = not inside
        j = i
    return inside


def _inside_room(scene: Scene, x: float, z: float) -> bool:
    if len(scene.room.outline) >= 3:
        return _inside_polygon(scene.room.outline, x, z)
    return 0.0 <= x <= scene.room.width_m and 0.0 <= z <= scene.room.depth_m


def _wall_blocking(scene: Scene, p0: tuple[float, float], p1: tuple[float, float]) -> str | None:
    """Id of the first plan wall the floor segment p0->p1 crosses outside a door or window."""
    rx, rz = p1[0] - p0[0], p1[1] - p0[1]
    for w in scene.room.walls:
        (ax, az), (bx, bz) = w.a, w.b
        sx, sz = bx - ax, bz - az
        denom = rx * sz - rz * sx
        if abs(denom) < 1e-9:
            continue  # parallel
        qx, qz = ax - p0[0], az - p0[1]
        t = (qx * sz - qz * sx) / denom  # along the sight line
        u = (qx * rz - qz * rx) / denom  # along the wall
        if not (0.0 <= t <= 1.0 and 0.0 <= u <= 1.0):
            continue
        along = u * math.hypot(sx, sz)
        if any(op.offset_m <= along <= op.offset_m + op.width_m for op in w.openings):
            continue  # seen through a doorway or a window
        return w.id
    return None


def analyse(scene: Scene) -> dict[str, Any]:
    witness = next((p for p in scene.people if p.role == "witness"), None)
    suspect = next((p for p in scene.people if p.role == "suspect"), None)
    if witness is None or suspect is None:
        return {
            "distance_m": None,
            "line_of_sight": "unknown",
            "blocking_object_id": None,
            "reason": "witness or suspect not placed",
        }
    dx, dz = suspect.pos[0] - witness.pos[0], suspect.pos[2] - witness.pos[2]
    distance = round(math.hypot(dx, dz) + 1e-9, 1)
    eye = (witness.pos[0], witness.eye_height_m or DEFAULT_EYE_M, witness.pos[2])
    head = (suspect.pos[0], SUSPECT_HEAD_M, suspect.pos[2])
    if _inside_room(scene, witness.pos[0], witness.pos[2]) != _inside_room(
        scene, suspect.pos[0], suspect.pos[2]
    ):
        return {"distance_m": distance, "line_of_sight": "blocked", "blocking_object_id": "wall"}
    wall = _wall_blocking(scene, (eye[0], eye[2]), (head[0], head[2]))
    if wall is not None:
        return {"distance_m": distance, "line_of_sight": "blocked", "blocking_object_id": wall}
    for o in scene.objects:
        if o.type == "road":
            continue
        if segment_hits_box(eye, head, o):
            return {"distance_m": distance, "line_of_sight": "blocked", "blocking_object_id": o.id}
    return {"distance_m": distance, "line_of_sight": "clear", "blocking_object_id": None}
