"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.container import Container
from app.core.errors import install_error_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import install_rate_limiting

log = get_logger("nishaan")


def _log_startup(settings: Settings) -> None:
    log.info("Nishaan backend starting (env=%s, ai_mode=%s)", settings.app_env, settings.ai_mode)
    for name, status in settings.provider_status().items():
        log.info("Provider %s: %s", name.capitalize(), status)
    if not settings.jwt_secret.get_secret_value():
        log.warning("JWT_SECRET missing - using an ephemeral secret (tokens reset on restart)")
    if not settings.file_master_key_b64.get_secret_value():
        log.warning(
            "FILE_MASTER_KEY_B64 missing - using an ephemeral key (files unreadable after restart)"
        )
    if settings.cloud_active:
        log.warning(
            "CLOUD MODE: audio, transcripts and prompts are sent to Google, Groq and/or "
            "Cloudflare. Use demo data only. data_mode=cloud_demo (CLOUD_MODE_ACK=%s)",
            settings.cloud_mode_ack,
        )
        if not settings.cloud_mode_ack:
            log.error(
                "CLOUD_MODE_ACK is false while cloud providers are configured; "
                "cloud providers are disabled until it is acknowledged."
            )
    else:
        log.info("Running fully offline with mock providers (data_mode=local_mock)")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    if settings.app_env == "production" and (
        not settings.jwt_secret.get_secret_value()
        or not settings.file_master_key_b64.get_secret_value()
    ):
        raise RuntimeError("JWT_SECRET and FILE_MASTER_KEY_B64 are required in production")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _log_startup(settings)
        c = container or Container(settings)
        await c.start()
        app.state.container = c
        try:
            yield
        finally:
            await c.stop()

    app = FastAPI(
        title="Nishaan API",
        version="0.1.0",
        description=(
            "AI crime scene and suspect sketch generator for police. "
            "Investigative aid only. Not an identification."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )
    install_error_handlers(app)
    install_rate_limiting(app)

    from app.api.v1 import api_router
    from app.api.ws import ws_router

    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(ws_router)
    return app


app = create_app()
