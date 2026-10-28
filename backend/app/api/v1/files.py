from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.api.deps import ContainerDep, DbDep, PrincipalDep
from app.services import files as file_service

router = APIRouter()


@router.get("/{file_id}")
async def get_file(
    file_id: str, principal: PrincipalDep, db: DbDep, container: ContainerDep
) -> Response:
    rec, data = await file_service.read_file(db, container, principal, file_id)
    ext = {
        "image/png": "png",
        "application/pdf": "pdf",
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
    }.get(rec.mime, "bin")
    disposition = "attachment" if rec.kind.startswith("export") else "inline"
    return Response(
        content=data,
        media_type=rec.mime,
        headers={
            "Content-Disposition": f'{disposition}; filename="{rec.kind}-{rec.id[:8]}.{ext}"',
            "X-File-SHA256": rec.sha256_plain,
            "Cache-Control": "private, no-store",
        },
    )
