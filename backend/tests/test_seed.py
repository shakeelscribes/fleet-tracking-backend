"""Phase 7 acceptance: seed is complete, correct, idempotent, and non-destructive."""

import pytest
from sqlalchemy import func, select

from app import seed as seed_module
from app.db.session import async_session_factory
from app.models import BusRoute, User, Vehicle

pytestmark = pytest.mark.usefixtures("_fresh_schema")



async def _table_counts() -> tuple[int, int, int]:
    async with async_session_factory() as db:
        users = await db.scalar(select(func.count()).select_from(User))
        routes = await db.scalar(select(func.count()).select_from(BusRoute))
        vehicles = await db.scalar(select(func.count()).select_from(Vehicle))
    return users or 0, routes or 0, vehicles or 0


class TestSeed:
    async def test_seed_populates_full_dataset(self):
        created = await seed_module.seed()
        assert created == {"routes": 4, "vehicles": 4, "users": 5}
        assert await _table_counts() == (5, 4, 4)

    async def test_assignments_strict_1_1_1(self):
        await seed_module.seed()
        async with async_session_factory() as db:
            for email, route_name, vehicle_code in seed_module.DEMO_ASSIGNMENTS:
                user = await db.scalar(select(User).where(User.email == email))
                assert user is not None, email
                route = await db.get(BusRoute, user.route_id)
                vehicle = await db.get(Vehicle, user.vehicle_id)
                assert route.name == route_name, email
                assert vehicle.code == vehicle_code, email

    async def test_admin_exists_without_assignment(self):
        await seed_module.seed()
        async with async_session_factory() as db:
            admin = await db.scalar(
                select(User).where(User.email == seed_module.ADMIN_EMAIL)
            )
            assert admin is not None and admin.is_admin is True
            assert admin.route_id is None and admin.vehicle_id is None

    async def test_seed_is_idempotent(self):
        await seed_module.seed()
        second = await seed_module.seed()
        assert second == {"routes": 0, "vehicles": 0, "users": 0}
        assert await _table_counts() == (5, 4, 4)  # no duplicates

    async def test_seed_never_clobbers_external_changes(self):
        """Rows created through the admin API survive a re-seed."""
        async with async_session_factory() as db:
            db.add(Vehicle(code="BUS-999", name="Added via API"))
            await db.commit()
        await seed_module.seed()
        async with async_session_factory() as db:
            extra = await db.scalar(select(Vehicle).where(Vehicle.code == "BUS-999"))
            assert extra is not None

    async def test_fresh_reset_rebuilds_demo(self):
        async with async_session_factory() as db:
            db.add(Vehicle(code="BUS-999", name="To be wiped"))
            await db.commit()
        await seed_module.seed()
        await seed_module.seed(fresh=True)
        async with async_session_factory() as db:
            extra = await db.scalar(select(Vehicle).where(Vehicle.code == "BUS-999"))
            assert extra is None  # wiped
        assert await _table_counts() == (5, 4, 4)

    async def test_seeded_users_can_login(self, client):
        await seed_module.seed()
        password = "password123"  # default SEED_PASSWORD
        for email in [seed_module.ADMIN_EMAIL] + [a[0] for a in seed_module.DEMO_ASSIGNMENTS]:
            r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
            assert r.status_code == 200, email
            body = r.json()
            assert body["access_token"] and body["refresh_token"]

    async def test_seeded_driver_sees_own_assignment(self, client):
        await seed_module.seed()
        r = client.post(
            "/api/v1/auth/login", json={"email": "ravi@fleet.com", "password": "password123"}
        )
        token = r.json()["access_token"]
        me = client.get("/api/v1/me/assignment", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        body = me.json()
        assert body["route"]["name"] == "City Center to Airport"
        assert body["vehicle"]["code"] == "BUS-001"

    async def test_seeded_routes_have_valid_chennai_waypoints(self):
        await seed_module.seed()
        async with async_session_factory() as db:
            for route in (await db.execute(select(BusRoute))).scalars():
                assert len(route.waypoints) >= 2
                for wp in route.waypoints:
                    assert 12.5 <= wp["lat"] <= 13.5  # Chennai-ish
                    assert 79.5 <= wp["lng"] <= 80.5
