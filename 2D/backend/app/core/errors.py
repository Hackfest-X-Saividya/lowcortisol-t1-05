"""Typed application errors and the single JSON error shape.

Every error leaving the API looks like::

    {"error": {"code": "...", "message": "...", "request_id": "..."}}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_var

log = get_logger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code.replace("_", " ")
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMedia(AppError):
    status_code = 415
    code = "unsupported_media_type"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class Locked(AppError):
    status_code = 423
    code = "locked"


class ProviderError(AppError):
    """Raised by AI providers after retries are exhausted."""

    status_code = 502
    code = "provider_error"

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        retryable: bool = False,
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.provider = provider
        self.retryable = retryable
        self.status = status


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


def error_body(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id or request_id_var.get(),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        body = error_body(exc.code, exc.message)
        if exc.details:
            body["error"]["details"] = exc.details
        headers = {}
        if isinstance(exc, RateLimited):
            headers["Retry-After"] = str(exc.details.get("retry_after", 60))
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = error_body("validation_failed", "Request validation failed")
        body["error"]["details"] = {"errors": exc.errors()}
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, msg),
            headers=dict(exc.headers or {}),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500, content=error_body("internal_error", "Internal server error")
        )
