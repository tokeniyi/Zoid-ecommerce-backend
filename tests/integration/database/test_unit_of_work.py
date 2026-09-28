"""Proves the persistence foundation against the configured PostgreSQL.

Gate requirements: session opens, a transaction commits, and a transaction
rolls back. A scratch table (its own metadata, separate from the domain
`Base`) is used so this phase does not depend on any domain model.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Column, Integer, MetaData, String, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork


class _ProbeBase(DeclarativeBase):
    # Dedicated metadata so this scratch table never enters the domain Base
    # that Alembic autogeneration reads.
    metadata = MetaData()


class Probe(_ProbeBase):
    __tablename__ = "zoid_uow_probe"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String, nullable=False)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    async with eng.begin() as conn:
        await conn.run_sync(_ProbeBase.metadata.drop_all)
        await conn.run_sync(_ProbeBase.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(_ProbeBase.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _count(maker: async_sessionmaker) -> int:
    async with maker() as session:
        return await session.scalar(select(func.count()).select_from(Probe)) or 0


async def test_session_opens(maker: async_sessionmaker) -> None:
    async with SqlAlchemyUnitOfWork(maker) as uow:
        assert uow.session is not None
        assert await uow.session.scalar(select(1)) == 1


async def test_transaction_commits(maker: async_sessionmaker) -> None:
    label = f"keep-{uuid.uuid4()}"
    async with SqlAlchemyUnitOfWork(maker) as uow:
        uow.session.add(Probe(label=label))
        await uow.commit()

    async with maker() as verify:
        found = await verify.scalar(select(Probe).where(Probe.label == label))
    assert found is not None


async def test_transaction_rolls_back(maker: async_sessionmaker) -> None:
    before = await _count(maker)
    label = f"discard-{uuid.uuid4()}"
    async with SqlAlchemyUnitOfWork(maker) as uow:
        uow.session.add(Probe(label=label))
        await uow.rollback()

    assert await _count(maker) == before
    async with maker() as verify:
        found = await verify.scalar(select(Probe).where(Probe.label == label))
    assert found is None


async def test_context_manager_rolls_back_on_exception(maker: async_sessionmaker) -> None:
    before = await _count(maker)
    label = f"boom-{uuid.uuid4()}"
    with pytest.raises(RuntimeError):
        async with SqlAlchemyUnitOfWork(maker) as uow:
            uow.session.add(Probe(label=label))
            raise RuntimeError("failure")
    assert await _count(maker) == before
