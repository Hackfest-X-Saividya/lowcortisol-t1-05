from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile, status

from app.api.deps import ContainerDep, DbDep, PrincipalDep
from app.core.errors import ValidationFailed
from app.schemas.statements import (
    FeatureSheetOut,
    StatementAccepted,
    StatementCorrection,
    StatementOut,
    StatementTextCreate,
)
from app.services import statements as statement_service

router = APIRouter()


@router.post(
    "/sessions/{session_id}/statements",
    response_model=StatementAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_statement(
    session_id: str,
    request: Request,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
    audio: UploadFile | None = File(default=None),
    language: str | None = Form(default=None),
    kind: str | None = Form(default=None),
    target_version_id: str | None = Form(default=None),
    question_id: str | None = Form(default=None),
) -> StatementAccepted:
    """Multipart (``audio`` + form fields) or JSON (``StatementTextCreate``)."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        if audio is None:
            raise ValidationFailed("audio file required in multipart upload")
        data = await audio.read()
        st, job = await statement_service.create_statement(
            db,
            container,
            principal,
            session_id,
            kind=kind or "free_recall",
            source="audio",
            lang=language or "en",
            audio=data,
            target_version_id=target_version_id,
            question_id=question_id,
        )
    else:
        body = StatementTextCreate.model_validate(await request.json())
        st, job = await statement_service.create_statement(
            db,
            container,
            principal,
            session_id,
            kind=body.kind,
            source=body.source,
            lang=body.language,
            text=body.text,
            target_version_id=body.target_version_id,
            question_id=body.question_id,
        )
    return StatementAccepted(statement_id=st.id, job_id=job.id, status=job.status)


@router.get("/sessions/{session_id}/statements/{statement_id}", response_model=StatementOut)
async def get_statement(
    session_id: str, statement_id: str, principal: PrincipalDep, db: DbDep
) -> StatementOut:
    st = await statement_service.get_statement(db, principal, session_id, statement_id)
    return StatementOut.model_validate(st)


@router.patch(
    "/sessions/{session_id}/statements/{statement_id}",
    response_model=StatementAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def correct_statement(
    session_id: str,
    statement_id: str,
    body: StatementCorrection,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
) -> StatementAccepted:
    st, job = await statement_service.correct_statement(
        db,
        container,
        principal,
        session_id,
        statement_id,
        body.corrected_transcript_original,
        body.note,
    )
    return StatementAccepted(statement_id=st.id, job_id=job.id, status=job.status)


@router.get("/sessions/{session_id}/feature-sheet", response_model=FeatureSheetOut)
async def feature_sheet(session_id: str, principal: PrincipalDep, db: DbDep) -> FeatureSheetOut:
    data = await statement_service.get_feature_sheet(db, principal, session_id)
    return FeatureSheetOut.model_validate(data)
