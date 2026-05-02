from __future__ import annotations

import logging
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError


class APIError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(APIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="NOT_FOUND", status_code=status.HTTP_404_NOT_FOUND, details=details)


class UnauthorizedError(APIError):
    def __init__(self, message: str = "Unauthorized", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="UNAUTHORIZED", status_code=status.HTTP_401_UNAUTHORIZED, details=details)


class ForbiddenError(APIError):
    def __init__(self, message: str = "Forbidden", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="FORBIDDEN", status_code=status.HTTP_403_FORBIDDEN, details=details)


class ValidationAPIError(APIError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="VALIDATION_ERROR", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


def _build_error_response(
    error: APIError | Exception,
    correlation_id: str,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    if isinstance(error, APIError):
        payload: dict[str, Any] = {
            "error": error.message,
            "code": error.code,
            "correlation_id": correlation_id,
        }
        if error.details:
            payload["detail"] = error.details
        if logger:
            logger.warning("API error: %s [%s]", error.message, error.code)
        return payload

    if isinstance(error, RequestValidationError):
        return {
            "error": "Request validation failed",
            "code": "VALIDATION_ERROR",
            "correlation_id": correlation_id,
            "detail": error.errors(),
        }

    if isinstance(error, ValidationError):
        return {
            "error": "Data validation failed",
            "code": "VALIDATION_ERROR",
            "correlation_id": correlation_id,
            "detail": error.errors(),
        }

    return {
        "error": "Internal server error",
        "code": "INTERNAL_ERROR",
        "correlation_id": correlation_id,
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        correlation_id = str(uuid.uuid4())
        return JSONResponse(
            status_code=exc.status_code,
            content=_build_error_response(exc, correlation_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        correlation_id = str(uuid.uuid4())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_build_error_response(exc, correlation_id),
        )

    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        correlation_id = str(uuid.uuid4())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_build_error_response(exc, correlation_id),
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = str(uuid.uuid4())
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if logger := getattr(request.app.state, "logger", None):
            logger.exception("Unhandled exception: %s", exc)
        else:
            logging.getLogger("shadowfleet.api").exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal server error",
                "code": "INTERNAL_ERROR",
                "correlation_id": correlation_id,
                "detail": tb if logging.getLogger().isEnabledFor(logging.DEBUG) else None,
            },
        )
