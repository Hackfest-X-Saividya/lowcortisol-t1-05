from __future__ import annotations

import pytest

from app.config import Settings
from app.core.errors import ValidationFailed
from app.providers.registry import build_registry
from app.services.sketch.edit_router import parse_amount, resolve_structured, route_utterance


def test_amount_words() -> None:
    assert parse_amount("jabda thoda chauda karo") == 0.05
    assert parse_amount("make the jaw a little wider") == 0.05
    assert parse_amount("ದವಡೆ ಸ್ವಲ್ಪ ಅಗಲ ಮಾಡಿ") == 0.05
    assert parse_amount("aur chauda") == 0.10
    assert parse_amount("innu agala") == 0.10
    assert parse_amount("bahut chauda") == 0.15
    assert parse_amount("a lot wider") == 0.15
    assert parse_amount("tumba agala") == 0.15
    assert parse_amount("jaw wider") is None


def test_structured_slider_and_locks(settings: Settings) -> None:
    r = resolve_structured(settings, {"param": "jaw_width", "amount": 0.05}, set())
    assert r.type == "geometric" and r.handle_moves and r.region == "jaw"
    r = resolve_structured(settings, {"region": "jaw", "param": "width", "amount": -0.1}, set())
    assert r.param == "jaw_width" and r.amount == -0.1
    r = resolve_structured(settings, {"param": "jaw_width", "amount": 0.05}, {"jaw"})
    assert r.type == "refused" and r.message == "The jaw is locked. Unlock it first."
    r = resolve_structured(settings, {"param": "jaw_width"}, set(), "jaw wider")
    assert r.type == "needs_choice"
    r = resolve_structured(settings, {"param": "jaw_width"}, set(), "jabda thoda chauda karo")
    assert r.type == "geometric" and r.amount == 0.05
    with pytest.raises(ValidationFailed):
        resolve_structured(settings, {"param": "nope"}, set())
    with pytest.raises(ValidationFailed):
        resolve_structured(settings, {"handle_moves": [{"handle": "nope", "dx": 0.1}]}, set())


def test_structured_drag_overlay_inpaint(settings: Settings) -> None:
    r = resolve_structured(
        settings, {"handle_moves": [{"handle": "eye_left_outer", "dx": 0.02}]}, {"eyes"}
    )
    assert r.type == "refused" and "eyes" in r.message
    r = resolve_structured(settings, {"handle_moves": [{"handle": "chin", "dy": 0.02}]}, set())
    assert r.type == "geometric" and r.handle_moves[0]["handle"] == "chin"
    r = resolve_structured(settings, {"type": "overlay", "overlay_id": "spectacles_round"}, set())
    assert r.type == "overlay" and r.region == "eyes"
    r = resolve_structured(settings, {"type": "overlay", "overlay_id": "cap"}, {"hair"})
    assert r.type == "overlay"  # feature locks do not block accessories
    r = resolve_structured(settings, {"type": "overlay", "overlay_id": "scar"}, {"marks"})
    assert r.type == "refused"
    r = resolve_structured(
        settings, {"type": "inpaint", "region": "hair", "prompt": "short grey hair"}, set()
    )
    assert r.type == "inpaint" and r.prompt == "short grey hair"


@pytest.mark.asyncio
async def test_route_utterance_mock(container) -> None:  # type: ignore[no-untyped-def]
    reg = build_registry(container.settings, container.files, container.db)
    s = container.settings
    r = await route_utterance(reg, s, "जबड़ा थोड़ा चौड़ा करो", "make the jaw a bit wider", "hi", set())
    assert r.type == "geometric" and r.param == "jaw_width" and r.amount == 0.05
    r = await route_utterance(reg, s, "jabda chauda karo", "make the jaw wider", "hi", set())
    assert r.type == "needs_choice"
    r = await route_utterance(reg, s, "jabda thoda chauda karo", "", "hi", {"jaw"})
    assert r.type == "refused" and "locked" in r.message
    r = await route_utterance(reg, s, "usne chashma pehna tha", "he wore spectacles", "hi", set())
    assert r.type == "overlay" and r.overlay_id == "spectacles_round"
    r = await route_utterance(reg, s, "", "a scar on the left cheek", "en", set())
    assert r.type == "overlay" and r.overlay_id == "scar"
    assert r.overlay_params.get("position") == "left_cheek"
    r = await route_utterance(reg, s, "", "make the hair grey", "en", set())
    assert r.type == "inpaint" and r.region == "hair"
    r = await route_utterance(reg, s, "", "nose a lot shorter", "en", set())
    assert r.type == "geometric" and r.param == "nose_length" and r.amount == -0.15
    r = await route_utterance(reg, s, "", "blah blah", "en", set())
    assert r.type == "unknown"
    await reg.aclose()
