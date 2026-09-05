"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    # Phase 0: no DB dependency yet; later phases swap in a test database via dependency_overrides
    with TestClient(app) as c:
        yield c
