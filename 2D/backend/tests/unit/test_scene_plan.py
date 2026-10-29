"""The sample floor plan (2D/data/image.png): plan walls, line of sight, rendering, upload."""

from __future__ import annotations

import copy

import cv2
import httpx
import numpy as np
import pytest

from app.db.models.users import User
from app.services.scene import builder, geometry, sample_plan
from app.services.scene.render import render_top_down
from app.services.scene.schema import Scene
from app.services.scene.templates import TEMPLATES
from tests.conftest import login


def _people(scene: dict, witness: list[float], suspect: list[float]) -> dict:
    s = copy.deepcopy(scene)
    s["people"] = [
        {"id": "witness", "role": "witness", "pos": witness, "facing_deg": 0.0},
        {"id": "suspect", "role": "suspect", "pos": suspect, "facing_deg": 0.0},
    ]
    return s


def test_sample_plan_has_every_door_and_window() -> None:
    scene = builder.normalize(sample_plan.sample_scene())
    ops = [op for w in scene.room.walls for op in w.openings]
    assert len(scene.room.walls) == 10
    assert sum(op.kind == "door" for op in ops) == 5
    assert sum(op.kind == "window" for op in ops) == 7
    assert [a.name for a in scene.room.areas] == ["Room 1", "Room 2", "Room 3", "Hall", "Room 4"]
    assert (scene.room.width_m, scene.room.depth_m) == (8.9, 6.75)
    # every opening fits on its wall
    for w in scene.room.walls:
        length = float(np.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1]))
        for op in w.openings:
            assert 0 <= op.offset_m and op.offset_m + op.width_m <= length + 1e-9, op.id
    assert TEMPLATES["house"]["room"]["walls"] == sample_plan.SAMPLE_FLOOR_PLAN["room"]["walls"]


def test_plan_walls_block_sight_except_through_doors() -> None:
    plan = sample_plan.sample_scene()
    # room 1 to room 3 straight through the wall between them
    blocked = geometry.analyse(Scene.model_validate(_people(plan, [1.0, 0, 1.5], [1.0, 0, 4.0])))
    assert blocked["line_of_sight"] == "blocked"
    assert blocked["blocking_object_id"] == "wall_rooms_hall"
    # hall to room 1 through its open door
    clear = geometry.analyse(Scene.model_validate(_people(plan, [4.05, 0, 4.0], [4.05, 0, 1.5])))
    assert clear["line_of_sight"] == "clear"
    # the cut-away south-east corner is outside the house
    outside = geometry.analyse(Scene.model_validate(_people(plan, [5.0, 0, 4.0], [5.0, 0, 6.0])))
    assert outside["blocking_object_id"] == "wall"


def test_plain_room_unchanged_by_plan_fields() -> None:
    room = Scene.model_validate(TEMPLATES["room"]).room
    assert room.walls == [] and room.outline == [] and room.areas == []


def test_llm_plan_is_tidied() -> None:
    raw = {
        "room": {
            "walls": [
                {"a": {"x": 0, "z": 0}, "b": [5, 0, 0], "openings": [{"type": "Window"}]},
                {"id": "w", "a": [5, 0], "b": [5, 4], "openings": [{"opens": "right"}]},
                {"id": "w", "a": [0, 4], "b": [5, 4]},
            ]
        }
    }
    room = Scene.model_validate(raw).room
    assert (room.width_m, room.depth_m) == (5.0, 4.0)
    assert [w.id for w in room.walls] == ["wall_1", "w", "w_2"]
    assert room.walls[0].openings[0].kind == "window"
    assert room.walls[1].openings[0].opens == "east"


def test_render_top_down_draws_plan() -> None:
    img = render_top_down(builder.normalize(sample_plan.sample_scene()))
    assert img.shape[0] > 500 and img.shape[1] > 700


@pytest.mark.skipif(sample_plan.sample_image() is None, reason="2D/data/image.png missing")
def test_sample_image_is_recognised() -> None:
    ref = sample_plan.sample_image()
    assert ref is not None and sample_plan.is_sample_image(ref)
    img = cv2.imdecode(np.frombuffer(ref, np.uint8), cv2.IMREAD_COLOR)
    ok, jpg = cv2.imencode(".jpg", cv2.resize(img, (820, 548)))
    assert ok and sample_plan.is_sample_image(jpg.tobytes())
    ok, blank = cv2.imencode(".png", np.full((300, 400, 3), 255, np.uint8))
    assert ok and not sample_plan.is_sample_image(blank.tobytes())


@pytest.mark.skipif(sample_plan.sample_image() is None, reason="2D/data/image.png missing")
async def test_upload_falls_back_to_sample_plan(
    client: httpx.AsyncClient, users: dict[str, User]
) -> None:
    h = await login(client, "officer1")
    url = "/api/v1/sessions/any/scene/analyze-map"
    ref = sample_plan.sample_image()
    assert ref is not None
    r = await client.post(url, files={"image": ("plan.png", ref, "image/png")}, headers=h)
    body = r.json()
    assert r.status_code == 200 and body["_source"] == "sample" and "_error" not in body
    assert len(body["room"]["walls"]) == 10
    # mock mode has no Gemini: another image still gets walls, doors and windows
    ok, other = cv2.imencode(".png", np.full((300, 400, 3), 255, np.uint8))
    r = await client.post(url, files={"image": ("x.png", other.tobytes(), "image/png")}, headers=h)
    body = r.json()
    assert body["_source"] == "sample" and body["_error"]
    assert len(body["room"]["walls"]) == 10


async def test_upload_without_openings_falls_back_to_sample_plan(
    client: httpx.AsyncClient, users: dict[str, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A vision answer with no walls, doors or windows is not a floor plan: use the sample."""
    import app.providers.gemini as gemini
    from app.config import Settings

    class BareRoomVision:
        def __init__(self, settings: Settings) -> None:
            pass

        async def analyze(self, *args: object, **kwargs: object) -> dict:
            return {"room": {"width_m": 6, "depth_m": 5}, "objects": []}

    monkeypatch.setattr(Settings, "gemini_configured", property(lambda self: True))
    monkeypatch.setattr(gemini, "GeminiVision", BareRoomVision)
    h = await login(client, "officer1")
    ok, other = cv2.imencode(".png", np.full((300, 400, 3), 255, np.uint8))
    r = await client.post(
        "/api/v1/sessions/any/scene/analyze-map",
        files={"image": ("x.png", other.tobytes(), "image/png")},
        headers=h,
    )
    body = r.json()
    assert body["_source"] == "sample" and "no walls" in body["_error"]
    assert len(body["room"]["walls"]) == 10
