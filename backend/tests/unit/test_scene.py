from __future__ import annotations

import copy

import pytest

from app.core.errors import ValidationFailed
from app.services.scene import builder, geometry, patches
from app.services.scene.render import render_top_down
from app.services.scene.templates import TEMPLATES


def _shop() -> dict:
    s = copy.deepcopy(TEMPLATES["shop"])
    s["people"] = [
        {
            "id": "witness",
            "role": "witness",
            "pos": [3.0, 0.0, 1.0],
            "facing_deg": 0.0,
            "eye_height_m": 1.5,
        },
        {
            "id": "suspect",
            "role": "suspect",
            "pos": [3.0, 0.0, 4.6],
            "facing_deg": 180.0,
            "eye_height_m": 1.6,
        },
    ]
    return s


def test_templates_validate() -> None:
    for name, t in TEMPLATES.items():
        scene = builder.validate(t)
        assert scene.template == name


def test_grid_snap_and_clamp() -> None:
    s = _shop()
    s["objects"][0]["pos"] = [3.13, 0.0, 3.62]
    s["people"][0]["pos"] = [-2.0, 0.0, 99.0]
    scene = builder.normalize(s)
    counter = next(o for o in scene.objects if o.id == "counter")
    assert counter.pos[0] % 0.25 == 0 and counter.pos[2] % 0.25 == 0
    w = next(p for p in scene.people if p.role == "witness")
    assert 0 <= w.pos[0] <= scene.room.width_m and 0 <= w.pos[2] <= scene.room.depth_m


def test_overlap_resolution_nudges() -> None:
    s = _shop()
    s["objects"].append(
        {
            "id": "table",
            "type": "table",
            "pos": [3.0, 0.0, 3.5],
            "rot_y_deg": 0.0,
            "size": [1.0, 0.8, 0.8],
            "locked": False,
        }
    )
    scene = builder.normalize(s)
    counter = next(o for o in scene.objects if o.id == "counter")
    table = next(o for o in scene.objects if o.id == "table")
    assert not geometry.obb_overlap(counter, table)
    assert table.pos != [3.0, 0.0, 3.5]


def test_line_of_sight_clear_blocked_and_distance() -> None:
    s = _shop()
    s["objects"][0]["size"] = [3.0, 1.6, 0.8]  # a tall counter blocks the 1.3 m head line
    scene = builder.validate(s)
    a = geometry.analyse(scene)
    assert a["line_of_sight"] == "blocked" and a["blocking_object_id"] == "counter"
    assert a["distance_m"] == 3.6
    # the standard 1.0 m counter does not reach the 1.3 m head line -> clear
    assert geometry.analyse(builder.validate(_shop()))["line_of_sight"] == "clear"
    s2 = _shop()
    s2["people"][1]["pos"] = [1.0, 0.0, 1.5]
    a2 = geometry.analyse(builder.validate(s2))
    assert a2["line_of_sight"] == "clear" and a2["blocking_object_id"] is None
    assert a2["distance_m"] == 2.1
    s3 = _shop()
    s3["people"][1]["pos"] = [3.0, 0.0, 7.0]  # outside the room -> wall
    assert geometry.analyse(builder.validate(s3))["blocking_object_id"] == "wall"
    s4 = _shop()
    s4["people"] = []
    assert geometry.analyse(builder.validate(s4))["line_of_sight"] == "unknown"


def test_patch_apply_validate_and_locked_rejection() -> None:
    s = _shop()
    s["objects"][0]["locked"] = True
    new = patches.apply_patch(
        s, [{"op": "replace", "path": "/people/0/pos", "value": [2.0, 0.0, 1.0]}]
    )
    assert new.people[0].pos == [2.0, 0.0, 1.0]
    with pytest.raises(ValidationFailed, match="locked"):
        patches.apply_patch(
            s, [{"op": "replace", "path": "/objects/0/pos", "value": [1.0, 0.0, 1.0]}]
        )
    with pytest.raises(ValidationFailed, match="locked"):
        patches.apply_patch(s, [{"op": "remove", "path": "/objects/0"}])
    # explicit unlock is allowed
    unlocked = patches.apply_patch(
        s, [{"op": "replace", "path": "/objects/0/locked", "value": False}]
    )
    assert unlocked.objects[0].locked is False
    with pytest.raises(ValidationFailed):
        patches.apply_patch(s, [{"op": "replace", "path": "/room/width_m", "value": -1}])
    with pytest.raises(ValidationFailed):
        patches.apply_patch(s, [{"op": "replace", "path": "/nope/0", "value": 1}])
    with pytest.raises(ValidationFailed):
        patches.apply_patch(s, [])


def test_patch_is_fast() -> None:
    import time

    s = _shop()
    t0 = time.perf_counter()
    for _ in range(20):
        patches.apply_patch(s, [{"op": "replace", "path": "/people/0/facing_deg", "value": 90}])
    assert (time.perf_counter() - t0) / 20 < 0.2


def test_render_top_down() -> None:
    img = render_top_down(builder.validate(_shop()))
    assert img.ndim == 3 and img.shape[0] > 100 and img.shape[1] > 100


def test_lenient_llm_variations_are_coerced() -> None:
    raw = {
        "template": "shop",
        "room": {"width": 6, "depth": 5},
        "objects": [
            {"id": "counter", "position": {"x": 3, "z": 3.5}, "size": [3, 1, 0.8]},
            "not an object",
        ],
        "people": [
            {"role": "Suspect (male)", "pos": [2, 3]},
            {"role": "witness", "pos": [1, 0, 1]},
        ],
        "evidence": [{"id": "bag", "pos": {"x": 1, "y": 0, "z": 1}}],
        "lighting": "dim",
        "events": ["He came in", {"text": "He left", "positions": {}}],
    }
    scene = builder.validate(raw)
    assert scene.room.width_m == 6 and scene.objects[0].pos == [3.0, 0.0, 3.5]
    assert len(scene.objects) == 1 and scene.objects[0].type == "counter"
    assert scene.people[0].role == "suspect" and scene.people[0].pos == [2.0, 0.0, 3.0]
    assert scene.evidence[0].label == "bag" and scene.lighting.level == "dim"
    assert [e.step for e in scene.events] == [1, 2] and scene.events[1].text == "He left"
