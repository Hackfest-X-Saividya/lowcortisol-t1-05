from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.api.deps import ContainerDep, DbDep, PrincipalDep
from app.schemas.common import JobAccepted
from app.schemas.scene import (
    SceneBuildRequest,
    SceneCommandRequest,
    ScenePatchRequest,
    SceneTreeNode,
    SceneVersionOut,
)
from app.services.scene import versions as scene_service

router = APIRouter()


@router.post(
    "/sessions/{session_id}/scene", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def build_scene(
    session_id: str,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
    body: SceneBuildRequest | None = None,
) -> JobAccepted:
    job = await scene_service.request_build(
        db, container, principal, session_id, body.template if body else None
    )
    return JobAccepted(job_id=job.id, status=job.status, kind=job.kind)


@router.get("/sessions/{session_id}/scene-tree", response_model=list[SceneTreeNode])
async def scene_tree(session_id: str, principal: PrincipalDep, db: DbDep) -> list[SceneTreeNode]:
    return [
        SceneTreeNode.model_validate(n)
        for n in await scene_service.get_tree(db, principal, session_id)
    ]


@router.get("/scene-versions/{version_id}", response_model=SceneVersionOut)
async def get_scene_version(version_id: str, principal: PrincipalDep, db: DbDep) -> SceneVersionOut:
    return SceneVersionOut.model_validate(
        await scene_service.get_version(db, principal, version_id)
    )


@router.post(
    "/scene-versions/{version_id}/patches",
    response_model=SceneVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def patch_scene(
    version_id: str,
    body: ScenePatchRequest,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
) -> SceneVersionOut:
    data = await scene_service.apply_patch(
        db, container, principal, version_id, body.patch, body.source
    )
    return SceneVersionOut.model_validate(data)


@router.post(
    "/scene-versions/{version_id}/commands",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def scene_command(
    version_id: str,
    body: SceneCommandRequest,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
) -> JobAccepted:
    job = await scene_service.request_command(
        db, container, principal, version_id, body.utterance_original, body.language
    )
    return JobAccepted(job_id=job.id, status=job.status, kind=job.kind)


@router.get("/scene-templates")
async def scene_templates(
    container: ContainerDep, principal: PrincipalDep
) -> dict[str, dict[str, Any]]:
    return scene_service.templates_public(container)
