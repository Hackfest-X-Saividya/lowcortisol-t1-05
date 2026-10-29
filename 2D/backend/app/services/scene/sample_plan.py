"""The sample floor plan (2D/data/image.png) as a scene, traced from the drawing.

It is the reference layout for every floor plan: the "house" scene template, the worked example
shown to the vision model, and what an upload falls back to when the image cannot be read.

Scale: the drawn doors are 40 px wide, taken as 0.9 m (1 m = 44.4 px). Origin is the north-west
outer corner, x runs east, z runs south. Openings are measured from each wall's start point `a`.
Five spaces: two rooms across the top, a large room bottom-left, an entrance hall in the middle
(front door on its south wall) and a small room on the east, with the south-east corner cut away.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from app.config import BACKEND_DIR

SAMPLE_IMAGE_PATH = BACKEND_DIR.parent / "data" / "image.png"


def _door(id_: str, offset: float, hinge: str, opens: str, width: float = 0.9) -> dict[str, Any]:
    return {
        "id": id_,
        "kind": "door",
        "offset_m": offset,
        "width_m": width,
        "hinge": hinge,
        "opens": opens,
    }


def _window(id_: str, offset: float, width: float) -> dict[str, Any]:
    return {"id": id_, "kind": "window", "offset_m": offset, "width_m": width}


def _wall(
    id_: str, a: list[float], b: list[float], exterior: bool, *openings: dict[str, Any]
) -> dict[str, Any]:
    return {"id": id_, "a": a, "b": b, "exterior": exterior, "openings": list(openings)}


SAMPLE_FLOOR_PLAN: dict[str, Any] = {
    "template": "house",
    "room": {
        "width_m": 8.9,
        "depth_m": 6.75,
        "doors": [],
        "windows": [],
        "outline": [[0.0, 0.0], [8.9, 0.0], [8.9, 5.2], [3.2, 5.2], [3.2, 6.75], [0.0, 6.75]],
        "walls": [
            _wall(
                "wall_north",
                [0.0, 0.0],
                [8.9, 0.0],
                True,
                _window("window_room1_north", 1.6, 1.8),
                _window("window_room2_north_a", 5.15, 1.7),
                _window("window_room2_north_b", 6.95, 1.75),
            ),
            _wall(
                "wall_east",
                [8.9, 0.0],
                [8.9, 5.2],
                True,
                _window("window_room4_east", 2.95, 1.75),
            ),
            _wall(
                "wall_south_hall",
                [3.2, 5.2],
                [8.9, 5.2],
                True,
                _door("door_front", 1.65, "end", "south"),
            ),
            _wall("wall_south_step", [3.2, 5.2], [3.2, 6.75], True),
            _wall(
                "wall_south_room3",
                [0.0, 6.75],
                [3.2, 6.75],
                True,
                _window("window_room3_south", 0.65, 1.8),
            ),
            _wall(
                "wall_west",
                [0.0, 0.0],
                [0.0, 6.75],
                True,
                _window("window_room1_west", 0.45, 1.8),
                _window("window_room3_west", 3.85, 1.75),
            ),
            _wall(
                "wall_rooms_hall",
                [0.0, 2.5],
                [8.9, 2.5],
                False,
                _door("door_room1", 3.6, "end", "north"),
                _door("door_room2", 5.25, "start", "north"),
            ),
            _wall("wall_room1_room2", [4.95, 0.0], [4.95, 2.5], False),
            _wall(
                "wall_hall_room3",
                [3.2, 2.5],
                [3.2, 5.2],
                False,
                _door("door_room3", 0.3, "start", "west"),
            ),
            _wall(
                "wall_hall_room4",
                [6.35, 2.5],
                [6.35, 5.2],
                False,
                _door("door_room4", 0.3, "start", "east"),
            ),
        ],
        "areas": [
            {"id": "room1", "name": "Room 1", "rect": [0.0, 0.0, 4.95, 2.5]},
            {"id": "room2", "name": "Room 2", "rect": [4.95, 0.0, 8.9, 2.5]},
            {"id": "room3", "name": "Room 3", "rect": [0.0, 2.5, 3.2, 6.75]},
            {"id": "hall", "name": "Hall", "rect": [3.2, 2.5, 6.35, 5.2]},
            {"id": "room4", "name": "Room 4", "rect": [6.35, 2.5, 8.9, 5.2]},
        ],
    },
    "objects": [],
    "people": [],
    "evidence": [],
    "lighting": {"type": "indoor", "level": "normal", "sources": ["ceiling light"]},
    "events": [],
}


def sample_scene() -> dict[str, Any]:
    return copy.deepcopy(SAMPLE_FLOOR_PLAN)


@lru_cache(maxsize=1)
def sample_image() -> bytes | None:
    try:
        return SAMPLE_IMAGE_PATH.read_bytes()
    except OSError:
        return None


def _thumb(data: bytes) -> Any:
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return cv2.resize(img, (64, 48), interpolation=cv2.INTER_AREA).astype(np.float32)


def is_sample_image(data: bytes) -> bool:
    """True when the upload is the sample plan (also after re-saving, resizing or a screenshot)."""
    ref = sample_image()
    if ref is None:
        return False
    if data == ref:
        return True
    a, b = _thumb(data), _thumb(ref)
    if a is None or b is None:
        return False
    return float(abs(a - b).mean()) < 12.0
