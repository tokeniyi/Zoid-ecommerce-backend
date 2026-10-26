"""Which database the test suite may destroy, and how it is reset.

Database-backed tests drop the ``public`` schema, migrate it from scratch and
truncate tables between tests, so they must never reach a database someone
cares about. The rules are deliberately strict and fail closed:

* the URL comes only from ``TEST_DATABASE_URL`` (environment, then ``.env``),
  never from ``DATABASE_URL``;
* it must be ``postgresql+asyncpg`` and the database name must contain
  ``test`` as a distinct token (``zoid_test``, ``test-zoid``; not ``latest``);
* the host must be local (or the docker-compose ``postgres`` service) unless
  ``ALLOW_REMOTE_TEST_DATABASE=1`` is set explicitly.

When no test database is configured the suite points ``DATABASE_URL`` at an
address that cannot be connected to, so a test that touches the database
without being marked ``database`` fails instead of writing to a dev database.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from alembic.config import Config
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]

TEST_DATABASE_ENV = "TEST_DATABASE_URL"
ALLOW_REMOTE_ENV = "ALLOW_REMOTE_TEST_DATABASE"

# Port 1 on the loopback interface: nothing listens there, so any connection
# attempt is refused. The name makes the cause obvious in a traceback.
UNCONFIGURED_DATABASE_URL = (
    "postgresql+asyncpg://test-database-not-configured@127.0.0.1:1/set_TEST_DATABASE_URL"
)

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})
_TEST_TOKEN = re.compile(r"(?:^|[_-])test(?:[_-]|$)")

# Reference data seeded by migrations. Truncating it would leave the tests
# running on a state a freshly deployed database never has.
SEEDED_TABLES = frozenset({"roles"})


class UnsafeTestDatabaseError(ValueError):
    """The configured test database could belong to someone else."""


def configured_test_database_url(
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = ROOT / ".env",
) -> str | None:
    """``TEST_DATABASE_URL`` from the environment, else from ``.env``, else ``None``."""
    environ = os.environ if environ is None else environ
    url = environ.get(TEST_DATABASE_ENV, "").strip()
    if not url and env_file is not None and env_file.is_file():
        url = (dotenv_values(env_file).get(TEST_DATABASE_ENV) or "").strip()
    return url or None


def validate_test_database_url(url: str, *, allow_remote: bool = False) -> str:
    """Return ``url`` if it is safe to destroy, else raise ``UnsafeTestDatabaseError``."""
    parts = urlsplit(url)
    if parts.scheme != "postgresql+asyncpg":
        raise UnsafeTestDatabaseError(
            f"{TEST_DATABASE_ENV} must use the postgresql+asyncpg driver"
        )

    database = parts.path.removeprefix("/")
    if not _TEST_TOKEN.search(database):
        raise UnsafeTestDatabaseError(
            f"{TEST_DATABASE_ENV} must name a database containing the distinct token "
            f"'test' (for example zoid_test); got {database!r}"
        )

    host = (parts.hostname or "").lower()
    if host not in _LOCAL_HOSTS and not allow_remote:
        raise UnsafeTestDatabaseError(
            f"{TEST_DATABASE_ENV} points at host {host!r}; only local hosts are allowed "
            f"unless {ALLOW_REMOTE_ENV}=1 is set"
        )
    return url


def redact(url: str) -> str:
    """The URL with any credentials removed, for logs and reports."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    credentials = "<REDACTED>@" if parts.username or parts.password else ""
    return f"{parts.scheme}://{credentials}{host}{port}{parts.path}"


def alembic_config() -> Config:
    """The project's migration chain, without alembic.ini's logging setup.

    alembic.ini's ``fileConfig`` would reconfigure (and silence) the loggers
    pytest has already set up, so only the script location is taken over.
    """
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config
