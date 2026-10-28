"""Live voice interview: one call per turn, sheet updates, drawing adjustments, next question."""

from __future__ import annotations

import io
from typing import Any

import httpx
import pytest
from PIL import Image

from tests.conftest import fake_wav, login, setup_session

API = "/api/v1"


@pytest.mark.asyncio
async def test_live_interview_turns(client: httpx.AsyncClient, users: dict[str, Any]) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer, language="kn")
    sid, wh = ctx["session_id"], ctx["witness_headers"]

    r = await client.get(f"{API}/sessions/{sid}/interview/live", headers=wh)
    assert r.status_code == 200
    st = r.json()
    assert not st["started"] and st["ask_field"] == "free_recall" and st["language"] == "kn"
    assert "ನೆನಪಿರುವುದನ್ನೆಲ್ಲಾ" in st["question_local"]

    # empty turn is refused
    r = await client.post(f"{API}/sessions/{sid}/interview/turn", json={"text": "  "}, headers=wh)
    assert r.status_code == 422

    # free recall (typed English, as the browser transcript would arrive)
    r = await client.post(
        f"{API}/sessions/{sid}/interview/turn",
        json={
            "text": "He was about thirty years old, tall and thin, "
            "with a long nose and a wide jaw.",
            "language": "en",
            "source": "browser_asr",
        },
        headers=wh,
    )
    assert r.status_code == 200, r.text
    t1 = r.json()
    assert {"nose", "jaw", "age_range", "build"} <= set(t1["updated_fields"])
    assert t1["sheet"]["nose"]["value"] == "long" and t1["ask_field"] not in ("nose", "jaw")
    # live sketching asks about the person and the face before the viewing conditions
    from app.services.interview.fields import FIELD_MAP

    assert FIELD_MAP[t1["ask_field"]].stage in ("overall", "face")
    assert t1["reply_local"] and t1["reply_en"].endswith("?") and not t1["done"]
    s = (await client.get(f"{API}/sessions/{sid}", headers=wh)).json()
    assert s["has_free_recall"] and s["question_count"] == 1

    # answer + a drawing correction in the same breath
    r = await client.post(
        f"{API}/sessions/{sid}/interview/turn",
        json={"text": "make the jaw a bit wider", "language": "en", "source": "typed"},
        headers=wh,
    )
    t2 = r.json()
    assert t2["adjust"]["jaw_width"] == pytest.approx(0.05)
    assert t2["reply_en"].startswith("Done")

    # "I don't remember" moves on without an LLM call
    r = await client.post(
        f"{API}/sessions/{sid}/interview/turn", json={"dont_remember": True}, headers=wh
    )
    t3 = r.json()
    assert t3["provider"] == "none" and t3["ask_field"] != t2["ask_field"]
    qs = (await client.get(f"{API}/sessions/{sid}/questions", headers=officer)).json()
    assert qs[1]["answer_type"] == "not_remembered" and all(q["options"] == [] for q in qs)

    # audio turn goes through Whisper (mock ASR)
    files = {"audio": ("t.wav", fake_wav(), "audio/wav")}
    r = await client.post(
        f"{API}/sessions/{sid}/interview/turn", files=files, data={"language": "kn"}, headers=wh
    )
    assert r.status_code == 200 and r.json()["transcript_original"]

    # leading LLM wording is never used: every stored question passes the rule check
    from app.services.interview.leading_check import rule_check

    qs = (await client.get(f"{API}/sessions/{sid}/questions", headers=officer)).json()
    assert all(rule_check(q["text_en"], q["field_key"]) is None for q in qs)

    # TTS: no provider in mock mode -> 204 so the browser shows text only
    r = await client.post(f"{API}/tts", json={"text": "ಮೂಗು ಹೇಗಿತ್ತು?", "language": "kn"}, headers=wh)
    assert r.status_code == 204

    # save the live drawing as a sketch version; the witness sees it, the officer exports it
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (228, 211, 168)).save(buf, format="PNG")
    r = await client.post(
        f"{API}/sessions/{sid}/sketch/live",
        files={"image": ("sketch.png", buf.getvalue(), "image/png")},
        data={"params": '{"jawW": 1.1}'},
        headers=wh,
    )
    assert r.status_code == 201, r.text
    vid = r.json()["version_id"]
    v = (await client.get(f"{API}/sketch-versions/{vid}", headers=officer)).json()
    assert v["edit"]["type"] == "live" and v["edit"]["params"]["jawW"] == 1.1
    r = await client.post(
        f"{API}/sessions/{sid}/sketch/live",
        files={"image": ("x.png", b"not a png", "image/png")},
        headers=wh,
    )
    assert r.status_code == 415

    # audit trail for every turn
    au = (
        await client.get(
            f"{API}/audit", params={"session_id": sid, "action": "interview.turn"}, headers=officer
        )
    ).json()
    assert len(au["items"]) == 4  # the empty turn was refused


@pytest.mark.asyncio
async def test_live_turn_permissions(client: httpx.AsyncClient, users: dict[str, Any]) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer)
    other = await login(client, "officer2")
    r = await client.post(
        f"{API}/sessions/{ctx['session_id']}/interview/turn", json={"text": "hello"}, headers=other
    )
    assert r.status_code == 403
    await client.post(f"{API}/sessions/{ctx['session_id']}/pause", headers=officer)
    r = await client.post(
        f"{API}/sessions/{ctx['session_id']}/interview/turn",
        json={"text": "hello"},
        headers=ctx["witness_headers"],
    )
    assert r.status_code == 409
