from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbDep, PrincipalDep
from app.core.errors import NotFound
from app.db.models.jobs import Job
from app.schemas.sessions import JobOut
from app.services import cases as case_service

router = APIRouter()


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, principal: PrincipalDep, db: DbDep) -> JobOut:
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFound("Job not found")
    if job.session_id:
        await case_service.load_session(db, principal, job.session_id)
    elif principal.kind != "user":
        raise NotFound("Job not found")
    return JobOut.model_validate(job)
