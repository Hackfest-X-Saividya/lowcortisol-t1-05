from __future__ import annotations

from typing import Any

from fastapi import APIRouter, UploadFile, status

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
    image: UploadFile,
) -> dict[str, Any]:
    """Upload a floor-plan image (or a photo of a room) and get back a 3-D scene JSON.

    The sample floor plan (2D/data/image.png) is the reference for every upload: uploading it
    returns its traced plan directly, Gemini Vision is shown it as a worked example (walls, doors
    and windows) before reading any other image, and when the image cannot be read the sample
    plan is returned so the 3D view still has walls, doors and windows to show. The response's
    "_source" is "sample" or "image"; "_error" says why the image could not be read.
    """
    from app.core.errors import ProviderError
    from app.core.logging import get_logger
    from app.providers.gemini import GeminiVision
    from app.services.scene import sample_plan
    from app.services.scene.builder import clamp_scene, snap_scene
    from app.services.scene.schema import Scene

    raw = await image.read()
    mime = image.content_type or "image/jpeg"

    def sample(error: str | None = None) -> dict[str, Any]:
        out = Scene.model_validate(sample_plan.sample_scene()).model_dump()
        out["_source"] = "sample"
        if error:
            out["_error"] = error[:200]
        return out

    if sample_plan.is_sample_image(raw):
        return sample()

    SCENE_PROMPT = """You are a forensic scene analyst. The image is a floor plan / hand-drawn
sketch of a place, or a photograph of a room. Rebuild the space as ONE JSON object (no prose, no
markdown) in the same format as the example: the floor plan as straight wall segments, each with
its doors and windows.

{
  "template": "house",
  "room": {
    "width_m": <overall east-west size>, "depth_m": <overall north-south size>,
    "doors": [], "windows": [],
    "outline": [[x,z], ...],
    "walls": [
      {"id":"wall_north","a":[x,z],"b":[x,z],"exterior":true,
       "openings":[
         {"id":"window1","kind":"window","offset_m":1.6,"width_m":1.8},
         {"id":"door1","kind":"door","offset_m":3.6,"width_m":0.9,"hinge":"end","opens":"north"}
       ]}
    ],
    "areas": [{"id":"room1","name":"Bedroom","rect":[x0,z0,x1,z1]}]
  },
  "objects": [{"id":"bed1","type":"bed","pos":[x,0,z],"size":[w,h,d],"rot_y_deg":0}],
  "people": [{"id":"person1","role":"suspect","pos":[x,0,z],"facing_deg":180}],
  "evidence": [{"id":"ev1","label":"knife","pos":[x,0,z]}],
  "lighting": {"type":"indoor","level":"normal"}
}

Rules:
- Metres. Origin is the north-west corner of the whole plan; x runs east, z runs south, y=0 is the
  floor. The top of a drawing is north. In a photograph the wall facing the camera is north, the
  left wall west, the right wall east and the camera side south.
- With no scale, take a door as 0.9 m wide (2.1 m tall); single bed 0.9 x 2.0 m, double bed
  1.6 x 2.0 m, table height 0.75 m.
- "walls": every outer AND inner wall as a straight segment from "a" to "b" along the wall's centre
  line; exterior=true for outer walls. Split a wall only where the plan turns a corner.
- "openings": EVERY door (also open doorways and arches) and EVERY window on that wall.
  "offset_m" is the distance from the wall's "a" end to the opening's nearer edge, "width_m" its
  width. Doors: "hinge" is "start" if the hinge is at the edge nearer "a", else "end"; "opens" is
  the side (north/south/east/west) the door leaf swings into (drawn as the quarter-circle arc).
- "outline": the outer boundary of the floor as a polygon, clockwise from the north-west corner.
- "areas": one per room or space, its bounding rectangle, a short name (bedroom, hall, kitchen...).
- Objects: every piece of furniture or fixture; "type" is one short lowercase word (bed, sofa,
  chair, table, desk, cabinet, wardrobe, shelf, tv, fridge, stove, sink, toilet, bathtub, counter).
  "pos" is the centre of its base, "size" [width, height, depth], "rot_y_deg" clockwise from above.
- People only if visible (role suspect, witness or other); evidence only if marked as evidence.
- Every id unique. Keep everything inside the outline. Return ONLY the JSON object."""

    try:
        if not container.settings.gemini_configured:
            raise ProviderError("Gemini is not configured on the server", provider="gemini")
        ref = sample_plan.sample_image()
        example = (ref, "image/png", sample_plan.sample_scene()) if ref else None
        vision = GeminiVision(container.settings)
        raw_scene = await vision.analyze(raw, mime, SCENE_PROMPT, example=example)
        scene = Scene.model_validate(raw_scene)
        if not (scene.room.walls or scene.room.doors or scene.room.windows):
            raise ProviderError("no walls, doors or windows found in the image", provider="gemini")
        # snap to the grid and keep everything inside the walls (no overlap nudging: the image
        # is the source of truth for where things are)
        out = clamp_scene(snap_scene(scene)).model_dump()
        out["_source"] = "image"
        return out
    except Exception as exc:  # noqa: BLE001
        get_logger(__name__).warning("scene map analysis failed: %s", exc)
        return sample(str(exc))
