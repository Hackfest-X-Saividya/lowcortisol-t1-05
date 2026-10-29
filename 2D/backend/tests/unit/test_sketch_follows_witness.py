"""The live sketch follows the witness: corrections win, nothing is invented, front view only."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
import pytest

from app.core.errors import ProviderError
from app.providers.base import ImageResult, LLMResult
from app.services.interview import live_render
from app.services.interview.engine import grounded, merge_extracted
from app.services.sketch.landmarks import load_template


def _answered(key: str, value: str) -> dict[str, Any]:
    return {key: {"value": value, "confidence": "high", "source": "question:q1"}}


def _ex(value: str, quote: str, conf: str = "high") -> dict[str, Any]:
    return {"value": value, "confidence": conf, "source_text": quote}


# ---- corrections -------------------------------------------------------------------------------


def test_spoken_correction_replaces_an_earlier_answer() -> None:
    sheet = _answered("gender", "female")
    out = merge_extracted(
        sheet, {"gender": _ex("male", "It's a man.")}, "statement:s2", said="It's a man."
    )
    assert out["gender"]["value"] == "male"


def test_echo_of_older_words_does_not_replace_an_answer() -> None:
    # the LLM re-emits fields from "known so far": not grounded in this turn's words
    sheet = _answered("gender", "male")
    out = merge_extracted(
        sheet, {"gender": _ex("female", "female")}, "statement:s3", said="Skin tone was white"
    )
    assert out["gender"]["value"] == "male"


def test_without_words_answers_still_win_as_before() -> None:
    sheet = _answered("gender", "female")
    out = merge_extracted(sheet, {"gender": _ex("male", "It's a man.")}, "statement:s2")
    assert out["gender"]["value"] == "female"


def test_grounded_matches_the_witness_words() -> None:
    assert grounded("it's a man", "It's a man.")
    assert grounded("long curly hair", "he had long, curly hair I think")
    assert not grounded("female", "skin tone was white")
    assert not grounded("", "anything")


# ---- nothing invented ----------------------------------------------------------------------------


def test_invented_not_remembered_fields_are_dropped() -> None:
    extracted = {
        "gender": _ex("male", "man"),
        "eyes": _ex("not_remembered", "man", "not_remembered"),
        "nose": _ex("not_remembered", "man", "not_remembered"),
    }
    out = merge_extracted({}, extracted, "statement:s1", said="man", answered="gender")
    assert out["gender"]["value"] == "male"
    assert "eyes" not in out and "nose" not in out  # still to be asked


def test_not_remembered_kept_when_the_witness_says_so() -> None:
    unknown = {"eyes": _ex("not_remembered", "I don't remember", "not_remembered")}
    out = merge_extracted({}, unknown, "question:q2", said="I don't remember.", answered="eyes")
    assert out["eyes"]["value"] == "not_remembered"
    # the "don't remember" button sends no words
    out = merge_extracted({}, unknown, "question:q2", said=" | ", answered="eyes")
    assert out["eyes"]["value"] == "not_remembered"
    # said about another field than the one asked: not taken
    out = merge_extracted({}, unknown, "question:q2", said="I don't remember.", answered="nose")
    assert "eyes" not in out


def test_no_sketch_before_gender_is_given() -> None:
    assert not live_render.gender_given({"hair": {"value": "curly hair"}})
    assert live_render.gender_given({"gender": {"value": "male"}})
    assert live_render.gender_given({"gender": {"value": "not_remembered"}})


# ---- front view and the described gender ---------------------------------------------------------


def _turned(lm: np.ndarray, by: float) -> np.ndarray:
    out = lm.copy()
    left, right = out[234, 0], out[454, 0]
    out[1, 0] = left + (0.5 + by) * (right - left)
    return out


def test_head_turn_measure() -> None:
    lm = load_template().landmarks
    assert live_render.head_turn(_turned(lm, 0.0)) < 0.01
    assert live_render.head_turn(_turned(lm, 0.3)) == pytest.approx(0.3, abs=1e-6)


class _Fake:
    """Image service + landmarker + vision check, scripted per attempt."""

    def __init__(self, turns: list[float | None], genders: list[str]) -> None:
        self.turns, self.genders, self.seeds = turns, genders, []
        self.attempt = -1
        ok, png = cv2.imencode(".png", np.full((64, 64, 3), 200, np.uint8))
        self.png = png.tobytes()
        self.template = load_template().landmarks

    async def generate_image(self, req: Any) -> ImageResult:
        self.attempt += 1
        self.seeds.append(req.seed)
        return ImageResult(png=self.png, provider="pollinations", model="flux", seed=req.seed)

    def detect(self, img: np.ndarray) -> list[np.ndarray]:
        turn = self.turns[self.attempt]
        return [] if turn is None else [_turned(self.template, turn)]

    async def vision_json(self, req: Any) -> LLMResult:
        seen = self.genders[self.attempt]
        bad = [] if seen == "male" else [{"field": "gender", "expected": "male", "seen": seen}]
        return LLMResult(data={"matches": not bad, "mismatches": bad}, provider="groq", model="q")


def _container(fake: _Fake) -> Any:
    settings = SimpleNamespace(
        mock_mode=False, sketch_verify=True, cf_inpaint_model="none", inpaint_chain=[]
    )
    return SimpleNamespace(settings=settings, landmarker=fake, providers=fake)


async def test_turned_and_wrong_gender_portraits_are_redrawn() -> None:
    # attempt 1: three-quarter view, attempt 2: front view but a woman, attempt 3: right
    fake = _Fake(turns=[0.3, 0.0, 0.02], genders=["male", "female", "male"])
    photo, res = await live_render._front_facing_photo(
        _container(fake), "man", {"gender": "male"}, 7
    )
    assert fake.attempt == 2 and res.provider == "pollinations"
    assert len(set(fake.seeds)) == 3  # a different seed for every redraw


async def test_no_portrait_when_every_attempt_is_wrong() -> None:
    fake = _Fake(turns=[0.3, None, 0.0], genders=["male", "male", "female"])
    with pytest.raises(ProviderError, match="head turned.*0 faces.*wrong gender"):
        await live_render._front_facing_photo(_container(fake), "man", {"gender": "male"}, 7)


async def test_free_tier_limit_is_waited_out_before_a_redraw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Fake(turns=[0.3, 0.0], genders=["male", "male"])
    real_generate = fake.generate_image
    calls = {"n": 0}

    async def limited(req: Any) -> ImageResult:
        calls["n"] += 1
        if calls["n"] == 2:  # the redraw comes too soon after the first image
            raise ProviderError("Free limit reached. Retry after 31s", provider="pollinations")
        return await real_generate(req)

    waited: list[float] = []

    async def no_sleep(s: float) -> None:
        waited.append(s)

    fake.generate_image = limited  # type: ignore[method-assign]
    monkeypatch.setattr(live_render.asyncio, "sleep", no_sleep)
    photo, res = await live_render._front_facing_photo(
        _container(fake), "man", {"gender": "male"}, 7
    )
    assert waited == [32] and fake.attempt == 1
