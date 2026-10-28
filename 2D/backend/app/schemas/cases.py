from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

Language = Literal["hi", "kn", "en"]


class CaseCreate(BaseModel):
    case_number: str = Field(min_length=1, max_length=64)
    crime_type: str = Field(default="", max_length=80)
    occurred_at: datetime | None = None
    location_text: str = Field(default="", max_length=2000)
    station: str | None = Field(default=None, max_length=120)


class CaseUpdate(BaseModel):
    crime_type: str | None = Field(default=None, max_length=80)
    occurred_at: datetime | None = None
    location_text: str | None = Field(default=None, max_length=2000)
    status: Literal["open", "closed", "archived"] | None = None


class CaseOut(ORMModel):
    id: str
    case_number: str
    station: str
    crime_type: str
    occurred_at: datetime | None
    location_text: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class AssignmentCreate(BaseModel):
    user_id: str
    role_on_case: Literal["lead", "assisting", "artist"] = "assisting"


class AssignmentOut(ORMModel):
    case_id: str
    user_id: str
    role_on_case: str
    created_at: datetime


class WitnessCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    preferred_language: Language = "en"
    consent_given: bool = False
    consent_note: str = Field(default="", max_length=2000)


class WitnessOut(ORMModel):
    id: str
    case_id: str
    display_name: str
    preferred_language: str
    consent_given: bool
    consent_at: datetime | None
    consent_recorded_by: str | None
    consent_note: str
    created_at: datetime


class CaseDetail(CaseOut):
    assignments: list[AssignmentOut] = []
    witnesses: list[WitnessOut] = []
    session_ids: list[str] = []
