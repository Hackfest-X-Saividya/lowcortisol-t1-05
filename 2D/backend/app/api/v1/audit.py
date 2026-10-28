from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import DbDep, StaffDep
from app.db.base import iso_utc
from app.schemas.admin import AuditEntryOut, AuditPage, AuditVerifyOut
from app.services import audit_service

router = APIRouter()


@router.get("", response_model=AuditPage)
async def list_audit(
    principal: StaffDep,
    db: DbDep,
    case_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    cursor: int | None = Query(default=None, description="id of the last row seen"),
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditPage:
    rows, next_cursor = await audit_service.list_audit(
        db,
        principal,
        case_id=case_id,
        session_id=session_id,
        action=action,
        cursor=cursor,
        limit=limit,
    )
    items = [
        AuditEntryOut(
            id=r.id,
            at=iso_utc(r.at),
            actor_user_id=r.actor_user_id,
            actor_role=r.actor_role,
            session_id=r.session_id,
            case_id=r.case_id,
            action=r.action,
            object_type=r.object_type,
            object_id=r.object_id,
            ip=r.ip,
            request_id=r.request_id,
            details=r.details or {},
            prev_hash=r.prev_hash,
            hash=r.hash,
        )
        for r in rows
    ]
    return AuditPage(items=items, next_cursor=next_cursor)


@router.post("/verify", response_model=AuditVerifyOut)
async def verify(principal: StaffDep, db: DbDep) -> AuditVerifyOut:
    result = await audit_service.verify(db, principal)
    return AuditVerifyOut(**result.as_dict())
