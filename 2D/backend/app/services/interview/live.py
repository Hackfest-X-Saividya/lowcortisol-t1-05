"""Live voice interview with a "sketch artist".

One witness turn = one request: the words (live browser transcript, typed text, or audio for
Whisper) go in; the feature sheet updates, drawing adjustments and the next open question
(in the witness's language and English) come out. A single LLM call does translation,
extraction, edit interpretation and question phrasing, so a turn costs one round trip.

The deterministic engine still decides WHICH field to ask next (situation -> overall -> face
-> marks), the leading-question rule check still guards every question, and every question
and answer is stored as before (questions table, statements table, audit log).
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import audit
from app.core.errors import ValidationFailed
from app.core.security import Principal
from app.db.base import utcnow
from app.db.models.statements import Question, Statement
from app.db.repositories import statements as repo
from app.services import cases as case_service
from app.services import speech
from app.services.interview import engine, prompts
from app.services.interview.fields import ASKED_FIELDS, FIELD_MAP, NOT_REMEMBERED, filled
from app.services.interview.leading_check import rule_check
from app.services.interview.local_templates import (
    ACK,
    GENDER_RETRY,
    OPENING,
    REVIEW,
    UPDATED,
    line,
    question_for,
)

ADJUST_KEY = "_adjust"
ADJUST_LIMIT = 0.45
EDITS_KEY = "_edits"  # free-form appearance edits (any detail, no fixed field needed)
MAX_EDITS = 12
# Live sketching: the face first, so the drawing starts at once; the viewing conditions
# (light, distance, time, angle) are still asked, at the end.
STAGE_ORDER = ("overall", "face", "marks", "situation")
# No portrait is drawn until the gender is known, so a gender answer that did not come through
# (e.g. garbled speech recognition) is asked again, up to this many times in all.
REASK = {"gender": 3}


def upcoming_fields(sheet: dict[str, Any], asked: set[str], n: int = 4) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for stage in STAGE_ORDER:
        for f in ASKED_FIELDS:
            if f.stage != stage or filled(sheet, f.key) or f.key in asked:
                continue
            out.append({"key": f.key, "about": f.description})
            if len(out) >= n:
                return out
    return out


def apply_adjustments(sheet: dict[str, Any], adjustments: list[dict[str, Any]]) -> dict[str, float]:
    current: dict[str, float] = dict(sheet.get(ADJUST_KEY) or {})
    for a in adjustments:
        param = str(a.get("param", ""))
        if param not in prompts.SKETCH_PARAMS:
            continue
        v = current.get(param, 0.0) + float(a.get("amount", 0.0))
        current[param] = round(max(-ADJUST_LIMIT, min(ADJUST_LIMIT, v)), 3)
    return current


def merge_edits(sheet: dict[str, Any], new: list[Any]) -> list[str]:
    """Append new free-form appearance edits, keeping order, dropping duplicates."""
    out: list[str] = [str(e) for e in (sheet.get(EDITS_KEY) or [])]
    seen = {e.lower() for e in out}
    for e in new:
        t = " ".join(str(e).split())[:200]
        if t and t.lower() not in seen:
            out.append(t)
            seen.add(t.lower())
    return out[-MAX_EDITS:]


def public_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in sheet.items() if not k.startswith("_")}


async def state(
    db: AsyncSession, container: Container, actor: Principal, session_id: str
) -> dict[str, Any]:
    """Where the live interview stands (for page loads / reconnects)."""
    sess, _ = await case_service.load_session(db, actor, session_id)
    fs = await repo.get_feature_sheet(db, sess.id)
    sheet = fs.sheet if fs else {}
    open_q = await repo.open_question(db, sess.id)
    lang = await _language(db, sess)
    started = await repo.has_free_recall(db, sess.id)
    if not started:
        q_local, q_en, field = line(OPENING, lang), line(OPENING, "en"), "free_recall"
    elif open_q is not None:
        q_local, q_en, field = open_q.text_local or open_q.text_en, open_q.text_en, open_q.field_key
    else:
        q_local, q_en, field = line(REVIEW, lang), line(REVIEW, "en"), "review"
    audit.record(
        db,
        actor,
        "interview.state_viewed",
        object_type="session",
        object_id=sess.id,
        session_id=sess.id,
        case_id=sess.case_id,
    )
    await audit.commit_with_audit(db)
    return {
        "started": started,
        "language": lang,
        "question_local": q_local,
        "question_en": q_en,
        "ask_field": field,
        "sheet": public_sheet(sheet),
        "adjust": sheet.get(ADJUST_KEY) or {},
    }


async def _language(db: AsyncSession, sess: Any) -> str:
    from app.db.models.cases import Witness

    w = await db.get(Witness, sess.witness_id)
    return w.preferred_language if w and w.preferred_language in ("kn", "hi", "en") else "en"


async def turn(
    db: AsyncSession,
    container: Container,
    actor: Principal,
    session_id: str,
    *,
    text: str | None,
    language: str | None,
    source: str,
    audio: bytes | None = None,
    dont_remember: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    sess, _ = await case_service.require_open_session(db, actor, session_id)
    lang = language if language in ("kn", "hi", "en") else await _language(db, sess)
    segments: list[Any] = []
    provider = source
    audio_file_id = None
    if audio is not None:
        t = await speech.transcribe(
            container.providers, audio, None, lang, container.settings.max_audio_mb
        )
        text, segments, provider = t.text, t.segments_json(), t.provider
        rec = await container.files.save(
            db,
            audio,
            kind="audio",
            mime=speech.require_audio(audio, container.settings.max_audio_mb),
            session_id=sess.id,
            created_by=actor.user_id,
        )
        audio_file_id = rec.id
    text = (text or "").strip()
    if not text and not dont_remember:
        raise ValidationFailed("Nothing was heard. Please say it again.", code="empty_turn")

    first = not await repo.has_free_recall(db, sess.id)
    fs = await repo.get_or_create_feature_sheet(db, sess.id)
    sheet: dict[str, Any] = dict(fs.sheet or {})
    questions = await repo.list_questions(db, sess.id)
    asked = {q.field_key for q in questions}
    open_q = await repo.open_question(db, sess.id)
    history = [
        {"q": q.text_en, "a": q.answer_text_en or q.answer_type or ""}
        for q in questions[-4:]
        if q.answered_at
    ]

    # ---- one LLM call ----------------------------------------------------------------------
    nxt = upcoming_fields(sheet, asked | ({open_q.field_key} if open_q else set()))
    llm_provider = "none"
    if dont_remember:
        data: dict[str, Any] = {
            "english": "",
            "fields": {},
            "adjustments": [],
            "reply_local": "",
            "reply_en": "",
            "ask_field": "",
        }
        if open_q:
            data["fields"][open_q.field_key] = {
                "value": NOT_REMEMBERED,
                "confidence": NOT_REMEMBERED,
                "source_text": "",
            }
    else:
        last = {"field": open_q.field_key, "question": open_q.text_en} if open_q else None
        res = await container.providers.llm_json(
            prompts.interview_turn(text, lang, last, sheet, nxt, history)
        )
        data = res.data
        llm_provider = res.provider

    # ---- statement --------------------------------------------------------------------------
    st = Statement(
        session_id=sess.id,
        kind="free_recall" if first else "answer_audio",
        source="audio" if audio is not None else source,
        language=lang,
        audio_file_id=audio_file_id,
        transcript_original=text,
        transcript_english=str(data.get("english") or ("" if dont_remember else text)),
        segments=segments,
        status="extracted",
        provider=provider,
    )
    await repo.add_statement(db, st)

    # ---- sheet + adjustments ----------------------------------------------------------------
    fields = {
        k: v
        for k, v in (data.get("fields") or {}).items()
        if k in FIELD_MAP and isinstance(v, dict)
    }
    answered_field = open_q.field_key if open_q else None
    direct = {k: v for k, v in fields.items() if k == answered_field}
    other = {k: v for k, v in fields.items() if k != answered_field}
    said = f"{text} | {st.transcript_english}"  # corrections must come from these words
    sheet = engine.merge_extracted(sheet, other, source=f"statement:{st.id}", said=said)
    if direct and open_q is not None:
        sheet = engine.merge_extracted(
            sheet, direct, source=f"question:{open_q.id}", said=said, answered=answered_field
        )
    if open_q is not None and answered_field == "gender" and not filled(sheet, "gender"):
        # the LLM missed a plain "man" / "woman" (or a tap on those buttons)
        spoken = engine.stated_gender(said)
        if spoken:
            fields["gender"] = {"value": spoken[0], "confidence": "high", "source_text": spoken[1]}
            sheet = engine.merge_extracted(
                sheet,
                {"gender": fields["gender"]},
                source=f"question:{open_q.id}",
                said=said,
                answered=answered_field,
            )
    adjustments = list(data.get("adjustments") or [])
    if adjustments:
        sheet[ADJUST_KEY] = apply_adjustments(sheet, adjustments)
    visual_edits = list(data.get("visual_edits") or [])
    if visual_edits:
        sheet[EDITS_KEY] = merge_edits(sheet, visual_edits)

    # ---- answer the open question -------------------------------------------------------------
    if open_q is not None:
        open_q.answer_type = (
            "not_remembered"
            if dont_remember
            else ("voice" if source in ("audio", "browser_asr") else "text")
        )
        open_q.answer_text_original = text or None
        open_q.answer_text_en = st.transcript_english or None
        open_q.answered_at = utcnow()

    # ---- next question (engine decides the field; LLM wording only if it is safe) ----------
    asked_now = [{"field_key": q.field_key, "stage": q.stage} for q in questions]
    step = engine.next_step(
        sheet,
        asked_now,
        len(questions),
        container.settings.interview_live_max_questions,
        order=STAGE_ORDER,
        reask=REASK,
    )
    ack = UPDATED if adjustments else ACK
    new_q = None
    if step.done or step.field is None:
        reply_local, reply_en, ask_field = line(REVIEW, lang), line(REVIEW, "en"), "review"
        if adjustments and not first:
            reply_local = f"{line(UPDATED, lang)} {reply_local}"
            reply_en = f"{line(UPDATED, 'en')} {reply_en}"
        check: dict[str, Any] = {}
    else:
        ask_field = step.field.key
        llm_local = str(data.get("reply_local") or "").strip()
        llm_en = str(data.get("reply_en") or "").strip()
        hit = rule_check(llm_en, ask_field) if llm_en else "empty"
        use_llm = data.get("ask_field") == ask_field and llm_local and not hit
        if ask_field == "gender" and ask_field in asked and step.stage != "check":
            # asked before and still unanswered (see REASK)
            use_llm = False
            reply_local = f"{line(ack, lang)} {line(GENDER_RETRY, lang)}"
            reply_en = f"{line(ack, 'en')} {line(GENDER_RETRY, 'en')}"
        elif use_llm:
            reply_local, reply_en = llm_local, llm_en
        else:
            reply_local = f"{line(ack, lang)} {question_for(ask_field, lang)}"
            reply_en = f"{line(ack, 'en')} {question_for(ask_field, 'en')}"
        check = {
            "approved": True,
            "used_template": not use_llm,
            "rule": hit,
            "provider": llm_provider,
            "prompt_version": prompts.PROMPT_VERSION,
            "live": True,
        }
        new_q = Question(
            session_id=sess.id,
            field_key=ask_field,
            stage=step.stage,
            text_en=reply_en,
            text_local=reply_local,
            options=[],
            leading_check=check,
        )
        await repo.add_question(db, new_q)

    fs.sheet = sheet
    audit.record(
        db,
        actor,
        "interview.turn",
        object_type="statement",
        object_id=st.id,
        session_id=sess.id,
        case_id=sess.case_id,
        details={
            "kind": st.kind,
            "source": st.source,
            "fields": sorted(fields),
            "adjustments": [a.get("param") for a in adjustments],
            "answered_field": answered_field,
            "next_field": ask_field,
            "provider": llm_provider,
        },
    )
    await audit.commit_with_audit(db)
    container.bus.publish(
        sess.id, "feature_sheet.updated", {"fields": sorted(fields), "statement_id": st.id}
    )
    if new_q is not None:
        container.bus.publish(
            sess.id,
            "question.next",
            {"question_id": new_q.id, "field_key": new_q.field_key, "stage": new_q.stage},
        )
    return {
        "statement_id": st.id,
        "transcript_original": text,
        "transcript_english": st.transcript_english,
        "updated_fields": sorted(fields),
        "adjustments": adjustments,
        "sheet": public_sheet(sheet),
        "adjust": sheet.get(ADJUST_KEY) or {},
        "reply_local": reply_local,
        "reply_en": reply_en,
        "ask_field": ask_field,
        "done": ask_field == "review",
        "provider": llm_provider,
        "ms": round((time.perf_counter() - t0) * 1000),
    }
