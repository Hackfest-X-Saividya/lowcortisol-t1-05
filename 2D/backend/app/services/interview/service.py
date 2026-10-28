"""Interview service: next question, answers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import audit
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import Principal
from app.db.base import utcnow
from app.db.models.cases import Witness
from app.db.models.sessions import InterviewSession
from app.db.models.statements import Question, Statement
from app.db.repositories import statements as repo
from app.services import cases as case_service
from app.services import language
from app.services.interview import engine, prompts
from app.services.interview.fields import FIELD_MAP, NOT_REMEMBERED
from app.services.interview.leading_check import rule_check, safe_template


async def _phrase_question(
    container: Container, step: engine.NextStep, sheet: dict[str, Any], previous: list[str]
) -> tuple[str, dict[str, Any]]:
    """Phrase with the LLM, run rule + LLM leading checks, regenerate twice, else template."""
    assert step.field is not None
    f = step.field
    known = {k: v.get("value") for k, v in sheet.items() if isinstance(v, dict)}
    reason = "contradiction" if step.stage == "check" else "missing"
    attempts: list[dict[str, Any]] = []
    for _attempt in range(3):
        res = await container.providers.llm_json(
            prompts.phrase_question(f.key, f.description, known, step.options, previous, reason)
        )
        q = str(res.data.get("question_en", "")).strip()
        rule_hit = rule_check(q, f.key) if q else "empty"
        llm_hit: dict[str, Any] = {}
        if not rule_hit:
            chk = await container.providers.llm_json(prompts.leading_check(q, f.key))
            llm_hit = {
                "leading": bool(chk.data.get("leading")),
                "reason": chk.data.get("reason", ""),
                "provider": chk.provider,
            }
        attempts.append({"question": q, "rule": rule_hit, "llm": llm_hit, "provider": res.provider})
        if q and not rule_hit and not llm_hit.get("leading"):
            return q, {
                "approved": True,
                "attempts": attempts,
                "used_template": False,
                "prompt_version": prompts.PROMPT_VERSION,
            }
    q = safe_template(f.label)
    return q, {
        "approved": True,
        "attempts": attempts,
        "used_template": True,
        "prompt_version": prompts.PROMPT_VERSION,
    }


async def next_question(
    db: AsyncSession, container: Container, actor: Principal, session_id: str
) -> dict[str, Any]:
    sess, _ = await case_service.require_open_session(db, actor, session_id)
    if not await repo.has_free_recall(db, sess.id):
        raise Conflict(
            "Record the free-recall statement before the interview starts",
            code="free_recall_required",
        )
    open_q = await repo.open_question(db, sess.id)
    if open_q is not None:
        audit.record(
            db,
            actor,
            "question.viewed",
            object_type="question",
            object_id=open_q.id,
            session_id=sess.id,
            case_id=sess.case_id,
        )
        await audit.commit_with_audit(db)
        return {"done": False, "question": open_q}
    fs = await repo.get_or_create_feature_sheet(db, sess.id)
    questions = await repo.list_questions(db, sess.id)
    asked = [{"field_key": q.field_key, "stage": q.stage} for q in questions]
    step = engine.next_step(
        fs.sheet, asked, len(questions), container.settings.interview_max_questions
    )
    if step.done:
        audit.record(
            db,
            actor,
            "interview.done",
            object_type="session",
            object_id=sess.id,
            session_id=sess.id,
            case_id=sess.case_id,
            details={"reason": step.reason},
        )
        await audit.commit_with_audit(db)
        return {"done": True, "reason": step.reason, "question": None}
    assert step.field is not None
    text_en, check = await _phrase_question(
        container, step, fs.sheet, [q.text_en for q in questions[-5:]]
    )
    witness = await db.get(Witness, sess.witness_id)
    lang = witness.preferred_language if witness else "en"
    text_local, tprov = await language.from_english(container.providers, text_en, lang)
    q = Question(
        session_id=sess.id,
        field_key=step.field.key,
        stage=step.stage,
        text_en=text_en,
        text_local=text_local,
        options=step.options,
        leading_check={**check, "translation_provider": tprov, "context": step.context},
    )
    await repo.add_question(db, q)
    audit.record(
        db,
        actor,
        "question.asked",
        object_type="question",
        object_id=q.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={
            "field_key": q.field_key,
            "stage": q.stage,
            "used_template": check["used_template"],
        },
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id, "question.next", {"question_id": q.id, "field_key": q.field_key, "stage": q.stage}
    )
    return {"done": False, "question": q}


async def answer_question(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    session_id: str,
    question_id: str,
    *,
    answer_type: str,
    option_id: str | None,
    text: str | None,
    lang: str | None,
) -> dict[str, Any]:
    sess, _ = await case_service.require_open_session(db, actor, session_id)
    q = await repo.get_question(db, question_id)
    if q is None or q.session_id != sess.id:
        raise NotFound("Question not found")
    if q.answered_at is not None:
        raise Conflict("Question already answered", code="already_answered")
    if answer_type not in ("text", "voice", "option", "not_remembered", "skipped"):
        raise ValidationFailed("invalid answer_type")
    if answer_type == "option" and not option_id:
        raise ValidationFailed("option_id required for option answers")
    text_en = None
    tprov = "none"
    if answer_type in ("text", "voice"):
        if not text or not text.strip():
            raise ValidationFailed("text required for text answers")
        witness_lang = lang or "en"
        text_en, tprov = await language.to_english(container.providers, text.strip(), witness_lang)
    await _record(
        db,
        container,
        actor,
        sess,
        q,
        answer_type=answer_type,
        option_id=option_id,
        text_original=text,
        text_en=text_en,
        translation_provider=tprov,
    )
    return {"question_id": q.id, "field_key": q.field_key, "answered_at": q.answered_at}


async def _record(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    sess: InterviewSession,
    q: Question,
    *,
    answer_type: str,
    option_id: str | None,
    text_original: str | None,
    text_en: str | None,
    translation_provider: str,
) -> None:
    if option_id == NOT_REMEMBERED:
        answer_type = "not_remembered"
    q.answer_type = answer_type
    q.answer_option_id = option_id
    q.answer_text_original = text_original
    q.answer_text_en = text_en
    q.answered_at = utcnow()
    fs = await repo.get_or_create_feature_sheet(db, sess.id)
    fs.sheet = engine.apply_answer(
        fs.sheet,
        q.field_key,
        answer_type=answer_type,
        option_id=option_id,
        text_en=text_en,
        source=f"question:{q.id}",
    )
    audit.record(
        db,
        actor,
        "question.answered",
        object_type="question",
        object_id=q.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={
            "field_key": q.field_key,
            "answer_type": answer_type,
            "option_id": option_id,
            "translation_provider": translation_provider,
        },
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id, "feature_sheet.updated", {"fields": [q.field_key], "question_id": q.id}
    )


async def record_answer_from_statement(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    sess: InterviewSession,
    question_id: str,
    st: Statement,
) -> None:
    q = await repo.get_question(db, question_id)
    if q is None or q.session_id != sess.id or q.answered_at is not None:
        return
    await _record(
        db,
        container,
        actor,
        sess,
        q,
        answer_type="voice",
        option_id=None,
        text_original=st.transcript_original,
        text_en=st.transcript_english,
        translation_provider=st.provider,
    )


def field_label(key: str) -> str:
    f = FIELD_MAP.get(key)
    return f.label if f else key
