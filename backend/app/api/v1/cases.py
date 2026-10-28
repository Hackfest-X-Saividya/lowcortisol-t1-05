from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import ContainerDep, DbDep, PrincipalDep, StaffDep
from app.schemas.cases import (
    AssignmentCreate,
    AssignmentOut,
    CaseCreate,
    CaseDetail,
    CaseOut,
    CaseUpdate,
    WitnessCreate,
    WitnessOut,
)
from app.schemas.common import Page
from app.schemas.sessions import SessionCreate, SessionCreated, SessionOut
from app.services import cases as case_service

router = APIRouter()


@router.get("", response_model=Page[CaseOut])
async def list_cases(
    principal: StaffDep,
    db: DbDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> Page[CaseOut]:
    rows, next_cursor = await case_service.list_cases(db, principal, cursor, limit)
    return Page(items=[CaseOut.model_validate(r) for r in rows], next_cursor=next_cursor)


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def create_case(body: CaseCreate, principal: StaffDep, db: DbDep) -> CaseOut:
    case = await case_service.create_case(db, principal, body)
    return CaseOut.model_validate(case)


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: str, principal: PrincipalDep, db: DbDep) -> CaseDetail:
    data = await case_service.get_case(db, principal, case_id)
    return CaseDetail.model_validate(data)


@router.patch("/{case_id}", response_model=CaseOut)
async def update_case(case_id: str, body: CaseUpdate, principal: StaffDep, db: DbDep) -> CaseOut:
    case = await case_service.update_case(db, principal, case_id, body)
    return CaseOut.model_validate(case)


@router.post(
    "/{case_id}/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED
)
async def assign(
    case_id: str, body: AssignmentCreate, principal: StaffDep, db: DbDep
) -> AssignmentOut:
    a = await case_service.assign(db, principal, case_id, body)
    return AssignmentOut.model_validate(a)


@router.post("/{case_id}/witnesses", response_model=WitnessOut, status_code=status.HTTP_201_CREATED)
async def add_witness(
    case_id: str, body: WitnessCreate, principal: StaffDep, db: DbDep
) -> WitnessOut:
    w = await case_service.add_witness(db, principal, case_id, body)
    return WitnessOut.model_validate(w)


@router.post(
    "/{case_id}/sessions", response_model=SessionCreated, status_code=status.HTTP_201_CREATED
)
async def create_session(
    case_id: str, body: SessionCreate, principal: StaffDep, db: DbDep, container: ContainerDep
) -> SessionCreated:
    sess, token = await case_service.create_session(
        db, container.settings, principal, case_id, body.witness_id
    )
    return SessionCreated(session=SessionOut.model_validate(sess), witness_token=token)
