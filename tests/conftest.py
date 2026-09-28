"""Shared pytest fixtures.

A single session-scoped ``TestClient`` is used by all database-backed API tests
so the application's lazily-created global async engine lives on one event loop
for the whole session. Creating a client per module would bind the shared
engine's pooled connections to different (soon-closed) loops and break
subsequent tests with "Event loop is closed".
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
