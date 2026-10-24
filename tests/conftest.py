"""Shared pytest fixtures.

A function-scoped ``TestClient`` is used by all database-backed API tests so
every test starts with an isolated client and an empty cookie jar. Login and
guest-cart cookies from one test can never authenticate requests in another.

The application's lazily-created global async engine lives on the client's own
event loop for the duration of that test only: the TestClient context manager
runs the app lifespan, which creates the engine on startup and disposes it on
shutdown, so no engine (or pooled connection) outlives the loop that created it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
