from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import ContainerDep, DbDep, StaffDep
from app.schemas.common import JobAccepted
from app.schemas.sessions import ExportCreate, ExportOut
from app.services import exports as export_service

router = APIRouter()


@router.post(
    "/sessions/{session_id}/exports",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_export(
    session_id: str, body: ExportCreate, principal: StaffDep, db: DbDep, container: ContainerDep
) -> JobAccepted:
    job = await export_service.request_export(
        db,
        container,
        principal,
        session_id,
        body.kind,
        body.sketch_version_id,
        body.scene_version_id,
    )
    return JobAccepted(job_id=job.id, status=job.status, kind=job.kind)


@router.get("/exports/{export_id}", response_model=ExportOut)
async def get_export(export_id: str, principal: StaffDep, db: DbDep) -> ExportOut:
    return ExportOut.model_validate(await export_service.get_export(db, principal, export_id))
