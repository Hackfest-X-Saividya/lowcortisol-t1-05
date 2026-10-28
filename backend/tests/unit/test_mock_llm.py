from __future__ import annotations

import json

import pytest

from app.providers.mock.llm import MockLLM
from app.services.interview import prompts
from app.services.scene.templates import TEMPLATES

FIX = json.load(open("tests/fixtures/transcripts.json", encoding="utf-8"))


@pytest.mark.asyncio
async def test_mock_translate_uses_fixtures() -> None:
    llm = MockLLM()
    res = await llm.complete_json(
        prompts.translate(FIX["hi"]["free_recall"]["original"], "hi", "en")
    )
    assert res.data["translation"] == FIX["hi"]["free_recall"]["english"]
    res = await llm.complete_json(prompts.translate("What do you remember?", "en", "kn"))
    assert res.data["translation"].startswith("[kn]")


@pytest.mark.asyncio
async def test_mock_extraction_finds_fields() -> None:
    llm = MockLLM()
    res = await llm.complete_json(
        prompts.extract_feature_sheet(
            FIX["hi"]["free_recall"]["original"], FIX["hi"]["free_recall"]["english"], "hi"
        )
    )
    f = res.data["fields"]
    assert f["gender"]["value"] == "male" and f["age_range"]["value"] == "30_40"
    assert f["face_shape"]["value"] == "long" and f["nose"]["value"] == "long"
    assert f["jaw"]["value"] == "wide" and f["eyewear"]["value"] == "spectacles"
    assert "scar" in f["scars"]["value"] and "left cheek" in f["scars"]["value"]
    assert f["place_type"]["value"] == "shop" and f["events"]["value"]
    assert all({"value", "confidence", "source_text"} <= set(v) for v in f.values())
    validated = prompts.FeatureSheetOut.model_validate(res.data)
    assert validated.fields["gender"].confidence == "medium"


@pytest.mark.asyncio
async def test_mock_question_and_leading_check() -> None:
    llm = MockLLM()
    res = await llm.complete_json(
        prompts.phrase_question("nose", "Nose shape and size", {}, [], [])
    )
    assert res.data["question_en"].startswith("What do you remember")
    chk = await llm.complete_json(prompts.leading_check("Did he have a beard?", "facial_hair"))
    assert chk.data["leading"] is True
    chk = await llm.complete_json(prompts.leading_check(res.data["question_en"], "nose"))
    assert chk.data["leading"] is False


@pytest.mark.asyncio
async def test_mock_scene_build_and_command() -> None:
    llm = MockLLM()
    res = await llm.complete_json(
        prompts.build_scene(FIX["en"]["free_recall"]["english"], "", TEMPLATES, {})
    )
    scene = res.data["scene"]
    assert scene["template"] == "shop"
    roles = {p["role"] for p in scene["people"]}
    assert {"witness", "suspect"} <= roles and scene["events"]
    cmd = await llm.complete_json(
        prompts.scene_command(
            "move the counter a little to the left", "move the counter a little to the left", scene
        )
    )
    assert (
        cmd.data["patch"][0]["path"].startswith("/objects/")
        and cmd.data["patch"][0]["value"][0] < 3.0
    )
    none = await llm.complete_json(prompts.scene_command("hello", "hello", scene))
    assert none.data["patch"] == []
