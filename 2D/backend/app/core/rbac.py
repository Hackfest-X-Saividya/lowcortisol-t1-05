"""Role based access control matrix.

Action                     Witness       Officer        Artist     Supervisor    Admin
create case / witness /
  start session            no            own station    no         no            no
view case                  own session   assigned       assigned   jurisdiction  no
edit sketch or scene       own session   assigned       assigned   no            no
view master (photoreal)    no            yes(assigned)  assigned   jurisdiction  no
export                     no            assigned       no         jurisdiction  no
view audit log             no            own cases      no         jurisdiction  no
verify audit chain         no            no             no         yes           yes
manage users               no            no             no         no            yes

``Scope`` carries what the check needs about the target case/session. Each matrix cell
is covered by ``tests/unit/test_rbac.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.core.errors import Forbidden
from app.core.security import Principal


class Action(StrEnum):
    CREATE_CASE = "create_case"
    ADD_WITNESS = "add_witness"
    START_SESSION = "start_session"
    VIEW_CASE = "view_case"
    EDIT_SKETCH_OR_SCENE = "edit_sketch_or_scene"
    VIEW_MASTER_IMAGE = "view_master_image"
    EXPORT = "export"
    VIEW_AUDIT = "view_audit"
    VERIFY_AUDIT = "verify_audit"
    MANAGE_USERS = "manage_users"


@dataclass
class Scope:
    """Facts about the target object used to evaluate the matrix."""

    case_id: str | None = None
    station: str = ""
    jurisdiction: str = ""
    assigned_user_ids: set[str] = field(default_factory=set)
    created_by: str | None = None
    session_id: str | None = None

    def is_assigned(self, user_id: str | None) -> bool:
        return bool(user_id) and (user_id in self.assigned_user_ids or user_id == self.created_by)


# Actions the witness token is allowed to perform at all (section 11 of the spec).
WITNESS_ALLOWED = {Action.VIEW_CASE, Action.EDIT_SKETCH_OR_SCENE}


def _same_jurisdiction(p: Principal, s: Scope) -> bool:
    return bool(p.jurisdiction) and p.jurisdiction == s.jurisdiction


def can(p: Principal, action: Action, scope: Scope | None = None) -> bool:
    scope = scope or Scope()
    if p.kind == "system":
        return True
    role = p.role

    if p.kind == "witness" or role == "witness":
        if action not in WITNESS_ALLOWED:
            return False
        return bool(p.session_id) and p.session_id == scope.session_id

    if role == "officer":
        if action in (Action.CREATE_CASE, Action.ADD_WITNESS, Action.START_SESSION):
            return not scope.station or scope.station == p.station
        if action in (
            Action.VIEW_CASE,
            Action.EDIT_SKETCH_OR_SCENE,
            Action.VIEW_MASTER_IMAGE,
            Action.EXPORT,
            Action.VIEW_AUDIT,
        ):
            return scope.is_assigned(p.user_id)
        return False

    if role == "artist":
        if action in (Action.VIEW_CASE, Action.EDIT_SKETCH_OR_SCENE, Action.VIEW_MASTER_IMAGE):
            return scope.is_assigned(p.user_id)
        return False

    if role == "supervisor":
        if action in (Action.VIEW_CASE, Action.VIEW_MASTER_IMAGE, Action.EXPORT, Action.VIEW_AUDIT):
            return _same_jurisdiction(p, scope)
        if action == Action.VERIFY_AUDIT:
            return True
        return False

    if role == "admin":
        return action in (Action.MANAGE_USERS, Action.VERIFY_AUDIT)

    return False


def require(p: Principal, action: Action, scope: Scope | None = None) -> None:
    if not can(p, action, scope):
        raise Forbidden(f"Not allowed: {action.value}")
