"""End-to-end happy path and access-control checks over the HTTP API (mock mode, jobs inline)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from tests.conftest import fake_wav, login, setup_session

API = "/api/v1"
FIX = json.load(open("tests/fixtures/transcripts.json", encoding="utf-8"))


async def job(client: httpx.AsyncClient, job_id: str, headers: dict[str, str]) -> dict[str, Any]:
    r = await client.get(f"{API}/jobs/{job_id}", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "done", data
    return data["result"]


@pytest.mark.asyncio
async def test_happy_path(client: httpx.AsyncClient, users: dict[str, Any]) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer, language="hi")
    sid, wh = ctx["session_id"], ctx["witness_headers"]

    # health / ready
    r = await client.get(f"{API}/ready")
    assert r.status_code == 200 and r.json()["data_mode"] == "local_mock"

    # sketch before free recall -> 409
    r = await client.post(f"{API}/sessions/{sid}/sketch", json={}, headers=wh)
    assert r.status_code == 409 and r.json()["error"]["code"] == "free_recall_required"
    r = await client.get(f"{API}/sessions/{sid}/questions/next", headers=wh)
    assert r.status_code == 409

    # free recall (typed, Hindi) -> transcript, translation, feature sheet
    r = await client.post(
        f"{API}/sessions/{sid}/statements",
        json={
            "text": FIX["hi"]["free_recall"]["original"],
            "language": "hi",
            "kind": "free_recall",
            "source": "typed",
        },
        headers=wh,
    )
    assert r.status_code == 202, r.text
    res = await job(client, r.json()["job_id"], wh)
    assert "gender" in res["extracted_fields"]
    st_id = r.json()["statement_id"]
    r = await client.get(f"{API}/sessions/{sid}/statements/{st_id}", headers=officer)
    st = r.json()
    assert st["status"] == "extracted" and st["transcript_english"].startswith("I was standing")
    r = await client.get(f"{API}/sessions/{sid}/feature-sheet", headers=officer)
    sheet = r.json()["sheet"]
    assert sheet["jaw"]["value"] == "wide" and sheet["age_range"]["value"] == "30_40"

    # audio free recall (mock ASR) for Hindi witness
    files = {"audio": ("rec.wav", fake_wav(), "audio/wav")}
    r = await client.post(
        f"{API}/sessions/{sid}/statements",
        files=files,
        data={"language": "hi", "kind": "free_recall"},
        headers=wh,
    )
    assert r.status_code == 202, r.text
    res = await job(client, r.json()["job_id"], wh)
    assert res["asr_provider"] == "mock"
    r = await client.get(
        f"{API}/sessions/{sid}/statements/{r.json()['statement_id']}", headers=officer
    )
    assert r.json()["segments"] and r.json()["audio_file_id"]

    # bad audio rejected
    r = await client.post(
        f"{API}/sessions/{sid}/statements",
        files={"audio": ("x.bin", b"not audio", "audio/wav")},
        data={"language": "hi"},
        headers=wh,
    )
    assert r.status_code == 415

    # interview: answer questions (option, text, not_remembered) until done or 5 asked
    asked = 0
    answered_types: set[str] = set()
    while asked < 6:
        r = await client.get(f"{API}/sessions/{sid}/questions/next", headers=wh)
        assert r.status_code == 200, r.text
        nq = r.json()
        if nq["done"]:
            break
        q = nq["question"]
        assert q["text_en"] and q["text_local"] and q["leading_check"]["approved"]
        assert any(o["id"] == "not_remembered" for o in q["options"])
        # asking again returns the same open question
        r2 = await client.get(f"{API}/sessions/{sid}/questions/next", headers=wh)
        assert r2.json()["question"]["id"] == q["id"]
        if asked == 0:
            body = {"answer_type": "not_remembered"}
        elif asked == 1 and len(q["options"]) > 1:
            body = {"answer_type": "option", "option_id": q["options"][0]["id"]}
        else:
            body = {"answer_type": "text", "text": "ಕಣ್ಣುಗಳು ದೊಡ್ಡದಾಗಿದ್ದವು", "language": "kn"}
        r = await client.post(
            f"{API}/sessions/{sid}/questions/{q['id']}/answer", json=body, headers=wh
        )
        assert r.status_code == 200, r.text
        answered_types.add(body["answer_type"])
        asked += 1
    assert {"not_remembered", "option", "text"} <= answered_types
    r = await client.get(f"{API}/sessions/{sid}/feature-sheet", headers=officer)
    assert any(v.get("value") == "not_remembered" for v in r.json()["sheet"].values())

    # generate the first face
    r = await client.post(f"{API}/sessions/{sid}/sketch", json={"seed": 42}, headers=wh)
    assert r.status_code == 202
    res = await job(client, r.json()["job_id"], wh)
    v0 = res["version_id"]
    assert res["provider_info"]["provider"] == "mock" and not res["quality_warning"]
    r = await client.get(f"{API}/sketch-versions/{v0}", headers=wh)
    assert r.status_code == 200
    ver = r.json()
    assert ver["master_file_id"] is None and ver["sketch_file_id"]
    assert len(ver["landmarks"]) == 478 and len(ver["handle_positions"]) >= 20
    assert "jaw_width" not in ver["sliders"]
    r = await client.get(f"{API}/sketch-versions/{v0}", headers=officer)
    assert r.json()["master_file_id"]
    sketch_fid = ver["sketch_file_id"]

    # display event
    r = await client.post(
        f"{API}/sessions/{sid}/display-events",
        json={"sketch_version_id": v0, "screen": "witness"},
        headers=wh,
    )
    assert r.status_code == 201
    r = await client.get(f"{API}/sessions/{sid}", headers=officer)
    assert r.json()["first_image_shown_at"] is not None

    # lock eyes
    r = await client.put(
        f"{API}/sessions/{sid}/locks",
        json={"locks": [{"feature": "eyes", "locked": True, "confidence": "sure"}]},
        headers=wh,
    )
    assert r.status_code == 200
    assert next(lk for lk in r.json() if lk["feature"] == "eyes")["locked"] is True

    # voice-style edit: "jaw a bit wider" (Hindi utterance)
    r = await client.post(
        f"{API}/sketch-versions/{v0}/edits",
        json={"source": "voice", "utterance_original": "जबड़ा थोड़ा चौड़ा करो", "language": "hi"},
        headers=wh,
    )
    assert r.status_code == 202
    res = await job(client, r.json()["job_id"], wh)
    assert res["status"] == "created", res
    v1 = res["new_version_id"]
    assert res["parent_version_id"] == v0
    assert res["stability"]["locked_drift_px"] == 0.0 and not res["stability"]["warning"]
    assert res["provider_info"]["type"] == "geometric"
    r = await client.get(f"{API}/sketch-versions/{v1}", headers=wh)
    assert r.json()["sliders"]["jaw_width"] == 0.05

    # edit on locked region refused
    r = await client.post(
        f"{API}/sketch-versions/{v1}/edits",
        json={"source": "slider", "edit": {"param": "eye_size", "amount": 0.1}},
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    assert res["status"] == "refused" and "locked" in res["message"]

    # unclear amount -> needs_choice with 3 previews; explicit previews endpoint
    r = await client.post(
        f"{API}/sketch-versions/{v1}/edits",
        json={"source": "text", "utterance_original": "nose longer", "language": "en"},
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    assert res["status"] == "needs_choice" and len(res["previews"]) == 3
    r = await client.post(
        f"{API}/sketch-versions/{v1}/previews",
        json={"source": "slider", "edit": {"param": "nose_length"}},
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    assert [p["amount"] for p in res["previews"]] == [0.05, 0.10, 0.15]
    r = await client.get(f"{API}/files/{res['previews'][0]['sketch_file_id']}", headers=wh)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"

    # overlay: spectacles
    r = await client.post(
        f"{API}/sketch-versions/{v1}/edits",
        json={"source": "accessory", "edit": {"type": "overlay", "overlay_id": "spectacles_round"}},
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    v2 = res["new_version_id"]
    assert res["provider_info"]["type"] == "overlay"
    r = await client.get(f"{API}/sketch-versions/{v2}", headers=wh)
    assert r.json()["overlays"][0]["overlay_id"] == "spectacles_round"

    # a later warp keeps the overlay (re-applied on the warped face)
    r = await client.post(
        f"{API}/sketch-versions/{v2}/edits",
        json={
            "source": "drag",
            "edit": {"handle_moves": [{"handle": "chin", "dx": 0, "dy": 0.03}], "symmetric": False},
        },
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    v3 = res["new_version_id"]
    r = await client.get(f"{API}/sketch-versions/{v3}", headers=wh)
    assert r.json()["overlays"] and r.json()["edit_source"] == "drag"

    # rating
    r = await client.post(
        f"{API}/sketch-versions/{v3}/rating", json={"rating": "closer"}, headers=wh
    )
    assert r.status_code == 200 and r.json()["witness_rating"] == "closer"

    # branch from the older version v1
    r = await client.post(
        f"{API}/sketch-versions/{v1}/edits",
        json={"source": "slider", "edit": {"param": "lip_fullness", "amount": 0.05}},
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    v4 = res["new_version_id"]
    r = await client.get(f"{API}/sessions/{sid}/sketch-tree", headers=wh)
    tree = {n["id"]: n for n in r.json()}
    assert tree[v4]["parent_id"] == v1 and tree[v2]["parent_id"] == v1 and len(tree) == 5
    r = await client.get(f"{API}/sketch-versions/{v0}/compare/{v3}", headers=officer)
    assert r.status_code == 200 and "stability" in r.json()

    # inpaint edit (mock inpainter) with overlay catalogue check
    r = await client.get(f"{API}/overlays", headers=wh)
    assert any(o["id"] == "scar" for o in r.json())
    r = await client.post(
        f"{API}/sketch-versions/{v3}/edits",
        json={"source": "text", "utterance_original": "make the hair grey", "language": "en"},
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    assert res["status"] == "created" and res["provider_info"]["type"] == "inpaint"

    # audio edit command targeting a version
    files = {"audio": ("cmd.wav", fake_wav("edit_command"), "audio/wav")}
    r = await client.post(
        f"{API}/sessions/{sid}/statements",
        files=files,
        data={"language": "hi", "kind": "edit_command", "target_version_id": v3},
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    assert res["edit_status"] == "created"

    # scene
    r = await client.post(f"{API}/sessions/{sid}/scene", json={}, headers=wh)
    assert r.status_code == 202
    res = await job(client, r.json()["job_id"], wh)
    s0 = res["version_id"]
    assert res["template"] == "shop" and res["analysis"]["distance_m"]
    r = await client.get(f"{API}/scene-versions/{s0}", headers=wh)
    scene = r.json()["scene"]
    idx = next(i for i, o in enumerate(scene["objects"]) if o["id"] == "counter")
    r = await client.post(
        f"{API}/scene-versions/{s0}/patches",
        json={
            "patch": [{"op": "replace", "path": f"/objects/{idx}/pos", "value": [2.5, 0.0, 3.5]}],
            "source": "drag",
        },
        headers=wh,
    )
    assert r.status_code == 201, r.text
    s1 = r.json()["id"]
    assert r.json()["scene"]["objects"][idx]["pos"] == [2.5, 0.0, 3.5]
    r = await client.post(
        f"{API}/scene-versions/{s1}/patches",
        json={"patch": [{"op": "replace", "path": f"/objects/{idx}/locked", "value": True}]},
        headers=officer,
    )
    s2 = r.json()["id"]
    r = await client.post(
        f"{API}/scene-versions/{s2}/patches",
        json={
            "patch": [{"op": "replace", "path": f"/objects/{idx}/pos", "value": [1.0, 0.0, 1.0]}]
        },
        headers=wh,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "object_locked"
    r = await client.post(
        f"{API}/scene-versions/{s1}/commands",
        json={"utterance_original": "काउंटर को थोड़ा बाईं तरफ करो", "language": "hi"},
        headers=wh,
    )
    res = await job(client, r.json()["job_id"], wh)
    assert res["status"] == "created" and res["patch"]
    r = await client.get(f"{API}/sessions/{sid}/scene-tree", headers=wh)
    assert len(r.json()) == 4

    # sign-off
    r = await client.post(
        f"{API}/sessions/{sid}/signoff",
        json={
            "sketch_version_id": v3,
            "confidences": {"eyes": "sure", "jaw": "somewhat"},
            "witness_statement": "This looks close.",
        },
        headers=wh,
    )
    assert r.status_code == 201, r.text
    r = await client.get(f"{API}/sessions/{sid}", headers=officer)
    assert r.json()["status"] == "signed_off"
    # witness token no longer valid after sign-off
    r = await client.get(f"{API}/sessions/{sid}", headers=wh)
    assert r.status_code == 401

    # exports
    export_ids = []
    for kind in ("png", "pdf", "scene_png", "photoreal_png"):
        r = await client.post(f"{API}/sessions/{sid}/exports", json={"kind": kind}, headers=officer)
        assert r.status_code == 202, r.text
        res = await job(client, r.json()["job_id"], officer)
        export_ids.append(res["export_id"])
        r = await client.get(f"{API}/exports/{res['export_id']}", headers=officer)
        assert r.status_code == 200 and r.json()["sha256"] == res["sha256"]
        r = await client.get(f"{API}/files/{res['file_id']}", headers=officer)
        assert r.status_code == 200 and r.headers["x-file-sha256"] == res["sha256"]
        if kind == "pdf":
            assert r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
        else:
            assert r.content.startswith(b"\x89PNG")
    # artist cannot export
    artist = await login(client, "artist1")
    r = await client.post(f"{API}/sessions/{sid}/exports", json={"kind": "png"}, headers=artist)
    assert r.status_code == 403

    # audit: everything written, chain verifies
    supervisor = await login(client, "supervisor1")
    r = await client.post(f"{API}/audit/verify", headers=supervisor)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["checked"] > 50
    r = await client.get(f"{API}/audit", params={"session_id": sid, "limit": 200}, headers=officer)
    assert r.status_code == 200
    actions = {e["action"] for e in r.json()["items"]}
    for expected in (
        "session.started",
        "statement.created",
        "feature_sheet.updated",
        "question.asked",
        "question.answered",
        "version.created",
        "image.shown",
        "locks.updated",
        "scene_version.created",
        "session.signed_off",
        "export.created",
        "file.downloaded",
        "version.viewed",
        "job.submitted",
    ):
        assert expected in actions, expected
    r = await client.get(f"{API}/audit", params={"limit": 5}, headers=officer)
    assert r.json()["next_cursor"] is not None
    assert sketch_fid


@pytest.mark.asyncio
async def test_witness_cannot_fetch_master_or_audit(
    client: httpx.AsyncClient, users: dict[str, Any]
) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer)
    sid, wh = ctx["session_id"], ctx["witness_headers"]
    r = await client.post(
        f"{API}/sessions/{sid}/statements",
        json={"text": FIX["en"]["free_recall"]["original"], "language": "en"},
        headers=wh,
    )
    await job(client, r.json()["job_id"], wh)
    r = await client.post(f"{API}/sessions/{sid}/sketch", json={}, headers=officer)
    res = await job(client, r.json()["job_id"], officer)
    r = await client.get(f"{API}/sketch-versions/{res['version_id']}", headers=officer)
    master_id = r.json()["master_file_id"]
    sketch_id = r.json()["sketch_file_id"]
    r = await client.get(f"{API}/files/{master_id}", headers=wh)
    assert r.status_code == 403
    r = await client.get(f"{API}/files/{sketch_id}", headers=wh)
    assert r.status_code == 200
    r = await client.get(f"{API}/audit", headers=wh)
    assert r.status_code == 403
    r = await client.post(f"{API}/audit/verify", headers=wh)
    assert r.status_code == 403
    r = await client.post(f"{API}/sessions/{sid}/exports", json={"kind": "png"}, headers=wh)
    assert r.status_code == 403
    r = await client.get(f"{API}/sessions/{sid}", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_officer_cannot_open_unassigned_case(
    client: httpx.AsyncClient, users: dict[str, Any]
) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer)
    other = await login(client, "officer2")
    r = await client.get(f"{API}/cases/{ctx['case']['id']}", headers=other)
    assert r.status_code == 403
    r = await client.get(f"{API}/sessions/{ctx['session_id']}", headers=other)
    assert r.status_code == 403
    r = await client.get(f"{API}/cases", headers=other)
    assert r.json()["items"] == []
    # assign and retry
    r = await client.post(
        f"{API}/cases/{ctx['case']['id']}/assignments",
        json={"user_id": users["officer2"].id, "role_on_case": "assisting"},
        headers=officer,
    )
    assert r.status_code == 201
    r = await client.get(f"{API}/cases/{ctx['case']['id']}", headers=other)
    assert r.status_code == 200 and len(r.json()["assignments"]) == 2
    # other station officer cannot create a case at this station
    foreign = await login(client, "officer3")
    r = await client.post(
        f"{API}/cases", json={"case_number": "Z", "station": "Jayanagar PS"}, headers=foreign
    )
    assert r.status_code == 403
    # supervisor sees it through jurisdiction; admin does not
    sup = await login(client, "supervisor1")
    r = await client.get(f"{API}/cases/{ctx['case']['id']}", headers=sup)
    assert r.status_code == 200
    adm = await login(client, "admin1")
    r = await client.get(f"{API}/cases/{ctx['case']['id']}", headers=adm)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_auth_lockout_refresh_logout_and_admin(
    client: httpx.AsyncClient, users: dict[str, Any]
) -> None:
    for _ in range(5):
        r = await client.post(f"{API}/auth/login", json={"username": "artist1", "password": "bad"})
        assert r.status_code == 401
    r = await client.post(
        f"{API}/auth/login", json={"username": "artist1", "password": "Str0ngPassw0rd!"}
    )
    assert r.status_code == 423 and r.json()["error"]["code"] == "account_locked"
    r = await client.post(
        f"{API}/auth/login", json={"username": "officer1", "password": "Str0ngPassw0rd!"}
    )
    tokens = r.json()
    r = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.json()["username"] == "officer1"
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401  # rotated
    r = await client.post(f"{API}/auth/logout", json={"refresh_token": new["refresh_token"]})
    assert r.status_code == 204
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": new["refresh_token"]})
    assert r.status_code == 401
    # admin unlocks the artist and manages users
    adm = await login(client, "admin1")
    r = await client.patch(
        f"{API}/admin/users/{users['artist'].id}", json={"unlock": True}, headers=adm
    )
    assert r.status_code == 200
    r = await client.post(
        f"{API}/auth/login", json={"username": "artist1", "password": "Str0ngPassw0rd!"}
    )
    assert r.status_code == 200
    r = await client.post(
        f"{API}/admin/users",
        json={"username": "new1", "password": "Passw0rd!x", "role": "officer"},
        headers=adm,
    )
    assert r.status_code == 201
    r = await client.get(f"{API}/admin/users", headers=adm)
    assert len(r.json()) == 7
    off = await login(client, "officer1")
    r = await client.get(f"{API}/admin/users", headers=off)
    assert r.status_code == 403
    r = await client.get(f"{API}/nope")
    assert r.status_code == 404 and "request_id" in r.json()["error"]


@pytest.mark.asyncio
async def test_login_rate_limit(client: httpx.AsyncClient, users: dict[str, Any]) -> None:
    codes = []
    for _ in range(12):
        r = await client.post(f"{API}/auth/login", json={"username": "nobody", "password": "x"})
        codes.append(r.status_code)
    assert 429 in codes


@pytest.mark.asyncio
async def test_statement_correction_reruns_and_session_lifecycle(
    client: httpx.AsyncClient, users: dict[str, Any]
) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer)
    sid, wh = ctx["session_id"], ctx["witness_headers"]
    r = await client.post(
        f"{API}/sessions/{sid}/statements",
        json={"text": "He was tall with a long nose.", "language": "en", "source": "browser_asr"},
        headers=wh,
    )
    st_id = r.json()["statement_id"]
    await job(client, r.json()["job_id"], wh)
    r = await client.patch(
        f"{API}/sessions/{sid}/statements/{st_id}",
        json={
            "corrected_transcript_original": "He was short with a broad nose.",
            "note": "mis-typed",
        },
        headers=officer,
    )
    assert r.status_code == 202
    await job(client, r.json()["job_id"], officer)
    r = await client.get(f"{API}/sessions/{sid}/statements/{st_id}", headers=officer)
    assert r.json()["corrections"] and r.json()["corrected_transcript_original"].startswith(
        "He was short"
    )
    r = await client.get(f"{API}/sessions/{sid}/feature-sheet", headers=officer)
    assert r.json()["sheet"]["nose"]["value"] == "broad"
    r = await client.patch(
        f"{API}/sessions/{sid}/statements/{st_id}",
        json={"corrected_transcript_original": "x"},
        headers=wh,
    )
    assert r.status_code == 403
    # pause blocks witness writes; resume; close expires the token
    r = await client.post(f"{API}/sessions/{sid}/pause", headers=officer)
    assert r.json()["status"] == "paused"
    r = await client.post(f"{API}/sessions/{sid}/sketch", json={}, headers=wh)
    assert r.status_code == 409
    r = await client.post(f"{API}/sessions/{sid}/resume", headers=officer)
    assert r.json()["status"] == "active"
    r = await client.post(f"{API}/sessions/{sid}/close", headers=officer)
    assert r.json()["status"] == "closed"
    r = await client.get(f"{API}/sessions/{sid}", headers=wh)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_websocket_receives_events(settings, container, users) -> None:  # type: ignore[no-untyped-def]
    """Event bus -> websocket delivery using Starlette's test client."""
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.main import create_app

    app = create_app(settings, container)
    with TestClient(app) as tc:
        r = tc.post(
            f"{API}/auth/login", json={"username": "officer1", "password": "Str0ngPassw0rd!"}
        )
        tok = r.json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        case = tc.post(f"{API}/cases", json={"case_number": "WS-1"}, headers=h).json()
        w = tc.post(
            f"{API}/cases/{case['id']}/witnesses",
            json={"display_name": "w", "consent_given": True},
            headers=h,
        ).json()
        s = tc.post(
            f"{API}/cases/{case['id']}/sessions", json={"witness_id": w["id"]}, headers=h
        ).json()
        sid, wtok = s["session"]["id"], s["witness_token"]
        with tc.websocket_connect(f"/ws/sessions/{sid}?token={wtok}") as ws:
            assert ws.receive_json()["type"] == "connected"
            ws.send_text("ping")
            assert ws.receive_json()["type"] == "pong"
            tc.post(
                f"{API}/sessions/{sid}/statements",
                json={"text": "He was tall.", "language": "en"},
                headers={"Authorization": f"Bearer {wtok}"},
            )
            types = [ws.receive_json()["type"] for _ in range(3)]
            assert "job.progress" in types
        with pytest.raises(WebSocketDisconnect):
            with tc.websocket_connect(f"/ws/sessions/{sid}?token=bad") as ws:
                ws.receive_json()


@pytest.mark.asyncio
async def test_lists_and_witness_code_reissue(
    client: httpx.AsyncClient, users: dict[str, Any]
) -> None:
    officer = await login(client, "officer1")
    ctx = await setup_session(client, officer)
    sid, wh = ctx["session_id"], ctx["witness_headers"]
    r = await client.post(
        f"{API}/sessions/{sid}/statements",
        json={"text": "He was tall with a long nose.", "language": "en"},
        headers=wh,
    )
    await job(client, r.json()["job_id"], wh)
    r = await client.get(f"{API}/sessions/{sid}/questions/next", headers=wh)
    q = r.json()["question"]
    await client.post(
        f"{API}/sessions/{sid}/questions/{q['id']}/answer",
        json={"answer_type": "not_remembered"},
        headers=wh,
    )
    r = await client.get(f"{API}/sessions/{sid}/statements", headers=wh)
    assert r.status_code == 200 and len(r.json()) == 1
    assert r.json()[0]["transcript_original"].startswith("He was tall")
    r = await client.get(f"{API}/sessions/{sid}/questions", headers=officer)
    assert r.status_code == 200 and r.json()[0]["answer_type"] == "not_remembered"
    other = await login(client, "officer2")
    r = await client.get(f"{API}/sessions/{sid}/questions", headers=other)
    assert r.status_code == 403
    # reissue: new code works, old one stops; witness and other officers cannot reissue
    r = await client.post(f"{API}/sessions/{sid}/witness-token", headers=wh)
    assert r.status_code == 403
    r = await client.post(f"{API}/sessions/{sid}/witness-token", headers=other)
    assert r.status_code == 403
    r = await client.post(f"{API}/sessions/{sid}/witness-token", headers=officer)
    assert r.status_code == 200
    new_wh = {"Authorization": f"Bearer {r.json()['witness_token']}"}
    assert (await client.get(f"{API}/sessions/{sid}", headers=new_wh)).status_code == 200
    assert (await client.get(f"{API}/sessions/{sid}", headers=wh)).status_code == 401
