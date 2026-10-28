from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep, DbDep, PrincipalDep
from app.schemas.statements import AnswerCreate, AnswerOut, NextQuestionOut, QuestionOut
from app.services.interview import service as interview_service
from app.services.interview.fields import CARD_CATALOG

router = APIRouter()


@router.get("/sessions/{session_id}/questions/next", response_model=NextQuestionOut)
async def next_question(
    session_id: str, principal: PrincipalDep, db: DbDep, container: ContainerDep
) -> NextQuestionOut:
    data = await interview_service.next_question(db, container, principal, session_id)
    q = data.get("question")
    return NextQuestionOut(
        done=data["done"],
        reason=data.get("reason"),
        question=QuestionOut.model_validate(q) if q is not None else None,
    )


@router.post("/sessions/{session_id}/questions/{question_id}/answer", response_model=AnswerOut)
async def answer(
    session_id: str,
    question_id: str,
    body: AnswerCreate,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
) -> AnswerOut:
    data = await interview_service.answer_question(
        db,
        container,
        principal,
        session_id,
        question_id,
        answer_type=body.answer_type,
        option_id=body.option_id,
        text=body.text,
        lang=body.language,
    )
    return AnswerOut(**data)


@router.get("/feature-cards")
async def feature_cards() -> dict[str, list[dict[str, str]]]:
    """Catalogue of option cards (ids, labels, field) for the frontend to draw."""
    return {"cards": list(CARD_CATALOG.values())}
