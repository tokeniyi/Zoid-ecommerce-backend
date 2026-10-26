"""The guard that decides which database the suite is allowed to destroy.

Every case passes its environment explicitly, so the result never depends on
what the developer or CI happens to have exported.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.database import (
    SEEDED_TABLES,
    UNCONFIGURED_DATABASE_URL,
    UnsafeTestDatabaseError,
    configured_test_database_url,
    redact,
    validate_test_database_url,
)

SAFE = "postgresql+asyncpg://user:secret@localhost:5432/zoid_test"


def test_nothing_configured_means_no_test_database(tmp_path: Path) -> None:
    assert configured_test_database_url({}, env_file=tmp_path / "missing.env") is None
    assert configured_test_database_url({"TEST_DATABASE_URL": "  "}, env_file=None) is None


def test_database_url_is_never_used_as_a_fallback(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql+asyncpg://u:p@localhost/zoid\n")

    environ = {"DATABASE_URL": "postgresql+asyncpg://u:p@localhost/zoid"}
    assert configured_test_database_url(environ, env_file=env_file) is None


def test_the_environment_wins_over_the_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DATABASE_URL=postgresql+asyncpg://u:p@localhost/file_test\n")

    assert configured_test_database_url({}, env_file=env_file).endswith("/file_test")
    environ = {"TEST_DATABASE_URL": SAFE}
    assert configured_test_database_url(environ, env_file=env_file) == SAFE


@pytest.mark.parametrize(
    "url",
    [
        SAFE,
        "postgresql+asyncpg://u:p@127.0.0.1/test",
        "postgresql+asyncpg://u:p@postgres:5432/test-zoid",
        "postgresql+asyncpg://u:p@[::1]/zoid_test_2",
    ],
)
def test_local_databases_named_for_testing_are_accepted(url: str) -> None:
    assert validate_test_database_url(url) == url


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("postgresql+asyncpg://u:p@localhost:5432/zoid", "token 'test'"),
        ("postgresql+asyncpg://u:p@localhost:5432/latest", "token 'test'"),
        ("postgresql+asyncpg://u:p@localhost:5432/zoidtest", "token 'test'"),
        ("postgresql+asyncpg://u:p@localhost:5432/", "token 'test'"),
        ("postgresql://u:p@localhost:5432/zoid_test", "postgresql\\+asyncpg"),
        ("sqlite+aiosqlite:///zoid_test.db", "postgresql\\+asyncpg"),
        ("postgresql+asyncpg://u:p@db.prod.example.com/zoid_test", "only local hosts"),
    ],
)
def test_databases_that_may_belong_to_someone_else_are_refused(url: str, reason: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match=reason):
        validate_test_database_url(url)


def test_a_remote_test_database_needs_an_explicit_opt_in() -> None:
    url = "postgresql+asyncpg://u:p@ci-db.internal/zoid_test"
    assert validate_test_database_url(url, allow_remote=True) == url


def test_the_unconfigured_placeholder_is_not_a_usable_test_database() -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        validate_test_database_url(UNCONFIGURED_DATABASE_URL)


def test_redaction_removes_credentials_only() -> None:
    assert redact(SAFE) == "postgresql+asyncpg://<REDACTED>@localhost:5432/zoid_test"
    assert "secret" not in redact(SAFE)
    assert redact("postgresql+asyncpg://localhost/zoid_test") == (
        "postgresql+asyncpg://localhost/zoid_test"
    )


def test_seeded_reference_tables_exist_in_the_model() -> None:
    from app.infrastructure.persistence.sqlalchemy.models import Base

    assert SEEDED_TABLES <= set(Base.metadata.tables)
