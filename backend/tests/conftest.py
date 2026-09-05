"""Shared pytest fixtures (decision #17: integration tests against real PostgreSQL).

The DATABASE_URL / TESTING env vars are set BEFORE any app import so the whole
application (including settings + engine) is bound to the dedicated test database.
"""

import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://tracking:tracking@localhost:5432/tracking_test"
os.environ["TESTING"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import BusRoute, User, Vehicle  # noqa: E402


@pytest.fixture(autouse=True)
async def _fresh_schema():
    """Drop + recreate all tables around every test: full isolation, reset sequences."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db():
    """Direct DB session for seeding/asserting inside tests."""
    async with async_session_factory() as session:
        yield session


# --- Data factories ----------------------------------------------------------


@pytest.fixture
def make_user():
    async def _make(
        email: str = "user@test.com",
        password: str = "password123",
        *,
        is_admin: bool = False,
        route: BusRoute | None = None,
        vehicle: Vehicle | None = None,
    ) -> User:
        async with async_session_factory() as session:
            user = User(
                email=email,
                hashed_password=hash_password(password),
                is_admin=is_admin,
                route_id=route.id if route else None,
                vehicle_id=vehicle.id if vehicle else None,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _make


@pytest.fixture
def make_route():
    async def _make(name: str = "Route A", waypoints: list | None = None) -> BusRoute:
        async with async_session_factory() as session:
            route = BusRoute(
                name=name,
                waypoints=waypoints
                or [{"lat": 13.0827, "lng": 80.2707}, {"lat": 12.99, "lng": 80.22}],
            )
            session.add(route)
            await session.commit()
            await session.refresh(route)
            return route

    return _make


@pytest.fixture
def make_vehicle():
    async def _make(code: str = "BUS-001", name: str = "Test Bus") -> Vehicle:
        async with async_session_factory() as session:
            vehicle = Vehicle(code=code, name=name)
            session.add(vehicle)
            await session.commit()
            await session.refresh(vehicle)
            return vehicle

    return _make


# --- HTTP helpers ------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client: TestClient):
    """Authorization header factory: login as the given user, return bearer header."""

    def _auth(email: str, password: str) -> dict[str, str]:
        r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, f"login failed for {email}: {r.json()}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _auth
