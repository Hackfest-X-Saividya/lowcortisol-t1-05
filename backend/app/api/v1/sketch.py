from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.api.deps import ContainerDep, DbDep, PrincipalDep
from app.schemas.common import JobAccepted
from app.schemas.sketch import (
    EditRequest,
    LockOut,
    LocksPut,
    OverlayInfo,
    RatingRequest,
    SketchRequest,
    TreeNode,
    VersionOut,
)
from app.services.sketch import overlays as overlay_service
from app.services.sketch import versions as sketch_service
from app.services.sketch.regions import HANDLES, SLIDERS

router = APIRouter()


@router.post(
    "/sessions/{session_id}/sketch",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_sketch(
    session_id: str,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
    body: SketchRequest | None = None,
) -> JobAccepted:
    sketch_service.check_edit_permission(principal)
    job = await sketch_service.request_sketch(
        db, container, principal, session_id, body.seed if body else None
    )
    return JobAccepted(job_id=job.id, status=job.status, kind=job.kind)


@router.get("/sessions/{session_id}/sketch-tree", response_model=list[TreeNode])
async def sketch_tree(session_id: str, principal: PrincipalDep, db: DbDep) -> list[TreeNode]:
    return [
        TreeNode.model_validate(n) for n in await sketch_service.get_tree(db, principal, session_id)
    ]


@router.get("/sketch-versions/{version_id}", response_model=VersionOut)
async def get_version(version_id: str, principal: PrincipalDep, db: DbDep) -> VersionOut:
    return VersionOut.model_validate(await sketch_service.get_version(db, principal, version_id))


@router.post(
    "/sketch-versions/{version_id}/edits",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def edit_version(
    version_id: str, body: EditRequest, principal: PrincipalDep, db: DbDep, container: ContainerDep
) -> JobAccepted:
    sketch_service.check_edit_permission(principal)
    job = await sketch_service.request_edit(
        db, container, principal, version_id, body.model_dump(exclude_none=True)
    )
    return JobAccepted(job_id=job.id, status=job.status, kind=job.kind)


@router.post(
    "/sketch-versions/{version_id}/previews",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def previews(
    version_id: str, body: EditRequest, principal: PrincipalDep, db: DbDep, container: ContainerDep
) -> JobAccepted:
    sketch_service.check_edit_permission(principal)
    job = await sketch_service.request_previews(
        db, container, principal, version_id, body.model_dump(exclude_none=True)
    )
    return JobAccepted(job_id=job.id, status=job.status, kind=job.kind)


@router.post("/sketch-versions/{version_id}/rating")
async def rate(
    version_id: str, body: RatingRequest, principal: PrincipalDep, db: DbDep
) -> dict[str, Any]:
    v = await sketch_service.rate_version(db, principal, version_id, body.rating)
    return {"version_id": v.id, "witness_rating": v.witness_rating}


@router.get("/sessions/{session_id}/locks", response_model=list[LockOut])
async def get_locks(session_id: str, principal: PrincipalDep, db: DbDep) -> list[LockOut]:
    return [
        LockOut.model_validate(x) for x in await sketch_service.get_locks(db, principal, session_id)
    ]


@router.put("/sessions/{session_id}/locks", response_model=list[LockOut])
async def put_locks(
    session_id: str, body: LocksPut, principal: PrincipalDep, db: DbDep
) -> list[LockOut]:
    items = [lock.model_dump() for lock in body.locks]
    return [
        LockOut.model_validate(x)
        for x in await sketch_service.put_locks(db, principal, session_id, items)
    ]


@router.get("/sketch-versions/{a}/compare/{b}")
async def compare(
    a: str, b: str, principal: PrincipalDep, db: DbDep, container: ContainerDep
) -> dict[str, Any]:
    return await sketch_service.compare(db, container, principal, a, b)


@router.get("/overlays", response_model=list[OverlayInfo])
async def overlays(container: ContainerDep, principal: PrincipalDep) -> list[OverlayInfo]:
    return [OverlayInfo.model_validate(o) for o in sketch_service.overlay_catalog(container)]


@router.get("/overlays/{overlay_id}/thumbnail")
async def overlay_thumbnail(
    overlay_id: str, container: ContainerDep, principal: PrincipalDep
) -> Response:
    png = overlay_service.overlay_png_bytes(container.settings, overlay_id)
    return Response(content=png, media_type="image/png")


@router.get("/sketch-controls")
async def sketch_controls(principal: PrincipalDep) -> dict[str, Any]:
    """Handle and slider definitions so the frontend can draw the editing UI."""
    return {
        "handles": [
            {"name": h.name, "anchor": h.anchor, "region": h.region, "mirror": h.mirror}
            for h in HANDLES.values()
        ],
        "sliders": [
            {
                "name": n,
                "region": r,
                "moves": [{"handle": h, "dx": dx, "dy": dy} for h, dx, dy in moves],
            }
            for n, (r, moves) in SLIDERS.items()
        ],
        "amounts": {"a little": 0.05, "more": 0.10, "a lot": 0.15},
    }
