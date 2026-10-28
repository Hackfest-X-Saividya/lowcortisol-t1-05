from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, UploadFile, status

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


@router.post(
    "/sessions/{session_id}/scene/analyze-map",
    status_code=status.HTTP_200_OK,
)
async def analyze_scene_map(
    session_id: str,
    principal: PrincipalDep,
    db: DbDep,
    container: ContainerDep,
    image: "UploadFile",
) -> dict[str, Any]:
    """Upload a crime scene floor-plan image and get back a 3-D scene JSON.

    The image is sent to Gemini Vision which extracts room dimensions, furniture,
    doors/windows, people positions and evidence markers.  The result is coerced
    through the Scene schema so the frontend can render it immediately with CrimeScene3D.
    """
    from app.providers.gemini import GeminiVision
    from app.services.scene.schema import Scene, coerce_scene_input
    from app.core.errors import ProviderError

    raw = await image.read()
    mime = image.content_type or "image/jpeg"

    SCENE_PROMPT = """You are a crime-scene analyst.  Analyse the floor-plan / sketch image and
return a single JSON object (no prose, no markdown) in this exact schema:

{
  "room": {
    "width_m": <float>,
    "depth_m": <float>,
    "doors": [{"id":"d1","wall":"south","offset_m":1.0,"width_m":0.9}],
    "windows": [{"id":"w1","wall":"north","offset_m":0.5,"width_m":1.2}]
  },
  "objects": [
    {"id":"table1","type":"table","pos":[x,0,z],"size":[w,h,d],"rot_y_deg":0}
  ],
  "people": [
    {"id":"witness0","role":"witness","pos":[x,0,z],"facing_deg":0},
    {"id":"suspect0","role":"suspect","pos":[x,0,z],"facing_deg":180}
  ],
  "evidence": [
    {"id":"ev1","label":"knife","pos":[x,0,z]}
  ],
  "lighting": {"type":"indoor","level":"normal"}
}

Rules:
- Coordinate origin is the north-west room corner; x runs east, z runs south, y=0 is floor.
- All dimensions in metres (estimate from context if not labelled).
- Include every visible piece of furniture as an object.
- Use role "suspect" for the accused/perpetrator, "witness" for the victim/witness.
- If you cannot see people, omit the people array.
- Return ONLY the JSON — no explanation."""

    try:
        if not container.settings.gemini_configured:
            raise ProviderError("Gemini not configured", provider="gemini")
        vision = GeminiVision(container.settings)
        raw_scene = await vision.analyze(raw, mime, SCENE_PROMPT)
        scene = Scene.model_validate(coerce_scene_input(raw_scene))
        return scene.model_dump()
    except Exception as exc:  # noqa: BLE001
        from app.core.logging import get_logger
        get_logger(__name__).warning("scene map analysis failed: %s", exc)
        # Return a minimal default scene so the frontend still has something to show
        return {
            "room": {"width_m": 6.0, "depth_m": 5.0, "doors": [], "windows": []},
            "objects": [],
            "people": [],
            "evidence": [],
            "lighting": {"type": "indoor", "level": "normal"},
            "_error": str(exc),
        }

