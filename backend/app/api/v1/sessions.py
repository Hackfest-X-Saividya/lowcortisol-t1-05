from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import DbDep, PrincipalDep, StaffDep
from app.schemas.sessions import DisplayEventCreate, DisplayEventOut, SessionDetail, SessionOut
from app.services import cases as case_service

router = APIRouter()


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, principal: PrincipalDep, db: DbDep) -> SessionDetail:
    data = await case_service.get_session_detail(db, principal, session_id)
    return SessionDetail.model_validate(data)


@router.post("/{session_id}/pause", response_model=SessionOut)
async def pause(session_id: str, principal: StaffDep, db: DbDep) -> SessionOut:
    return SessionOut.model_validate(
        await case_service.set_session_status(db, principal, session_id, "pause")
    )


@router.post("/{session_id}/resume", response_model=SessionOut)
async def resume(session_id: str, principal: StaffDep, db: DbDep) -> SessionOut:
    return SessionOut.model_validate(
        await case_service.set_session_status(db, principal, session_id, "resume")
    )


@router.post("/{session_id}/close", response_model=SessionOut)
async def close(session_id: str, principal: StaffDep, db: DbDep) -> SessionOut:
    return SessionOut.model_validate(
        await case_service.set_session_status(db, principal, session_id, "close")
    )


@router.post(
    "/{session_id}/display-events",
    response_model=DisplayEventOut,
    status_code=status.HTTP_201_CREATED,
)
async def display_event(
    session_id: str, body: DisplayEventCreate, principal: PrincipalDep, db: DbDep
) -> DisplayEventOut:
    ev = await case_service.record_display_event(db, principal, session_id, body)
    return DisplayEventOut.model_validate(ev)
