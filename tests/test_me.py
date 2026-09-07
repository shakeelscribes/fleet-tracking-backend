"""Phase 5 acceptance: /me endpoints, status derivation, cross-user isolation."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.session import async_session_factory
from app.models import User
from app.services.tracking_service import derive_status

pytestmark = pytest.mark.usefixtures("_fresh_schema")


# --- Unit: derive_status (decision #16) ---------------------------------------


class TestDeriveStatus:
    def test_no_fix_is_offline(self):
        assert derive_status(None, None) == "offline"

    def test_stale_fix_is_offline(self):
        old = datetime.now(UTC) - timedelta(seconds=61)
        assert derive_status(old, Decimal("40")) == "offline"

    def test_fresh_fast_is_moving(self):
        now = datetime.now(UTC)
        assert derive_status(now, Decimal("5.1")) == "moving"
        assert derive_status(now, Decimal("42.5")) == "moving"

    def test_fresh_slow_is_idle(self):
        now = datetime.now(UTC)
        assert derive_status(now, Decimal("5.0")) == "idle"  # threshold is exclusive
        assert derive_status(now, Decimal("0")) == "idle"

    def test_naive_timestamp_treated_as_utc(self):
        now = datetime.now(UTC)
        naive = now.replace(tzinfo=None)
        assert derive_status(naive, Decimal("0")) == "idle"


# --- Endpoints ----------------------------------------------------------------


class TestMeProfile:
    async def test_profile_returns_identity_and_role(self, client, auth_headers, make_user):
        """Client uses this to route by role (admin fleet view vs driver tracking)."""
        await make_user(email="admin@test.com", password="password123", is_admin=True)
        r = client.get("/api/v1/me/profile", headers=auth_headers("admin@test.com", "password123"))
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == "admin@test.com"
        assert body["is_admin"] is True

    async def test_profile_anonymous_401(self, client):
        r = client.get("/api/v1/me/profile")
        assert r.status_code == 401


class TestMeAssignment:
    async def test_assigned_user_sees_both(
        self, client, auth_headers, make_user, make_route, make_vehicle
    ):
        route, vehicle = await make_route(name="Route A"), await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", route=route, vehicle=vehicle)
        r = client.get("/api/v1/me/assignment", headers=auth_headers("u@test.com", "password123"))
        assert r.status_code == 200
        body = r.json()
        assert body["route"]["name"] == "Route A"
        assert body["vehicle"]["code"] == "BUS-001"

    async def test_unassigned_user_403_no_assignment(
        self, client, auth_headers, make_user
    ):
        await make_user(email="bare@test.com", password="password123")
        r = client.get(
            "/api/v1/me/assignment", headers=auth_headers("bare@test.com", "password123")
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "no_assignment"

    async def test_anonymous_401(self, client):
        r = client.get("/api/v1/me/assignment")
        assert r.status_code == 401


class TestMeRoute:
    async def test_polyline_round_trip(
        self, client, auth_headers, make_user, make_route, make_vehicle
    ):
        waypoints = [{"lat": 13.0827, "lng": 80.2707}, {"lat": 12.99, "lng": 80.17}]
        route = await make_route(name="City-Airport", waypoints=waypoints)
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", route=route, vehicle=vehicle)
        r = client.get("/api/v1/me/route", headers=auth_headers("u@test.com", "password123"))
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "City-Airport"
        assert body["waypoints"] == waypoints  # JSONB round-trip is lossless

    async def test_no_route_403(self, client, auth_headers, make_user, make_vehicle):
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        r = client.get("/api/v1/me/route", headers=auth_headers("u@test.com", "password123"))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "no_assignment"


class TestMeVehicleCurrent:
    async def test_no_data_yet_is_offline_nulls(
        self, client, auth_headers, make_user, make_vehicle
    ):
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        r = client.get(
            "/api/v1/me/vehicle/current", headers=auth_headers("u@test.com", "password123")
        )
        assert r.status_code == 200
        body = r.json()
        assert body["lat"] is None and body["lng"] is None
        assert body["status"] == "offline"

    async def test_fresh_fast_fix_is_moving(
        self, client, auth_headers, make_user, make_vehicle, make_gps_point
    ):
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        await make_gps_point(vehicle, lat="13.0827", lng="80.2707", speed="42.5")
        r = client.get(
            "/api/v1/me/vehicle/current", headers=auth_headers("u@test.com", "password123")
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "moving"
        assert body["lat"] == 13.0827
        assert body["vehicle_code"] == "BUS-001"

    async def test_no_vehicle_403(self, client, auth_headers, make_user, make_route):
        route = await make_route(name="Route A")
        await make_user(email="u@test.com", password="password123", route=route)
        r = client.get(
            "/api/v1/me/vehicle/current", headers=auth_headers("u@test.com", "password123")
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "no_assignment"


class TestMeVehicleHistory:
    async def test_returns_chronological_points(
        self, client, auth_headers, make_user, make_vehicle, make_gps_point
    ):
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        base = datetime.now(UTC) - timedelta(hours=2)
        for i, (lat, spd) in enumerate([("13.080", "30"), ("13.085", "32"), ("13.090", "35")]):
            await make_gps_point(
                vehicle, lat=lat, lng="80.27", speed=spd, recorded_at=base + timedelta(minutes=i)
            )
        r = client.get(
            "/api/v1/me/vehicle/history", headers=auth_headers("u@test.com", "password123")
        )
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 3
        lats = [p["lat"] for p in body["points"]]
        assert lats == sorted(lats)  # ascending recorded_at

    async def test_window_filtering(
        self, client, auth_headers, make_user, make_vehicle, make_gps_point
    ):
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        now = datetime.now(UTC)
        await make_gps_point(vehicle, recorded_at=now - timedelta(hours=30))  # outside 24h
        inside = await make_gps_point(vehicle, recorded_at=now - timedelta(hours=1))
        r = client.get(
            "/api/v1/me/vehicle/history", headers=auth_headers("u@test.com", "password123")
        )
        body = r.json()
        assert body["count"] == 1  # default window: last 24h
        assert body["points"][0]["lat"] == float(inside.lat)

    async def test_explicit_from_to(
        self, client, auth_headers, make_user, make_vehicle, make_gps_point
    ):
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        base = datetime.now(UTC) - timedelta(hours=5)
        for i in range(5):
            await make_gps_point(vehicle, recorded_at=base + timedelta(minutes=10 * i))
        frm = (base + timedelta(minutes=10)).isoformat()
        to = (base + timedelta(minutes=30)).isoformat()
        r = client.get(
            "/api/v1/me/vehicle/history",
            params={"from": frm, "to": to},  # params= encodes '+' correctly
            headers=auth_headers("u@test.com", "password123"),
        )
        body = r.json()
        assert body["count"] == 3  # minutes 10/20/30 - bounds inclusive

    async def test_limit_and_offset(
        self, client, auth_headers, make_user, make_vehicle, make_gps_point
    ):
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        base = datetime.now(UTC) - timedelta(hours=1)
        for i in range(7):
            await make_gps_point(
                vehicle,
                lat=f"13.08{i:02d}0",
                recorded_at=base + timedelta(minutes=i),
            )
        r = client.get(
            "/api/v1/me/vehicle/history?limit=2&offset=3",
            headers=auth_headers("u@test.com", "password123"),
        )
        body = r.json()
        assert body["count"] == 7  # total in window, not page size
        assert len(body["points"]) == 2
        lats = [p["lat"] for p in body["points"]]
        assert lats[0] < lats[1]  # page 2 of the ascending sequence (skip 3, take 2)

    async def test_limit_over_cap_422(self, client, auth_headers, make_user, make_vehicle):
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        r = client.get(
            "/api/v1/me/vehicle/history?limit=1001",
            headers=auth_headers("u@test.com", "password123"),
        )
        assert r.status_code == 422

    async def test_no_vehicle_403(self, client, auth_headers, make_user):
        await make_user(email="u@test.com", password="password123")
        r = client.get(
            "/api/v1/me/vehicle/history", headers=auth_headers("u@test.com", "password123")
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "no_assignment"


class TestCrossUserIsolation:
    """Decision #17: authorization tests. User B must never see user A's data."""

    async def test_history_only_own_vehicle(
        self, client, auth_headers, make_user, make_route, make_vehicle, make_gps_point
    ):
        route_a, route_b = await make_route(name="Route A"), await make_route(name="Route B")
        vehicle_a, vehicle_b = (
            await make_vehicle(code="BUS-001"),
            await make_vehicle(code="BUS-002"),
        )
        user_a = await make_user(
            email="a@test.com", password="password123", route=route_a, vehicle=vehicle_a
        )
        user_b = await make_user(
            email="b@test.com", password="password123", route=route_b, vehicle=vehicle_b
        )
        await make_gps_point(vehicle_a, lat="10.000000", lng="79.0", speed="50")
        await make_gps_point(vehicle_b, lat="20.000000", lng="79.0", speed="60")

        r_b = client.get(
            "/api/v1/me/vehicle/history", headers=auth_headers("b@test.com", "password123")
        )
        body = r_b.json()
        assert body["vehicle_id"] == vehicle_b.id
        assert len(body["points"]) == 1
        assert body["points"][0]["lat"] == 20.0  # only BUS-002 data, never BUS-001

        r_a = client.get(
            "/api/v1/me/vehicle/history", headers=auth_headers("a@test.com", "password123")
        )
        body = r_a.json()
        assert body["vehicle_id"] == vehicle_a.id
        assert body["points"][0]["lat"] == 10.0
        assert user_a.vehicle_id != user_b.vehicle_id  # sanity

    async def test_current_location_only_own_vehicle(
        self, client, auth_headers, make_user, make_route, make_vehicle, make_gps_point
    ):
        route_a, route_b = await make_route(name="Route A"), await make_route(name="Route B")
        vehicle_a, vehicle_b = (
            await make_vehicle(code="BUS-001"),
            await make_vehicle(code="BUS-002"),
        )
        await make_user(
            email="a@test.com", password="password123", route=route_a, vehicle=vehicle_a
        )
        await make_user(
            email="b@test.com", password="password123", route=route_b, vehicle=vehicle_b
        )
        await make_gps_point(vehicle_a, lat="10.000000", lng="79.0", speed="50")
        await make_gps_point(vehicle_b, lat="20.000000", lng="79.0", speed="60")

        r = client.get(
            "/api/v1/me/vehicle/current", headers=auth_headers("b@test.com", "password123")
        )
        assert r.json()["vehicle_id"] == vehicle_b.id
        assert r.json()["lat"] == 20.0

    async def test_revoked_assignment_blinds_user(
        self, client, auth_headers, make_user, make_vehicle, make_gps_point, db
    ):
        """When admin unassigns (NULLs), the user loses all tracking access."""
        vehicle = await make_vehicle(code="BUS-001")
        user = await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        await make_gps_point(vehicle, lat="13.08", lng="80.27", speed="10")
        headers = auth_headers("u@test.com", "password123")
        assert client.get("/api/v1/me/vehicle/history", headers=headers).status_code == 200

        # Unassign via a fresh session: make_user's object is detached
        async with async_session_factory() as session:
            fresh = await session.get(User, user.id)
            fresh.route_id = None
            fresh.vehicle_id = None
            await session.commit()
        await db.rollback()  # drop any cached state in the fixture session

        r = client.get("/api/v1/me/vehicle/history", headers=headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "no_assignment"
