"""Application entry point / bootstrap.

`main.py` only assembles the app: it loads configuration, creates the FastAPI
instance, installs cross-cutting error handling and mounts the versioned API
router. Domain routers themselves live in their domains. Business logic never
lives here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import get_settings
from app.infrastructure.persistence.sqlalchemy.session import (
    dispose_engine,
    get_sessionmaker,
)
from app.security.protection import configure_protection
from app.shared.exceptions import AppError, status_for


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Own the infrastructure lifecycle around the app's running period.

    Startup initialises the shared session factory (the engine itself connects
    lazily, so a briefly-unreachable database cannot fail boot); shutdown drains
    its connection pool so the process exits cleanly. This is the one place the
    persistence machinery is started and stopped, so no domain or route has to.
    """
    get_sessionmaker()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=_lifespan,
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Liveness probe used for bootstrap/deployment verification."""
        return {"status": "ok", "service": settings.app_name}

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        """Translate framework-free domain errors into HTTP responses."""
        return JSONResponse(status_code=status_for(exc), content={"detail": exc.message})

    configure_protection(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
