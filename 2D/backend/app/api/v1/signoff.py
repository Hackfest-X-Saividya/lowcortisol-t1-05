from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import ContainerDep, DbDep, PrincipalDep
from app.schemas.sessions import SignoffCreate, SignoffOut
from app.services import signoff as signoff_service

router = APIRouter()


@router.post(
    "/sessions/{session_id}/signoff", response_model=SignoffOut, status_code=status.HTTP_201_CREATED
)
async def sign_off(
    session_id: str,
    body: SignoffCreate,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
) -> SignoffOut:
    s = await signoff_service.sign_off(db, container, principal, session_id, body)
    return SignoffOut.model_validate(s)
