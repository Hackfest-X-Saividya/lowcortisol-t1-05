"""slowapi limiter used on POST /auth/login."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.errors import error_body

limiter = Limiter(key_func=get_remote_address, headers_enabled=False)


def install_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content=error_body("rate_limited", f"Too many requests: {exc.detail}"),
            headers={"Retry-After": "60"},
        )
