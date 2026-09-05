"""Phase 4 acceptance: admin API gating, CRUD, and assignment flows (decision #7)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models import GPSPoint, User


@pytest.fixture
def admin(make_user, auth_headers):
    """Async factory: create + log in a fresh admin, return bearer headers."""

    async def _admin(email: str = "admin@test.com") -> dict[str, str]:
        await make_user(email=email, password="password123", is_admin=True)
        return auth_headers(email, "password123")

    return _admin


# --- Gate enforcement --------------------------------------------------------


class TestAdminGate:
    async def test_missing_token_is_401(self, client):
        checks = [
            ("get", "/api/v1/admin/routes", None),
            ("post", "/api/v1/admin/routes", {}),
            ("get", "/api/v1/admin/users", None),
            ("put", "/api/v1/admin/users/1/assignment", {}),
            ("delete", "/api/v1/admin/vehicles/1", None),
        ]
        for method, path, json_body in checks:
            call = getattr(client, method)
            r = call(path, json=json_body) if json_body is not None else call(path)
            assert r.status_code == 401, f"{method.upper()} {path}"
            assert r.json()["error"]["code"] == "invalid_credentials"

    async def test_non_admin_is_403(self, client, make_user, auth_headers):
        await make_user(email="pleb@test.com", password="password123")
        headers = auth_headers("pleb@test.com", "password123")
        for path in ["/api/v1/admin/routes", "/api/v1/admin/vehicles", "/api/v1/admin/users"]:
            r = client.get(path, headers=headers)
            assert r.status_code == 403, path
            assert r.json()["error"]["code"] == "forbidden"


# --- Routes CRUD -------------------------------------------------------------


class TestRoutesCRUD:
    WAYPOINTS = [
        {"lat": 13.0827, "lng": 80.2707},
        {"lat": 13.0304, "lng": 80.2206},
        {"lat": 12.9900, "lng": 80.2200},
    ]

    async def test_create_get_list(self, client, admin):
        h = await admin()
        r = client.post(
            "/api/v1/admin/routes", headers=h, json={"name": "Route A", "waypoints": self.WAYPOINTS}
        )
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "Route A"
        assert len(body["waypoints"]) == 3

        got = client.get(f"/api/v1/admin/routes/{body['id']}", headers=h)
        assert got.status_code == 200
        listed = client.get("/api/v1/admin/routes", headers=h)
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    async def test_duplicate_name_409(self, client, admin):
        h = await admin()
        payload = {"name": "Route A", "waypoints": self.WAYPOINTS}
        client.post("/api/v1/admin/routes", headers=h, json=payload)
        r = client.post("/api/v1/admin/routes", headers=h, json=payload)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "route_name_taken"

    async def test_waypoint_bounds_422(self, client, admin):
        h = await admin()
        r = client.post(
            "/api/v1/admin/routes",
            headers=h,
            json={
                "name": "Bad Route",
                "waypoints": [{"lat": 95.0, "lng": 80.27}, {"lat": 13.0, "lng": 80.2}],
            },
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"

    async def test_get_missing_404(self, client, admin):
        h = await admin()
        r = client.get("/api/v1/admin/routes/999", headers=h)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "route_not_found"

    async def test_update_route(self, client, admin):
        h = await admin()
        route = client.post(
            "/api/v1/admin/routes", headers=h, json={"name": "Old", "waypoints": self.WAYPOINTS}
        ).json()
        r = client.patch(
            f"/api/v1/admin/routes/{route['id']}",
            headers=h,
            json={"name": "New", "waypoints": None},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "New"
        # waypoints untouched (None = not set)
        assert len(r.json()["waypoints"]) == 3

    async def test_delete_route_in_use_409(self, client, admin, make_user, make_route):
        h = await admin()
        route = await make_route(name="Busy")
        await make_user(email="u@test.com", password="password123", route=route)
        r = client.delete(f"/api/v1/admin/routes/{route.id}", headers=h)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "route_in_use"

    async def test_delete_route_free_204(self, client, admin):
        h = await admin()
        route = client.post(
            "/api/v1/admin/routes", headers=h, json={"name": "Doomed", "waypoints": self.WAYPOINTS}
        ).json()
        r = client.delete(f"/api/v1/admin/routes/{route['id']}", headers=h)
        assert r.status_code == 204
        assert client.get(f"/api/v1/admin/routes/{route['id']}", headers=h).status_code == 404


# --- Vehicles CRUD -----------------------------------------------------------


class TestVehiclesCRUD:
    async def test_create_get(self, client, admin):
        h = await admin()
        r = client.post(
            "/api/v1/admin/vehicles", headers=h, json={"code": "BUS-001", "name": "Adyar Express"}
        )
        assert r.status_code == 201
        body = r.json()
        assert body["code"] == "BUS-001"
        assert body["is_active"] is True

    async def test_duplicate_code_409(self, client, admin):
        h = await admin()
        payload = {"code": "BUS-001", "name": "One"}
        client.post("/api/v1/admin/vehicles", headers=h, json=payload)
        r = client.post("/api/v1/admin/vehicles", headers=h, json=payload)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "vehicle_code_taken"

    async def test_invalid_code_pattern_422(self, client, admin):
        h = await admin()
        r = client.post(
            "/api/v1/admin/vehicles", headers=h, json={"code": "BUS 001!", "name": "Bad"}
        )
        assert r.status_code == 422

    async def test_update_vehicle(self, client, admin, make_vehicle):
        h = await admin()
        vehicle = await make_vehicle(code="BUS-009")
        r = client.patch(
            f"/api/v1/admin/vehicles/{vehicle.id}", headers=h, json={"is_active": False}
        )
        assert r.status_code == 200
        assert r.json()["is_active"] is False

    async def test_delete_vehicle_assigned_409(self, client, admin, make_user, make_vehicle):
        h = await admin()
        vehicle = await make_vehicle(code="BUS-002")
        await make_user(email="u@test.com", password="password123", vehicle=vehicle)
        r = client.delete(f"/api/v1/admin/vehicles/{vehicle.id}", headers=h)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "vehicle_in_use"

    async def test_delete_vehicle_with_history_409(self, client, admin, make_vehicle, db):
        h = await admin()
        vehicle = await make_vehicle(code="BUS-003")
        db.add(
            GPSPoint(
                vehicle_id=vehicle.id,
                lat=Decimal("13.0827"),
                lng=Decimal("80.2707"),
                speed=Decimal("25.5"),
                recorded_at=datetime.now(UTC),
            )
        )
        await db.commit()
        r = client.delete(f"/api/v1/admin/vehicles/{vehicle.id}", headers=h)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "vehicle_in_use"


# --- Users CRUD --------------------------------------------------------------


class TestUsersCRUD:
    async def test_create_user_no_secret_leak(self, client, admin):
        h = await admin()
        r = client.post(
            "/api/v1/admin/users",
            headers=h,
            json={"email": "new@test.com", "password": "password123"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["email"] == "new@test.com"
        assert body["is_admin"] is False
        assert "password" not in body and "hashed_password" not in body

    async def test_duplicate_email_409(self, client, admin):
        h = await admin()
        payload = {"email": "dup@test.com", "password": "password123"}
        client.post("/api/v1/admin/users", headers=h, json=payload)
        r = client.post("/api/v1/admin/users", headers=h, json=payload)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "email_taken"

    async def test_update_user_password_takes_effect(self, client, admin):
        h = await admin()
        user = client.post(
            "/api/v1/admin/users",
            headers=h,
            json={"email": "pw@test.com", "password": "password123"},
        ).json()
        r = client.patch(
            f"/api/v1/admin/users/{user['id']}", headers=h, json={"password": "new-pass-123"}
        )
        assert r.status_code == 200
        login = client.post(
            "/api/v1/auth/login", json={"email": "pw@test.com", "password": "new-pass-123"}
        )
        assert login.status_code == 200

    async def test_delete_user(self, client, admin):
        h = await admin()
        user = client.post(
            "/api/v1/admin/users",
            headers=h,
            json={"email": "gone@test.com", "password": "password123"},
        ).json()
        assert client.delete(f"/api/v1/admin/users/{user['id']}", headers=h).status_code == 204
        assert client.get(f"/api/v1/admin/users/{user['id']}", headers=h).status_code == 404


# --- Assignment (graded core, decision #7/#11) --------------------------------


class TestAssignment:
    async def test_assign_then_read_back(
        self, client, admin, make_user, make_route, make_vehicle, db
    ):
        h = await admin()
        user = await make_user(email="driver@test.com")
        route = await make_route(name="Route A")
        vehicle = await make_vehicle(code="BUS-001")

        r = client.put(
            f"/api/v1/admin/users/{user.id}/assignment",
            headers=h,
            json={"route_id": route.id, "vehicle_id": vehicle.id},
        )
        assert r.status_code == 200
        assert r.json()["route_id"] == route.id
        assert r.json()["vehicle_id"] == vehicle.id

        fresh = await db.get(User, user.id)  # factory object lives in another session
        assert fresh.route_id == route.id
        assert fresh.vehicle_id == vehicle.id

    async def test_reassign(self, client, admin, make_user, make_route, make_vehicle):
        h = await admin()
        user = await make_user(email="driver@test.com")
        route1, route2 = await make_route(name="R1"), await make_route(name="R2")
        v1, v2 = await make_vehicle(code="BUS-001"), await make_vehicle(code="BUS-002")

        client.put(
            f"/api/v1/admin/users/{user.id}/assignment",
            headers=h,
            json={"route_id": route1.id, "vehicle_id": v1.id},
        )
        r = client.put(
            f"/api/v1/admin/users/{user.id}/assignment",
            headers=h,
            json={"route_id": route2.id, "vehicle_id": v2.id},
        )
        assert r.status_code == 200
        assert r.json()["route_id"] == route2.id

    async def test_unassign_with_nulls(self, client, admin, make_user, make_route, make_vehicle):
        h = await admin()
        user = await make_user(email="driver@test.com")
        route, vehicle = await make_route(name="R1"), await make_vehicle(code="BUS-001")
        client.put(
            f"/api/v1/admin/users/{user.id}/assignment",
            headers=h,
            json={"route_id": route.id, "vehicle_id": vehicle.id},
        )
        r = client.put(
            f"/api/v1/admin/users/{user.id}/assignment",
            headers=h,
            json={"route_id": None, "vehicle_id": None},
        )
        assert r.status_code == 200
        assert r.json()["route_id"] is None and r.json()["vehicle_id"] is None

    async def test_mixed_nulls_422(self, client, admin, make_user):
        h = await admin()
        user = await make_user(email="driver@test.com")
        r = client.put(
            f"/api/v1/admin/users/{user.id}/assignment",
            headers=h,
            json={"route_id": 1, "vehicle_id": None},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"

    async def test_missing_refs_404(self, client, admin, make_user, make_route):
        h = await admin()
        user = await make_user(email="driver@test.com")
        route = await make_route(name="R1")
        for payload in [
            {"route_id": 999, "vehicle_id": 1},
            {"route_id": route.id, "vehicle_id": 999},
        ]:
            r = client.put(
                f"/api/v1/admin/users/{user.id}/assignment", headers=h, json=payload
            )
            assert r.status_code == 404, payload
            assert r.json()["error"]["code"] in {"route_not_found", "vehicle_not_found"}

    async def test_missing_user_404(self, client, admin):
        h = await admin()
        r = client.put(
            "/api/v1/admin/users/999/assignment", headers=h, json={"route_id": 1, "vehicle_id": 1}
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "user_not_found"

    async def test_vehicle_exclusivity_409(
        self, client, admin, make_user, make_route, make_vehicle
    ):
        """Micro-decision: one vehicle serves exactly one user (demo integrity)."""
        h = await admin()
        u1, u2 = await make_user(email="a@test.com"), await make_user(email="b@test.com")
        vehicle = await make_vehicle(code="BUS-001")
        route_a = await make_route(name="Route A")
        route_b = await make_route(name="Route B")

        ok = client.put(
            f"/api/v1/admin/users/{u1.id}/assignment",
            headers=h,
            json={"route_id": route_a.id, "vehicle_id": vehicle.id},
        )
        assert ok.status_code == 200

        r = client.put(
            f"/api/v1/admin/users/{u2.id}/assignment",
            headers=h,
            json={"route_id": route_b.id, "vehicle_id": vehicle.id},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "vehicle_already_assigned"

    async def test_route_exclusivity_409(self, client, admin, make_user, make_route, make_vehicle):
        h = await admin()
        u1, u2 = await make_user(email="a@test.com"), await make_user(email="b@test.com")
        route = await make_route(name="Shared")
        v1, v2 = await make_vehicle(code="BUS-001"), await make_vehicle(code="BUS-002")

        client.put(
            f"/api/v1/admin/users/{u1.id}/assignment",
            headers=h,
            json={"route_id": route.id, "vehicle_id": v1.id},
        )
        r = client.put(
            f"/api/v1/admin/users/{u2.id}/assignment",
            headers=h,
            json={"route_id": route.id, "vehicle_id": v2.id},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "route_already_assigned"
