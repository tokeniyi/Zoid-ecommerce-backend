"""Shared pytest fixtures and the test-database safety harness.

Database isolation
------------------
Tests that touch PostgreSQL declare it with ``pytestmark = pytest.mark.database``.
They run only against ``TEST_DATABASE_URL`` (see ``tests/support/database.py``
for what makes a URL acceptable); ``DATABASE_URL`` is never used as a fallback.

* Before the first database test, the test database's ``public`` schema is
  dropped and rebuilt by the real Alembic migration chain.
* Before every database test, application tables are truncated, except the
  reference data the migrations seed. Truncating *before* (and once more at
  the end of the session) means a test that crashed cannot leak rows into the
  next one or into the next run.
* Selecting a database test without ``TEST_DATABASE_URL`` stops the run
  before anything executes. Without it, ``DATABASE_URL`` is pointed at an
  address that refuses connections, so an unmarked test that reaches for the
  database fails loudly instead of writing to a developer's database.

Client
------
A function-scoped ``TestClient`` is used by all database-backed API tests so
every test starts with an isolated client and an empty cookie jar. Login and
guest-cart cookies from one test can never authenticate requests in another.

The application's lazily-created global async engine lives on the client's own
event loop for the duration of that test only: the TestClient context manager
runs the app lifespan, which creates the engine on startup and disposes it on
shutdown, so no engine (or pooled connection) outlives the loop that created it.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.support.database import (
    ALLOW_REMOTE_ENV,
    SEEDED_TABLES,
    TEST_DATABASE_ENV,
    UNCONFIGURED_DATABASE_URL,
    UnsafeTestDatabaseError,
    alembic_config,
    configured_test_database_url,
    redact,
    validate_test_database_url,
)

_test_database_url: str | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Decide which database the whole run may use, before any app import."""
    global _test_database_url

    url = configured_test_database_url()
    if url is not None:
        try:
            _test_database_url = validate_test_database_url(
                url, allow_remote=os.environ.get(ALLOW_REMOTE_ENV) == "1"
            )
        except UnsafeTestDatabaseError as exc:
            raise pytest.UsageError(str(exc)) from exc

    # Environment variables take precedence over .env in Settings, so this
    # replaces the developer's DATABASE_URL for the application and Alembic.
    os.environ["DATABASE_URL"] = _test_database_url or UNCONFIGURED_DATABASE_URL

    from app.config import get_settings

    get_settings.cache_clear()


def pytest_report_header(config: pytest.Config) -> str:
    if _test_database_url is None:
        return f"test database: not configured ({TEST_DATABASE_ENV} unset)"
    return f"test database: {redact(_test_database_url)}"


# trylast: judge only what survives -m / -k deselection, so
# `pytest -m "not database"` runs without a test database.
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _test_database_url is not None:
        return
    needing = [item.nodeid for item in items if item.get_closest_marker("database")]
    if needing:
        raise pytest.UsageError(
            f"{len(needing)} selected test(s) need {TEST_DATABASE_ENV} (first: {needing[0]}). "
            "Point it at a disposable PostgreSQL database such as zoid_test; "
            "DATABASE_URL is never used as a fallback. See docs/TESTING.md."
        )


async def _execute(*statements: str) -> None:
    assert _test_database_url is not None
    engine = create_async_engine(_test_database_url)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


def _truncate_statement() -> str:
    from app.infrastructure.persistence.sqlalchemy.models import Base

    tables = [t.name for t in Base.metadata.sorted_tables if t.name not in SEEDED_TABLES]
    return f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"


def _migrate_to_head() -> None:
    command.upgrade(alembic_config(), "head")


@pytest.fixture(scope="session")
def migrated_test_database() -> Iterator[str]:
    """An empty test database built by the real migration chain, once per run."""
    assert _test_database_url is not None
    asyncio.run(_execute("DROP SCHEMA IF EXISTS public CASCADE", "CREATE SCHEMA public"))
    _migrate_to_head()
    yield _test_database_url
    asyncio.run(_execute(_truncate_statement()))


@pytest.fixture(autouse=True)
def _database_isolation(request: pytest.FixtureRequest) -> None:
    """Give every database test empty application tables (seed data kept)."""
    if request.node.get_closest_marker("database") is None:
        return
    request.getfixturevalue("migrated_test_database")
    asyncio.run(_execute(_truncate_statement()))


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
