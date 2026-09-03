"""HTTP Request Tracing, Structured Logging, Security, and Global Error Middleware Subsystem.

Provides FastAPI middleware for X-Request-ID header tracing, HTTP request logging,
process latency timing headers, security header injection, and global exception handlers converting engine errors into JSON ErrorResponses.
"""

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from basalt.api.schemas import ErrorDetail, ErrorResponse, create_error_response
from basalt.core.dag.exceptions import BasaltError
from basalt.utils.crypto import generate_uuid
from basalt.utils.logger import get_logger

logger = get_logger(__name__)


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Middleware injecting unique X-Request-ID header into requests and responses."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID") or generate_uuid()
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware logging HTTP request arrival, response status code, and latency timing."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        start_time = time.perf_counter()
        req_id = getattr(request.state, "request_id", "unknown")
        client_ip = request.client.host if request.client else "unknown"

        logger.info(f"[{req_id}] HTTP {request.method} {request.url.path} from {client_ip}")

        try:
            response = await call_next(request)
            process_time_ms = (time.perf_counter() - start_time) * 1000.0
            response.headers["X-Process-Time-MS"] = f"{process_time_ms:.2f}"

            logger.info(
                f"[{req_id}] HTTP {request.method} {request.url.path} -> {response.status_code} "
                f"({process_time_ms:.2f}ms)"
            )
            return response
        except Exception as exc:
            process_time_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(
                f"[{req_id}] HTTP {request.method} {request.url.path} uncaught error: {exc} "
                f"({process_time_ms:.2f}ms)",
                exc_info=True,
            )
            raise exc


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware injecting HTTP security headers to protect REST API endpoints."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Basalt-Engine-Version"] = "1.0.0"
        return response


class APIVersionHeaderMiddleware(BaseHTTPMiddleware):
    """Middleware attaching API version telemetry header to response objects."""

    def __init__(self, app: FastAPI, api_version: str = "v1") -> None:
        super().__init__(app)
        self.api_version = api_version

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        response = await call_next(request)
        response.headers["X-API-Version"] = self.api_version
        return response


def setup_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on FastAPI application instance."""

    @app.exception_handler(BasaltError)
    async def strata_error_handler(request: Request, exc: BasaltError) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        logger.warning(f"[{req_id}] BasaltError caught: [{exc.code}] {exc.message}")

        status_code = status.HTTP_400_BAD_REQUEST
        if exc.code == "DAG_NOT_FOUND" or exc.code == "RUN_NOT_FOUND":
            status_code = status.HTTP_404_NOT_FOUND
        elif exc.code == "ALREADY_EXISTS":
            status_code = status.HTTP_409_CONFLICT
        elif exc.code == "WEBHOOK_AUTH_ERROR":
            status_code = status.HTTP_401_UNAUTHORIZED

        err_payload = ErrorResponse(
            error=ErrorDetail(
                message=exc.message,
                code=exc.code,
                timestamp=datetime.now(UTC),
                details=exc.details,
            )
        )
        return JSONResponse(status_code=status_code, content=err_payload.model_dump(mode="json"))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        logger.warning(f"[{req_id}] HTTPException caught ({exc.status_code}): {exc.detail}")

        err_payload = create_error_response(
            message=str(exc.detail),
            code=f"HTTP_{exc.status_code}",
        )
        return JSONResponse(
            status_code=exc.status_code, content=err_payload.model_dump(mode="json")
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        logger.warning(f"[{req_id}] RequestValidationError caught: {exc.errors()}")

        err_payload = create_error_response(
            message="Request body payload or parameter validation failed.",
            code="VALIDATION_ERROR",
            details={"errors": exc.errors()},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=err_payload.model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def global_unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        logger.error(f"[{req_id}] Uncaught 500 Exception: {exc}", exc_info=True)

        err_payload = create_error_response(
            message="Internal server error occurred processing request.",
            code="INTERNAL_SERVER_ERROR",
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=err_payload.model_dump(mode="json"),
        )
