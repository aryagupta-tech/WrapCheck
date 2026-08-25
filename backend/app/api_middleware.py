import logging
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)


def install_api_middleware(app, repository) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled API error", extra={"request_id": request_id})
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "internal_error", "message": "The request could not be completed.", "retryable": True, "request_id": request_id}},
            )
        response.headers["X-Request-ID"] = request_id
        try:
            repository.client.insert(
                "request_audit",
                [[request_id, request.method, request.url.path, response.status_code, round((perf_counter() - started) * 1000), datetime.now(timezone.utc)]],
                column_names=["request_id", "method", "path", "status_code", "duration_ms", "created_at"],
            )
        except Exception:
            pass
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        request_id = getattr(request.state, "request_id", str(uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={"error": {"code": _code(exc.status_code), "message": str(exc.detail), "retryable": exc.status_code in {429, 502, 503, 504}, "request_id": request_id}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", str(uuid4()))
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "Request validation failed.", "retryable": False, "request_id": request_id, "fields": jsonable_encoder(exc.errors())}},
        )


def _code(status: int) -> str:
    return {
        400: "bad_request", 403: "forbidden", 404: "not_found", 409: "conflict",
        413: "payload_too_large", 415: "unsupported_media_type", 422: "validation_error",
        429: "quota_exceeded", 503: "service_unavailable",
    }.get(status, "request_failed")
