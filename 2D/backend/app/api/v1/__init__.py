from fastapi import APIRouter

from app.api.v1 import (
    admin,
    audit,
    auth,
    cases,
    exports,
    files,
    health,
    interview,
    jobs,
    live,
    scene,
    sessions,
    signoff,
    sketch,
    statements,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(cases.router, prefix="/cases", tags=["cases"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(statements.router, tags=["statements"])
api_router.include_router(interview.router, tags=["interview"])
api_router.include_router(live.router, tags=["live interview"])
api_router.include_router(sketch.router, tags=["sketch"])
api_router.include_router(scene.router, tags=["scene"])
api_router.include_router(signoff.router, tags=["signoff"])
api_router.include_router(exports.router, tags=["exports"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
