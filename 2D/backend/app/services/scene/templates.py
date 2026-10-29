"""Scene templates (shop, room, house, street, junction) stored in assets/templates/scene_templates.

"house" is the sample floor plan (2D/data/image.png): five rooms with all doors and windows.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.scene.sample_plan import sample_scene

TEMPLATES: dict[str, dict[str, Any]] = {
    "shop": {
        "template": "shop",
        "room": {
            "width_m": 6.0,
            "depth_m": 5.0,
            "doors": [{"id": "door_main", "wall": "south", "offset_m": 2.5, "width_m": 1.2}],
            "windows": [{"id": "window_front", "wall": "south", "offset_m": 4.5, "width_m": 1.2}],
        },
        "objects": [
            {
                "id": "counter",
                "type": "counter",
                "pos": [3.0, 0.0, 3.5],
                "rot_y_deg": 0.0,
                "size": [3.0, 1.0, 0.8],
                "locked": False,
            },
            {
                "id": "shelf_left",
                "type": "shelf",
                "pos": [0.3, 0.0, 2.5],
                "rot_y_deg": 0.0,
                "size": [0.5, 2.0, 3.0],
                "locked": False,
            },
            {
                "id": "shelf_right",
                "type": "shelf",
                "pos": [5.7, 0.0, 2.5],
                "rot_y_deg": 0.0,
                "size": [0.5, 2.0, 3.0],
                "locked": False,
            },
            {
                "id": "fridge",
                "type": "fridge",
                "pos": [5.5, 0.0, 4.5],
                "rot_y_deg": 0.0,
                "size": [0.8, 1.8, 0.8],
                "locked": False,
            },
        ],
        "people": [],
        "evidence": [],
        "lighting": {"type": "indoor", "level": "normal", "sources": ["tube light"]},
        "events": [],
    },
    "room": {
        "template": "room",
        "room": {
            "width_m": 4.0,
            "depth_m": 4.0,
            "doors": [{"id": "door", "wall": "south", "offset_m": 0.8, "width_m": 0.9}],
            "windows": [{"id": "window", "wall": "north", "offset_m": 2.0, "width_m": 1.2}],
        },
        "objects": [
            {
                "id": "bed",
                "type": "bed",
                "pos": [3.0, 0.0, 1.5],
                "rot_y_deg": 0.0,
                "size": [1.5, 0.5, 2.0],
                "locked": False,
            },
            {
                "id": "table",
                "type": "table",
                "pos": [1.0, 0.0, 3.25],
                "rot_y_deg": 0.0,
                "size": [1.0, 0.75, 0.6],
                "locked": False,
            },
            {
                "id": "cupboard",
                "type": "cupboard",
                "pos": [0.5, 0.0, 1.0],
                "rot_y_deg": 0.0,
                "size": [0.6, 2.0, 1.2],
                "locked": False,
            },
        ],
        "people": [],
        "evidence": [],
        "lighting": {"type": "indoor", "level": "normal", "sources": ["ceiling light"]},
        "events": [],
    },
    "house": sample_scene(),
    "street": {
        "template": "street",
        "room": {"width_m": 12.0, "depth_m": 8.0, "doors": [], "windows": []},
        "objects": [
            {
                "id": "road",
                "type": "road",
                "pos": [6.0, 0.0, 4.0],
                "rot_y_deg": 0.0,
                "size": [12.0, 0.05, 4.0],
                "locked": True,
            },
            {
                "id": "lamp_post",
                "type": "lamp_post",
                "pos": [2.0, 0.0, 1.5],
                "rot_y_deg": 0.0,
                "size": [0.3, 5.0, 0.3],
                "locked": False,
            },
            {
                "id": "parked_car",
                "type": "car",
                "pos": [9.0, 0.0, 6.5],
                "rot_y_deg": 0.0,
                "size": [4.2, 1.5, 1.8],
                "locked": False,
            },
            {
                "id": "tree",
                "type": "tree",
                "pos": [10.0, 0.0, 1.0],
                "rot_y_deg": 0.0,
                "size": [1.5, 4.0, 1.5],
                "locked": False,
            },
        ],
        "people": [],
        "evidence": [],
        "lighting": {"type": "outdoor", "level": "dim", "sources": ["street light"]},
        "events": [],
    },
    "junction": {
        "template": "junction",
        "room": {"width_m": 16.0, "depth_m": 16.0, "doors": [], "windows": []},
        "objects": [
            {
                "id": "road_ns",
                "type": "road",
                "pos": [8.0, 0.0, 8.0],
                "rot_y_deg": 0.0,
                "size": [6.0, 0.05, 16.0],
                "locked": True,
            },
            {
                "id": "road_ew",
                "type": "road",
                "pos": [8.0, 0.0, 8.0],
                "rot_y_deg": 0.0,
                "size": [16.0, 0.05, 6.0],
                "locked": True,
            },
            {
                "id": "signal",
                "type": "traffic_signal",
                "pos": [4.5, 0.0, 4.5],
                "rot_y_deg": 0.0,
                "size": [0.4, 4.0, 0.4],
                "locked": False,
            },
            {
                "id": "tea_stall",
                "type": "stall",
                "pos": [13.0, 0.0, 2.0],
                "rot_y_deg": 0.0,
                "size": [2.0, 2.2, 1.5],
                "locked": False,
            },
            {
                "id": "auto",
                "type": "auto_rickshaw",
                "pos": [11.5, 0.0, 12.5],
                "rot_y_deg": 90.0,
                "size": [2.6, 1.7, 1.3],
                "locked": False,
            },
        ],
        "people": [],
        "evidence": [],
        "lighting": {"type": "outdoor", "level": "normal", "sources": ["daylight"]},
        "events": [],
    },
}


def ensure_templates(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, scene in TEMPLATES.items():
        p = out_dir / f"{name}.json"
        if not p.exists():
            p.write_text(json.dumps(scene, indent=2), encoding="utf-8")


@lru_cache(maxsize=2)
def load_templates(template_dir: str) -> dict[str, dict[str, Any]]:
    d = Path(template_dir)
    ensure_templates(d)
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(d.glob("*.json")):
        with p.open(encoding="utf-8") as fh:
            out[p.stem] = json.load(fh)
    return out
