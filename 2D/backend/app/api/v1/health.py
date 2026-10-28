from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import ContainerDep

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(container: ContainerDep) -> dict[str, Any]:
    settings = container.settings
    db_ok = True
    try:
        async with container.db.session() as s:
            await s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ready" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "ai_mode": settings.ai_mode,
        "data_mode": settings.data_mode,
        "cloud_mode_ack": settings.cloud_mode_ack,
        "providers": settings.provider_status(),
        "chains": {
            "llm": settings.llm_chain,
            "asr": settings.asr_chain,
            "image": settings.image_chain,
            "inpaint": settings.inpaint_chain,
        },
        "landmarker": container.landmarker.status(),
    }
