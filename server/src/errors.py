"""Structured API errors with stable machine-readable codes.

Endpoints raise :class:`ApiError` instead of plain ``HTTPException`` so the
client can translate known failure codes while keeping the English
``detail`` message for humans and diagnostics. The response body is::

    {"detail": "...", "error_code": "...", "error_params": {...}}
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """An API failure described by a stable ``code`` and optional ``params``."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        params: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.params = dict(params or {})


def _handle(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.message,
            "error_code": exc.code,
            "error_params": exc.params,
        },
    )


def register_error_handler(app: FastAPI) -> None:
    """Install the :class:`ApiError` handler on *app*."""
    app.add_exception_handler(ApiError, _handle)
