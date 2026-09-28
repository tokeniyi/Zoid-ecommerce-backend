"""Async SQLAlchemy engine, session factory and declarative base.

This is the only place the SQLAlchemy engine/session machinery lives. Domain
and application code never import from here directly — they go through
repository interfaces and the Unit of Work contract.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models (metadata lives here)."""


def create_engine_from_url(url: str | None = None, *, echo: bool | None = None) -> AsyncEngine:
    """Build an async engine. Defaults to the configured PostgreSQL (asyncpg) URL."""
    settings = get_settings()
    return create_async_engine(
        url or settings.database_url,
        echo=settings.db_echo if echo is None else echo,
        pool_pre_ping=True,
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine_from_url()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = build_sessionmaker(get_engine())
    return _sessionmaker


async def dispose_engine() -> None:
    """Dispose the shared engine (used on app shutdown / in tests)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of operations.

    Convenience wrapper around the Unit of Work for read paths and scripts;
    the Unit of Work remains the primary boundary for write use-cases.
    """
    maker = get_sessionmaker()
    session = maker()
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()
