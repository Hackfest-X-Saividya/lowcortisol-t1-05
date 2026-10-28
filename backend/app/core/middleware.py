"""Request-id and security-header middleware."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), geolocation=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        request.state.request_id = rid
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        for k, v in SECURITY_HEADERS.items():
            # /docs needs scripts; keep CSP off the interactive docs only.
            if k == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc"):
                continue
            response.headers.setdefault(k, v)
        return response
