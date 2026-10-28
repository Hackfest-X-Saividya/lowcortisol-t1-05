"""Live sketch: instant library drawing, background portrait, commit as a version, interim
transcription."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import pytest

from app.services.interview import live_render
from tests.conftest import fake_wav, login, setup_session

API = "/api/v1"


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A one-face base library (grey square; mock mode uses template landmarks)."""
    img = np.full((768, 768, 3), 200, np.uint8)
    cv2.circle(img, (384, 384), 200, (120, 120, 120), -1)
    cv2.imwrite(str(tmp_path / "male_middle_clean.jpg"), img)
    monkeypatch.setattr(live_render, "BASE_DIR", tmp_path)
    live_render._bases.clear()
    live_render._live.clear()
    return tmp_path


def test_pick_base() -> None:
    def sheet(**kw: str) -> dict[str, Any]:
        return {k: {"value": v} for k, v in kw.items()}

    assert live_render.pick_base(sheet(gender="female", age_range="20-25")) == (
        "female",
        "young",
        "clean",
    )
    assert live_render.pick_base(sheet(gender="male", age_range="about 55")) == (
        "male",
        "older",
        "clean",
    )
    assert live_render.pick_base(sheet(facial_hair="thick moustache")) == (
        "male",
        "middle",
        "moustache",
    )
    assert live_render.pick_base(sheet(facial_hair="short beard", age_range="young")) == (
        "male",
        "young",
        "beard",
    )
    assert live_render.pick_base(sheet(facial_hair="no beard")) == ("male", "middle", "clean")


async def _latest(client: httpx.AsyncClient, sid: str, headers: dict[str, str]) -> dict[str, Any]:
    for _ in range(100):
        r = await client.get(f"{API}/sessions/{sid}/interview/render/latest", headers=headers)
        body: dict[str, Any] = r.json()
        if body.get("sketch_b64"):
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("portrait never arrived")


@pytest.mark.asyncio
async def test_live_render_instant_then_portrait_then_commit(
    client: httpx.AsyncClient, users: dict[str, Any], library: Path
) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer, language="en")
    sid, wh = ctx["session_id"], ctx["witness_headers"]

    # nothing described yet
    r = await client.post(f"{API}/sessions/{sid}/interview/render", json={}, headers=wh)
    assert r.status_code == 200 and r.json() == {
        "ready": False,
        "reason": "not_enough_detail",
        "preview_fields": [],
    }

    # words still being spoken: drawn at once from the library face, nothing stored
    r = await client.post(
        f"{API}/sessions/{sid}/interview/render",
        json={"text": "He was about forty with a long nose"},
        headers=wh,
    )
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["ready"] and pv["kind"] == "instant" and pv["version_id"] is None
    assert pv["lines_b64"] and pv["sketch_b64"] and "nose" in pv["preview_fields"]
    tree = (await client.get(f"{API}/sessions/{sid}/sketch-tree", headers=officer)).json()
    assert tree == []

    # the realistic portrait arrives in the background
    lt = await _latest(client, sid, wh)
    assert lt["kind"] == "portrait" and lt["seq"] >= 1

    # a turn saves the description; commit stores the drawing as a version (deduplicated)
    r = await client.post(
        f"{API}/sessions/{sid}/interview/turn",
        json={"text": "He was about thirty, with a long nose and a wide jaw.", "language": "en"},
        headers=wh,
    )
    assert r.status_code == 200
    r = await client.post(
        f"{API}/sessions/{sid}/interview/render", json={"commit": True, "wait_s": 10}, headers=wh
    )
    c1 = r.json()
    assert c1["ready"] and c1["kind"] == "portrait" and c1["version_id"]
    r = await client.post(
        f"{API}/sessions/{sid}/interview/render", json={"commit": True, "wait_s": 0}, headers=wh
    )
    assert r.json()["version_id"] == c1["version_id"]
    v = (await client.get(f"{API}/sketch-versions/{c1['version_id']}", headers=officer)).json()
    assert v["edit"]["type"] == "live" and v["edit"]["render"] == "portrait"
    assert v["provider_info"]["type"] == "live_sketch"

    # a spoken correction warps the same portrait (no new generation needed) -> new version
    await client.post(
        f"{API}/sessions/{sid}/interview/turn",
        json={"text": "make the jaw a bit wider", "language": "en"},
        headers=wh,
    )
    r = await client.post(
        f"{API}/sessions/{sid}/interview/render", json={"commit": True, "wait_s": 10}, headers=wh
    )
    c2 = r.json()
    assert c2["version_id"] != c1["version_id"]
    v2 = (await client.get(f"{API}/sketch-versions/{c2['version_id']}", headers=officer)).json()
    assert v2["parent_id"] == c1["version_id"] and v2["edit"]["adjust"]["jaw_width"] > 0

    au = (
        await client.get(
            f"{API}/audit",
            params={"session_id": sid, "action": "sketch.live_render"},
            headers=officer,
        )
    ).json()
    assert len(au["items"]) == 4

    # another officer cannot read this session's drawings
    other = await login(client, "officer2")
    r = await client.get(f"{API}/sessions/{sid}/interview/render/latest", headers=other)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_interim_transcribe(client: httpx.AsyncClient, users: dict[str, Any]) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer, language="kn")
    sid, wh = ctx["session_id"], ctx["witness_headers"]
    files = {"audio": ("a.wav", fake_wav(), "audio/wav")}
    r = await client.post(
        f"{API}/sessions/{sid}/transcribe", files=files, data={"language": "kn"}, headers=wh
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"]
    # nothing is stored as a statement
    sts = (await client.get(f"{API}/sessions/{sid}/statements", headers=officer)).json()
    assert sts == []
