"""Permission-checked, audited file reads. The only way bytes leave the file store."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import audit
from app.core.errors import Forbidden, NotFound
from app.core.rbac import Action, can
from app.core.security import Principal
from app.db.models.files import File
from app.db.repositories import cases as case_repo
from app.db.repositories import sessions as session_repo

WITNESS_VISIBLE_KINDS = {"sketch_image", "preview", "overlay_render"}
MASTER_KINDS = {"master_image", "base_master_image"}
EXPORT_KINDS = {"export_png", "export_pdf", "scene_image"}


async def read_file(
    db: AsyncSession, container: Container, actor: Principal, file_id: str
) -> tuple[File, bytes]:
    rec = await container.files.get(db, file_id)
    if rec.kind == "cache":
        raise NotFound("File not found")
    if rec.session_id is None:
        if actor.kind != "user" or actor.role != "admin":
            raise Forbidden("No access to this file")
    else:
        sess = await session_repo.get_session(db, rec.session_id)
        if sess is None:
            raise NotFound("File not found")
        scope = await case_repo.scope_for_session(db, sess)
        if rec.kind in MASTER_KINDS:
            if not (actor.kind == "user" and can(actor, Action.VIEW_MASTER_IMAGE, scope)):
                raise Forbidden("The photoreal master image is only available to staff")
        elif rec.kind in EXPORT_KINDS:
            if not (
                actor.kind == "user"
                and (can(actor, Action.EXPORT, scope) or can(actor, Action.VIEW_CASE, scope))
            ):
                raise Forbidden("No access to this export")
        elif rec.kind in WITNESS_VISIBLE_KINDS or rec.kind == "mask":
            if not can(actor, Action.VIEW_CASE, scope):
                raise Forbidden("No access to this file")
        else:  # audio and anything else: staff with case access only
            if not (actor.kind == "user" and can(actor, Action.VIEW_CASE, scope)):
                raise Forbidden("No access to this file")
    data = await container.files.load_bytes(rec)
    audit.record(
        db,
        actor,
        "file.downloaded",
        object_type="file",
        object_id=rec.id,
        session_id=rec.session_id,
        details={"kind": rec.kind, "bytes": rec.size_bytes},
    )
    await audit.commit_with_audit(db)
    return rec, data
