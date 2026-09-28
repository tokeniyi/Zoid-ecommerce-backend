"""CORS configuration.

Origins/credentials come from settings so the policy is environment-driven and
never hardcoded per route.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings


def cors_middleware_options() -> dict[str, Any]:
    """CORSMiddleware keyword args derived from configuration."""
    settings = get_settings()
    return {
        "allow_origins": settings.cors_origin_list,
        "allow_credentials": settings.cors_allow_credentials,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


def configure_cors(app: FastAPI) -> None:
    """Install the configured CORS middleware."""
    app.add_middleware(CORSMiddleware, **cors_middleware_options())
