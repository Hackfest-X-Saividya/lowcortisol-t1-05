from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.rbac import Action, Scope, can
from app.core.security import Principal

OFF = Principal(kind="user", user_id="o1", role="officer", station="S1", jurisdiction="J1")
ART = Principal(kind="user", user_id="a1", role="artist", station="S1", jurisdiction="J1")
SUP = Principal(kind="user", user_id="s1", role="supervisor", station="S9", jurisdiction="J1")
ADM = Principal(kind="user", user_id="ad", role="admin", jurisdiction="J1")
WIT = Principal(kind="witness", role="witness", session_id="sess1")

ASSIGNED = Scope(
    case_id="c",
    station="S1",
    jurisdiction="J1",
    assigned_user_ids={"o1", "a1"},
    created_by="o1",
    session_id="sess1",
)
UNASSIGNED = Scope(
    case_id="c2",
    station="S1",
    jurisdiction="J1",
    assigned_user_ids={"o2"},
    created_by="o2",
    session_id="sess2",
)
OTHER_STATION = Scope(
    case_id="c3",
    station="S2",
    jurisdiction="J2",
    assigned_user_ids=set(),
    created_by="o9",
    session_id="sess3",
)

# Matrix cells: (action, principal, scope, expected)
MATRIX = [
    # create case / add witness / start session
    (Action.CREATE_CASE, WIT, ASSIGNED, False),
    (Action.CREATE_CASE, OFF, Scope(station="S1"), True),
    (Action.CREATE_CASE, OFF, Scope(station="S2"), False),
    (Action.CREATE_CASE, ART, Scope(station="S1"), False),
    (Action.CREATE_CASE, SUP, Scope(station="S1"), False),
    (Action.CREATE_CASE, ADM, Scope(station="S1"), False),
    (Action.ADD_WITNESS, OFF, Scope(station="S1"), True),
    (Action.START_SESSION, OFF, Scope(station="S1"), True),
    (Action.START_SESSION, ART, Scope(station="S1"), False),
    # view case
    (Action.VIEW_CASE, WIT, ASSIGNED, True),
    (Action.VIEW_CASE, WIT, UNASSIGNED, False),
    (Action.VIEW_CASE, OFF, ASSIGNED, True),
    (Action.VIEW_CASE, OFF, UNASSIGNED, False),
    (Action.VIEW_CASE, ART, ASSIGNED, True),
    (Action.VIEW_CASE, ART, UNASSIGNED, False),
    (Action.VIEW_CASE, SUP, ASSIGNED, True),
    (Action.VIEW_CASE, SUP, OTHER_STATION, False),
    (Action.VIEW_CASE, ADM, ASSIGNED, False),
    # edit sketch or scene
    (Action.EDIT_SKETCH_OR_SCENE, WIT, ASSIGNED, True),
    (Action.EDIT_SKETCH_OR_SCENE, WIT, UNASSIGNED, False),
    (Action.EDIT_SKETCH_OR_SCENE, OFF, ASSIGNED, True),
    (Action.EDIT_SKETCH_OR_SCENE, OFF, UNASSIGNED, False),
    (Action.EDIT_SKETCH_OR_SCENE, ART, ASSIGNED, True),
    (Action.EDIT_SKETCH_OR_SCENE, SUP, ASSIGNED, False),
    (Action.EDIT_SKETCH_OR_SCENE, ADM, ASSIGNED, False),
    # view master image
    (Action.VIEW_MASTER_IMAGE, WIT, ASSIGNED, False),
    (Action.VIEW_MASTER_IMAGE, OFF, ASSIGNED, True),
    (Action.VIEW_MASTER_IMAGE, ART, ASSIGNED, True),
    (Action.VIEW_MASTER_IMAGE, SUP, ASSIGNED, True),
    (Action.VIEW_MASTER_IMAGE, ADM, ASSIGNED, False),
    # export
    (Action.EXPORT, WIT, ASSIGNED, False),
    (Action.EXPORT, OFF, ASSIGNED, True),
    (Action.EXPORT, OFF, UNASSIGNED, False),
    (Action.EXPORT, ART, ASSIGNED, False),
    (Action.EXPORT, SUP, ASSIGNED, True),
    (Action.EXPORT, ADM, ASSIGNED, False),
    # view audit
    (Action.VIEW_AUDIT, WIT, ASSIGNED, False),
    (Action.VIEW_AUDIT, OFF, ASSIGNED, True),
    (Action.VIEW_AUDIT, OFF, UNASSIGNED, False),
    (Action.VIEW_AUDIT, ART, ASSIGNED, False),
    (Action.VIEW_AUDIT, SUP, ASSIGNED, True),
    (Action.VIEW_AUDIT, SUP, OTHER_STATION, False),
    (Action.VIEW_AUDIT, ADM, ASSIGNED, False),
    # verify audit chain
    (Action.VERIFY_AUDIT, WIT, ASSIGNED, False),
    (Action.VERIFY_AUDIT, OFF, ASSIGNED, False),
    (Action.VERIFY_AUDIT, ART, ASSIGNED, False),
    (Action.VERIFY_AUDIT, SUP, ASSIGNED, True),
    (Action.VERIFY_AUDIT, ADM, ASSIGNED, True),
    # manage users
    (Action.MANAGE_USERS, WIT, ASSIGNED, False),
    (Action.MANAGE_USERS, OFF, ASSIGNED, False),
    (Action.MANAGE_USERS, ART, ASSIGNED, False),
    (Action.MANAGE_USERS, SUP, ASSIGNED, False),
    (Action.MANAGE_USERS, ADM, ASSIGNED, True),
]


@pytest.mark.parametrize(("action", "principal", "scope", "expected"), MATRIX)
def test_matrix_cell(action: Action, principal: Principal, scope: Scope, expected: bool) -> None:
    assert can(principal, action, scope) is expected


def test_system_principal_can_everything() -> None:
    assert can(Principal.system(), Action.MANAGE_USERS)


@pytest.mark.asyncio
async def test_witness_token_scope_and_expiry(container, users) -> None:  # type: ignore[no-untyped-def]
    from app.api.deps import resolve_principal
    from app.core.errors import Unauthorized
    from app.core.security import token_hash
    from app.db.models.cases import Case, Witness
    from app.db.models.sessions import InterviewSession

    async with container.db.session() as db:
        off = users["officer"]
        case = Case(case_number="X1", station="Jayanagar PS", created_by=off.id)
        db.add(case)
        await db.flush()
        w = Witness(case_id=case.id, display_name="w", consent_given=True)
        db.add(w)
        await db.flush()
        sess = InterviewSession(
            case_id=case.id,
            witness_id=w.id,
            officer_id=off.id,
            witness_token_hash=token_hash("tok-good"),
            witness_token_expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        expired = InterviewSession(
            case_id=case.id,
            witness_id=w.id,
            officer_id=off.id,
            witness_token_hash=token_hash("tok-expired"),
            witness_token_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        db.add_all([sess, expired])
        await db.commit()
        p = await resolve_principal(container, db, "tok-good", "", "", "")
        assert p.kind == "witness" and p.session_id == sess.id and p.role == "witness"
        with pytest.raises(Unauthorized):
            await resolve_principal(container, db, "tok-expired", "", "", "")
        with pytest.raises(Unauthorized):
            await resolve_principal(container, db, "tok-unknown", "", "", "")
        # witness is bound to its own session only
        assert can(p, Action.VIEW_CASE, Scope(session_id=sess.id))
        assert not can(p, Action.VIEW_CASE, Scope(session_id=expired.id))
        assert not can(p, Action.VIEW_MASTER_IMAGE, Scope(session_id=sess.id))
        assert not can(p, Action.VIEW_AUDIT, Scope(session_id=sess.id))
        assert not can(p, Action.EXPORT, Scope(session_id=sess.id))
