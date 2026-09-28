"""Request-validation handling.

Normalises FastAPI/Pydantic request-validation failures into the same error
envelope the rest of the API uses (`{"detail": ...}`), so clients get a
consistent shape for malformed input.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# HTTP 422: kept as a literal to avoid a version-specific status-name change.
_UNPROCESSABLE = 422


def _serialize(exc: RequestValidationError) -> list[dict[str, Any]]:
    return [
        {
            "loc": list(error.get("loc", [])),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]


def install_request_validation(app: FastAPI) -> None:
    """Register the validation-error handler on the app."""

    @app.exception_handler(RequestValidationError)
    async def handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=_UNPROCESSABLE,
            content={"detail": "Request validation failed.", "errors": _serialize(exc)},
        )
