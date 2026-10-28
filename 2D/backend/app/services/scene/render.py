"""Top-down scene rendering to PNG (OpenCV) for exports."""

from __future__ import annotations

import math

import cv2
import numpy as np

from app.services.scene.geometry import analyse, obb_corners
from app.services.scene.schema import Scene

COLOURS = {"witness": (60, 160, 60), "suspect": (40, 40, 220), "other": (160, 120, 60)}


def render_top_down(scene: Scene, px_per_m: float = 80.0, margin: int = 60) -> np.ndarray:
    w = int(scene.room.width_m * px_per_m) + 2 * margin
    h = int(scene.room.depth_m * px_per_m) + 2 * margin
    img = np.full((h, w, 3), 245, np.uint8)

    def pt(x: float, z: float) -> tuple[int, int]:
        return int(margin + x * px_per_m), int(margin + z * px_per_m)

    cv2.rectangle(img, pt(0, 0), pt(scene.room.width_m, scene.room.depth_m), (80, 80, 80), 3)
    for door in scene.room.doors:
        _wall_marker(img, scene, door.wall, door.offset_m, door.width_m, (30, 120, 200), pt)
    for win in scene.room.windows:
        _wall_marker(img, scene, win.wall, win.offset_m, win.width_m, (200, 160, 30), pt)
    for o in scene.objects:
        corners = np.array([pt(x, z) for x, z in obb_corners(o)], np.int32)
        colour = (200, 200, 200) if o.type == "road" else (150, 190, 230)
        cv2.fillPoly(img, [corners], colour)
        cv2.polylines(img, [corners], True, (90, 90, 90), 2)
        cv2.putText(
            img,
            o.id,
            pt(o.pos[0] - o.size[0] / 2, o.pos[2]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (40, 40, 40),
            1,
            cv2.LINE_AA,
        )
    for e in scene.evidence:
        c = pt(e.pos[0], e.pos[2])
        cv2.drawMarker(img, c, (0, 140, 255), cv2.MARKER_TRIANGLE_UP, 18, 2)
        cv2.putText(
            img,
            e.label,
            (c[0] + 8, c[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 100, 200),
            1,
            cv2.LINE_AA,
        )
    for p in scene.people:
        c = pt(p.pos[0], p.pos[2])
        col = COLOURS.get(p.role, COLOURS["other"])
        cv2.circle(img, c, 12, col, -1)
        r = math.radians(p.facing_deg)
        tip = (int(c[0] + 22 * math.sin(r)), int(c[1] - 22 * math.cos(r)))
        cv2.arrowedLine(img, c, tip, col, 2, tipLength=0.4)
        cv2.putText(
            img, p.id, (c[0] + 14, c[1] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA
        )
    a = analyse(scene)
    witness = next((p for p in scene.people if p.role == "witness"), None)
    suspect = next((p for p in scene.people if p.role == "suspect"), None)
    if witness and suspect:
        col = (60, 160, 60) if a["line_of_sight"] == "clear" else (40, 40, 220)
        cv2.line(
            img,
            pt(witness.pos[0], witness.pos[2]),
            pt(suspect.pos[0], suspect.pos[2]),
            col,
            2,
            cv2.LINE_AA,
        )
        label = f"{a['distance_m']} m, line of sight {a['line_of_sight']}"
        cv2.putText(
            img,
            label,
            (margin, h - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (40, 40, 40),
            1,
            cv2.LINE_AA,
        )
    cv2.putText(
        img,
        f"template: {scene.template}  (1 square = 1 m)",
        (margin, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (40, 40, 40),
        1,
        cv2.LINE_AA,
    )
    for x in range(int(scene.room.width_m) + 1):
        cv2.line(img, pt(x, 0), pt(x, scene.room.depth_m), (225, 225, 225), 1)
    for z in range(int(scene.room.depth_m) + 1):
        cv2.line(img, pt(0, z), pt(scene.room.width_m, z), (225, 225, 225), 1)
    return img


def _wall_marker(img, scene, wall, offset, width, colour, pt):  # type: ignore[no-untyped-def]
    if wall == "south":
        a, b = pt(offset, scene.room.depth_m), pt(offset + width, scene.room.depth_m)
    elif wall == "north":
        a, b = pt(offset, 0), pt(offset + width, 0)
    elif wall == "west":
        a, b = pt(0, offset), pt(0, offset + width)
    else:
        a, b = pt(scene.room.width_m, offset), pt(scene.room.width_m, offset + width)
    cv2.line(img, a, b, colour, 6)
