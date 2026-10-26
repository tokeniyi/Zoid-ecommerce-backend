"""The Alembic chain builds, from nothing, exactly the schema the models declare.

The session fixture has already dropped the test database's ``public`` schema
and run ``alembic upgrade head`` before these tests start, so they inspect a
database built only by migrations. Comparing it with the ORM metadata (the same
comparison ``alembic revision --autogenerate`` makes) catches a model change
that shipped without its migration, as well as a migration that diverged from
its model: tables, columns, types, nullability, indexes, unique constraints and
foreign keys.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.infrastructure.persistence.sqlalchemy.models import Base
from tests.support.database import alembic_config

pytestmark = pytest.mark.database

SEEDED_ROLES = {"customer", "admin"}


def _on_test_database(inspect_with: Any) -> Any:
    """Run a synchronous inspection callable against the test database."""

    async def run() -> Any:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(inspect_with)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _drift(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return compare_metadata(context, Base.metadata)


def _tables(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _roles(connection: Connection) -> set[str]:
    return set(connection.execute(text("SELECT name FROM roles")).scalars())


def _revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def test_the_chain_has_exactly_one_head() -> None:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1, f"divergent migration heads need a merge revision: {heads}"


def test_the_database_is_at_head_after_upgrade() -> None:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert _on_test_database(_revision) == head


def test_migrations_create_every_model_table_and_nothing_else() -> None:
    assert _on_test_database(_tables) == set(Base.metadata.tables) | {"alembic_version"}


def test_the_migrated_schema_matches_the_models_exactly() -> None:
    drift = _on_test_database(_drift)
    assert drift == [], "models and migrations disagree; generate a migration:\n" + "\n".join(
        map(repr, drift)
    )


def test_a_fresh_database_has_the_rbac_roles() -> None:
    assert _on_test_database(_roles) == SEEDED_ROLES


def test_every_migration_downgrades_and_the_chain_reapplies() -> None:
    """Downgrade paths are required for every migration; run them all.

    Leaves the database back at head, as the session fixture built it.
    """
    config = alembic_config()

    command.downgrade(config, "base")
    assert _on_test_database(_tables) <= {"alembic_version"}
    assert _on_test_database(_revision) is None

    command.upgrade(config, "head")
    assert _on_test_database(_drift) == []
    assert _on_test_database(_roles) == SEEDED_ROLES
