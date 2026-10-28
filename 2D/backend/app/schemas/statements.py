from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

Language = Literal["hi", "kn", "en"]
Kind = Literal["free_recall", "answer_audio", "edit_command", "scene_command"]


class StatementTextCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    language: Language = "en"
    kind: Kind = "free_recall"
    source: Literal["typed", "browser_asr"] = "typed"
    target_version_id: str | None = None
    question_id: str | None = None


class StatementOut(ORMModel):
    id: str
    session_id: str
    kind: str
    source: str
    language: str
    audio_file_id: str | None
    transcript_original: str
    transcript_english: str
    segments: list[Any]
    corrected_transcript_original: str | None
    corrections: list[Any]
    status: str
    provider: str
    target_version_id: str | None
    created_at: datetime


class StatementAccepted(BaseModel):
    statement_id: str
    job_id: str
    status: str


class StatementCorrection(BaseModel):
    corrected_transcript_original: str = Field(min_length=1, max_length=20000)
    note: str = Field(default="", max_length=1000)


class FeatureSheetOut(BaseModel):
    session_id: str
    sheet: dict[str, Any]
    version: int
    updated_at: datetime | None


class QuestionOut(ORMModel):
    id: str
    session_id: str
    field_key: str
    stage: str
    text_en: str
    text_local: str
    options: list[Any]
    leading_check: dict[str, Any]
    answer_type: str | None
    answer_text_original: str | None
    answer_text_en: str | None
    answer_option_id: str | None
    asked_at: datetime
    answered_at: datetime | None


class NextQuestionOut(BaseModel):
    done: bool
    reason: str | None = None
    question: QuestionOut | None = None


class AnswerCreate(BaseModel):
    answer_type: Literal["text", "voice", "option", "not_remembered", "skipped"]
    option_id: str | None = None
    text: str | None = Field(default=None, max_length=4000)
    language: Language | None = None


class AnswerOut(BaseModel):
    question_id: str
    field_key: str
    answered_at: datetime | None
