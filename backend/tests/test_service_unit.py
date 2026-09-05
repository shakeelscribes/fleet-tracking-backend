"""Service-layer unit tests (Phase 8 coverage audit).

These call the service functions directly instead of through the HTTP layer:
- business rules (conflicts, exclusivity, guards) are asserted with precision
- py.test-cov + anyio portal threads under-record async callees on this setup,
  so direct calls also keep the coverage report honest.

Pure-unit tests (no DB) for token edge cases live here too.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime

import jwt
import pytest
from sqlalchemy import func, select

from app.core import security
from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    CredentialsError,
    NoAssignmentError,
    NotFoundError,
    _unhandled_error_handler,
)
from app.models import GPSPoint, VehicleCurrentLocation
from app.mqtt import client as mqtt_client
from app.schemas.route import RouteCreate, RouteUpdate
from app.schemas.tracking import HistoryParams
from app.schemas.user import AssignmentUpdate, UserCreate, UserUpdate
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.services import auth_service, tracking_service
from app.services import fleet_admin_service as svc

pytestmark = pytest.mark.usefixtures("_fresh_schema")

WPS = [{"lat": 13.0827, "lng": 80.2707}, {"lat": 12.9941, "lng": 80.1709}]


def _route(name: str = "R1") -> RouteCreate:
    return RouteCreate(name=name, waypoints=WPS)


# --- Routes ------------------------------------------------------------------


class TestRouteService:
    async def test_create_route_ok(self, db):
        route = await svc.create_route(db, _route("A to B"))
        assert route.id is not None
        assert route.waypoints == WPS

    async def test_create_route_duplicate_name_conflict(self, db):
        await svc.create_route(db, _route("Dup"))
        with pytest.raises(ConflictError) as ei:
            await svc.create_route(db, _route("Dup"))
        assert ei.value.code == "route_name_taken"

    async def test_list_routes_ordered(self, db):
        await svc.create_route(db, _route("B"))
        await svc.create_route(db, _route("A"))
        routes = await svc.list_routes(db)
        assert [r.name for r in routes] == ["B", "A"]  # insertion (id) order

    async def test_get_route_not_found(self, db):
        with pytest.raises(NotFoundError) as ei:
            await svc.get_route(db, 4242)
        assert ei.value.code == "route_not_found"

    async def test_update_route_rename(self, db):
        route = await svc.create_route(db, _route("Old"))
        updated = await svc.update_route(db, route, RouteUpdate(name="New"))
        assert updated.name == "New"

    async def test_update_route_rename_to_same_name_is_not_a_conflict(self, db):
        route = await svc.create_route(db, _route("Same"))
        updated = await svc.update_route(db, route, RouteUpdate(name="Same"))
        assert updated.name == "Same"

    async def test_update_route_rename_to_taken_conflict(self, db):
        await svc.create_route(db, _route("Taken"))
        route = await svc.create_route(db, _route("Mine"))
        with pytest.raises(ConflictError) as ei:
            await svc.update_route(db, route, RouteUpdate(name="Taken"))
        assert ei.value.code == "route_name_taken"

    async def test_update_route_waypoints_only_keeps_name(self, db):
        route = await svc.create_route(db, _route("Keep"))
        wps2 = [{"lat": 13.1, "lng": 80.1}, {"lat": 13.2, "lng": 80.2}]
        updated = await svc.update_route(db, route, RouteUpdate(waypoints=wps2))
        assert updated.name == "Keep" and updated.waypoints == wps2

    async def test_delete_route_ok(self, db):
        route = await svc.create_route(db, _route("Doomed"))
        await svc.delete_route(db, route)
        assert await db.get(type(route), route.id) is None

    async def test_delete_route_in_use_conflict(self, db, make_user, make_route):
        route = await make_route(name="Busy")
        await make_user(email="u1@fleet.com", route=route)
        with pytest.raises(ConflictError) as ei:
            await svc.delete_route(db, route)
        assert ei.value.code == "route_in_use"


# --- Vehicles ----------------------------------------------------------------


class TestVehicleService:
    async def test_create_vehicle_ok(self, db):
        vehicle = await svc.create_vehicle(
            db, VehicleCreate(code="BUS-X", name="X", is_active=False)
        )
        assert vehicle.id is not None and vehicle.is_active is False

    async def test_create_vehicle_duplicate_code_conflict(self, db):
        await svc.create_vehicle(db, VehicleCreate(code="BUS-1", name="1"))
        with pytest.raises(ConflictError) as ei:
            await svc.create_vehicle(db, VehicleCreate(code="BUS-1", name="other"))
        assert ei.value.code == "vehicle_code_taken"

    async def test_list_vehicles(self, db):
        await svc.create_vehicle(db, VehicleCreate(code="BUS-1", name="1"))
        await svc.create_vehicle(db, VehicleCreate(code="BUS-2", name="2"))
        assert [v.code for v in await svc.list_vehicles(db)] == ["BUS-1", "BUS-2"]

    async def test_get_vehicle_not_found(self, db):
        with pytest.raises(NotFoundError) as ei:
            await svc.get_vehicle(db, 999)
        assert ei.value.code == "vehicle_not_found"

    async def test_update_vehicle_code_and_flags(self, db):
        vehicle = await svc.create_vehicle(db, VehicleCreate(code="BUS-A", name="A"))
        updated = await svc.update_vehicle(
            db, vehicle, VehicleUpdate(code="BUS-B", name="B", is_active=False)
        )
        assert (updated.code, updated.name, updated.is_active) == ("BUS-B", "B", False)

    async def test_update_vehicle_code_to_same_not_a_conflict(self, db):
        vehicle = await svc.create_vehicle(db, VehicleCreate(code="BUS-C", name="C"))
        updated = await svc.update_vehicle(db, vehicle, VehicleUpdate(code="BUS-C"))
        assert updated.code == "BUS-C"

    async def test_update_vehicle_code_to_taken_conflict(self, db):
        await svc.create_vehicle(db, VehicleCreate(code="BUS-T", name="T"))
        vehicle = await svc.create_vehicle(db, VehicleCreate(code="BUS-M", name="M"))
        with pytest.raises(ConflictError) as ei:
            await svc.update_vehicle(db, vehicle, VehicleUpdate(code="BUS-T"))
        assert ei.value.code == "vehicle_code_taken"

    async def test_delete_vehicle_ok(self, db):
        vehicle = await svc.create_vehicle(db, VehicleCreate(code="BUS-D", name="D"))
        await svc.delete_vehicle(db, vehicle)
        assert await db.get(type(vehicle), vehicle.id) is None

    async def test_delete_vehicle_assigned_conflict(self, db, make_user, make_vehicle):
        vehicle = await make_vehicle(code="BUS-U")
        await make_user(email="driver@fleet.com", vehicle=vehicle)
        with pytest.raises(ConflictError) as ei:
            await svc.delete_vehicle(db, vehicle)
        assert ei.value.code == "vehicle_in_use"

    async def test_delete_vehicle_with_gps_history_conflict(self, db, make_vehicle, make_gps_point):
        vehicle = await make_vehicle(code="BUS-G")
        await make_gps_point(vehicle=vehicle)
        with pytest.raises(ConflictError) as ei:
            await svc.delete_vehicle(db, vehicle)
        assert ei.value.code == "vehicle_in_use"

    async def test_delete_vehicle_with_current_row_conflict(self, db, make_vehicle, make_gps_point):
        vehicle = await make_vehicle(code="BUS-L")
        await make_gps_point(vehicle=vehicle, current=False)  # history only
        # simulate a stray current-location row with no points: delete history first
        await db.execute(GPSPoint.__table__.delete())
        db.add(
            VehicleCurrentLocation(
                vehicle_id=vehicle.id, lat=13.0, lng=80.0, speed=1.0, recorded_at=datetime.now(UTC)
            )
        )
        await db.commit()
        with pytest.raises(ConflictError) as ei:
            await svc.delete_vehicle(db, vehicle)
        assert ei.value.code == "vehicle_in_use"


# --- Users -------------------------------------------------------------------


class TestUserService:
    async def test_create_user_ok_hashes_password(self, db):
        user = await svc.create_user(
            db, UserCreate(email="new@fleet.com", password="supersecret1")
        )
        assert user.is_admin is False
        assert user.hashed_password != "supersecret1"
        assert security.verify_password("supersecret1", user.hashed_password)

    async def test_create_user_admin_flag(self, db):
        user = await svc.create_user(
            db, UserCreate(email="boss@fleet.com", password="supersecret1", is_admin=True)
        )
        assert user.is_admin is True

    async def test_create_user_duplicate_email_conflict(self, db):
        data = UserCreate(email="dup@fleet.com", password="supersecret1")
        await svc.create_user(db, data)
        with pytest.raises(ConflictError) as ei:
            await svc.create_user(db, data)
        assert ei.value.code == "email_taken"

    async def test_list_users_ordered(self, db):
        await svc.create_user(db, UserCreate(email="b@fleet.com", password="supersecret1"))
        await svc.create_user(db, UserCreate(email="a@fleet.com", password="supersecret1"))
        assert [u.email for u in await svc.list_users(db)] == ["b@fleet.com", "a@fleet.com"]

    async def test_get_user_not_found(self, db):
        with pytest.raises(NotFoundError) as ei:
            await svc.get_user(db, 31337)
        assert ei.value.code == "user_not_found"

    async def test_update_user_email(self, db):
        user = await svc.create_user(
            db, UserCreate(email="old@fleet.com", password="supersecret1")
        )
        updated = await svc.update_user(db, user, UserUpdate(email="renamed@fleet.com"))
        assert updated.email == "renamed@fleet.com"

    async def test_update_user_email_to_same_not_a_conflict(self, db):
        user = await svc.create_user(
            db, UserCreate(email="same@fleet.com", password="supersecret1")
        )
        updated = await svc.update_user(db, user, UserUpdate(email="same@fleet.com"))
        assert updated.email == "same@fleet.com"

    async def test_update_user_email_to_taken_conflict(self, db):
        await svc.create_user(db, UserCreate(email="t@fleet.com", password="supersecret1"))
        user = await svc.create_user(db, UserCreate(email="m@fleet.com", password="supersecret1"))
        with pytest.raises(ConflictError) as ei:
            await svc.update_user(db, user, UserUpdate(email="t@fleet.com"))
        assert ei.value.code == "email_taken"

    async def test_update_user_password_rehash(self, db):
        user = await svc.create_user(
            db, UserCreate(email="pw@fleet.com", password="oldpassword1")
        )
        await svc.update_user(db, user, UserUpdate(password="newpassword2"))
        assert not security.verify_password("oldpassword1", user.hashed_password)
        assert security.verify_password("newpassword2", user.hashed_password)

    async def test_update_user_promote_admin(self, db):
        user = await svc.create_user(
            db, UserCreate(email="promo@fleet.com", password="supersecret1")
        )
        updated = await svc.update_user(db, user, UserUpdate(is_admin=True))
        assert updated.is_admin is True

    async def test_delete_user_ok(self, db):
        user = await svc.create_user(
            db, UserCreate(email="gone@fleet.com", password="supersecret1")
        )
        await svc.delete_user(db, user)
        assert await db.get(type(user), user.id) is None


# --- Assignment (the graded core) ---------------------------------------------


class TestSetAssignment:
    async def test_assign_ok(self, db, make_route, make_vehicle, make_user):
        route, vehicle = await make_route(name="R"), await make_vehicle(code="BUS-A")
        user = await make_user(email="u@fleet.com")
        updated = await svc.set_assignment(
            db, user.id, AssignmentUpdate(route_id=route.id, vehicle_id=vehicle.id)
        )
        assert (updated.route_id, updated.vehicle_id) == (route.id, vehicle.id)

    async def test_unassign_both_null(self, db, make_route, make_vehicle, make_user):
        route, vehicle = await make_route(name="R2"), await make_vehicle(code="BUS-B")
        user = await make_user(email="u2@fleet.com", route=route, vehicle=vehicle)
        updated = await svc.set_assignment(db, user.id, AssignmentUpdate())
        assert updated.route_id is None and updated.vehicle_id is None

    async def test_reassign_releases_previous_route_and_vehicle(
        self, db, make_route, make_vehicle, make_user
    ):
        r1, v1 = await make_route(name="R-1"), await make_vehicle(code="BUS-1")
        r2, v2 = await make_route(name="R-2"), await make_vehicle(code="BUS-2")
        user = await make_user(email="swap@fleet.com", route=r1, vehicle=v1)
        await svc.set_assignment(db, user.id, AssignmentUpdate(route_id=r2.id, vehicle_id=v2.id))
        # r1/v1 are now free: another user can take them
        other = await make_user(email="other@fleet.com")
        ok = await svc.set_assignment(
            db, other.id, AssignmentUpdate(route_id=r1.id, vehicle_id=v1.id)
        )
        assert (ok.route_id, ok.vehicle_id) == (r1.id, v1.id)

    async def test_self_reassignment_of_same_pair_ok(self, db, make_route, make_vehicle, make_user):
        route, vehicle = await make_route(name="R3"), await make_vehicle(code="BUS-C")
        user = await make_user(email="self@fleet.com", route=route, vehicle=vehicle)
        updated = await svc.set_assignment(
            db, user.id, AssignmentUpdate(route_id=route.id, vehicle_id=vehicle.id)
        )
        assert updated.route_id == route.id

    async def test_route_taken_conflict(self, db, make_route, make_vehicle, make_user):
        route = await make_route(name="Contested")
        await make_user(email="owner@fleet.com", route=route)
        other = await make_user(email="other2@fleet.com")
        vehicle = await make_vehicle(code="BUS-V")
        with pytest.raises(ConflictError) as ei:
            await svc.set_assignment(
                db, other.id, AssignmentUpdate(route_id=route.id, vehicle_id=vehicle.id)
            )
        assert ei.value.code == "route_already_assigned"

    async def test_vehicle_taken_conflict(self, db, make_route, make_vehicle, make_user):
        vehicle = await make_vehicle(code="BUS-W")
        await make_user(email="owner2@fleet.com", vehicle=vehicle)
        other = await make_user(email="other3@fleet.com")
        route = await make_route(name="Free")
        with pytest.raises(ConflictError) as ei:
            await svc.set_assignment(
                db, other.id, AssignmentUpdate(route_id=route.id, vehicle_id=vehicle.id)
            )
        assert ei.value.code == "vehicle_already_assigned"

    async def test_assignment_missing_route_404(self, db, make_vehicle, make_user):
        vehicle = await make_vehicle(code="BUS-NR")
        user = await make_user(email="nr@fleet.com")
        with pytest.raises(NotFoundError):
            await svc.set_assignment(
                db, user.id, AssignmentUpdate(route_id=777, vehicle_id=vehicle.id)
            )

    async def test_assignment_missing_vehicle_404(self, db, make_route, make_user):
        route = await make_route(name="NV")
        user = await make_user(email="nv@fleet.com")
        with pytest.raises(NotFoundError):
            await svc.set_assignment(
                db, user.id, AssignmentUpdate(route_id=route.id, vehicle_id=888)
            )


# --- auth_service --------------------------------------------------------------


class TestAuthService:
    async def test_authenticate_user_ok(self, db, make_user):
        await make_user(email="auth@fleet.com", password="rightpass1")
        user = await auth_service.authenticate_user(db, "auth@fleet.com", "rightpass1")
        assert user.email == "auth@fleet.com"

    async def test_authenticate_user_unknown_email(self, db):
        with pytest.raises(CredentialsError):
            await auth_service.authenticate_user(db, "ghost@fleet.com", "whatever1")

    async def test_authenticate_user_wrong_password(self, db, make_user):
        await make_user(email="real@fleet.com", password="rightpass1")
        with pytest.raises(CredentialsError):
            await auth_service.authenticate_user(db, "real@fleet.com", "wrongpass1")

    async def test_issue_token_pair_shape(self, make_user):
        user = await make_user(email="tok@fleet.com")
        pair = auth_service.issue_token_pair(user)
        assert security.decode_token(pair.access_token, expected_type="access") == user.id
        assert security.decode_token(pair.refresh_token, expected_type="refresh") == user.id
        assert pair.expires_in == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    async def test_refresh_token_pair_ok(self, db, make_user):
        user = await make_user(email="rf@fleet.com")
        old = auth_service.issue_token_pair(user)
        fresh = await auth_service.refresh_token_pair(db, old.refresh_token)
        assert security.decode_token(fresh.access_token, expected_type="access") == user.id

    async def test_refresh_token_pair_deleted_user(self, db, make_user):
        user = await make_user(email="gone2@fleet.com")
        token = security.create_refresh_token(user.id)
        await db.delete(user)
        await db.commit()
        with pytest.raises(CredentialsError):
            await auth_service.refresh_token_pair(db, token)


# --- tracking_service.get_history edge branches --------------------------------


class TestGetHistoryBranches:
    async def test_unassigned_user_raises_no_assignment(self, db, make_user):
        user = await make_user(email="nohist@fleet.com")
        with pytest.raises(NoAssignmentError, match="No vehicle assigned"):
            await tracking_service.get_history(db, user, HistoryParams())

    async def test_naive_datetimes_are_treated_as_utc(
        self, db, make_user, make_vehicle, make_gps_point
    ):
        vehicle = await make_vehicle(code="BUS-H")
        user = await make_user(email="hist@fleet.com", vehicle=vehicle)
        await make_gps_point(vehicle=vehicle)
        params = HistoryParams(
            date_from=datetime(2020, 1, 1), date_to=datetime(2030, 1, 1)
        )
        out = await tracking_service.get_history(db, user, params)
        assert out.count == 1 and len(out.points) == 1

    async def test_empty_window_zero_count(self, db, make_user, make_vehicle):
        vehicle = await make_vehicle(code="BUS-E")
        user = await make_user(email="empty@fleet.com", vehicle=vehicle)
        out = await tracking_service.get_history(db, user, HistoryParams())
        assert out.count == 0 and out.points == []

    async def test_default_window_includes_recent_points(
        self, db, make_user, make_vehicle, make_gps_point
    ):
        vehicle = await make_vehicle(code="BUS-R")
        user = await make_user(email="recent@fleet.com", vehicle=vehicle)
        await make_gps_point(vehicle=vehicle)  # recorded_at=now
        out = await tracking_service.get_history(db, user, HistoryParams())  # no from/to
        assert out.count == 1


# --- pure units: token edge cases & error plumbing ------------------------------


class TestTokenEdgeCases:
    def test_decode_token_malformed_subject(self):
        token = jwt.encode({"type": "access"}, settings.JWT_SECRET_KEY, algorithm="HS256")
        with pytest.raises(CredentialsError, match="Malformed token subject"):
            security.decode_token(token, expected_type="access")

    def test_decode_token_wrong_type(self):
        token = security.create_access_token(1)
        with pytest.raises(CredentialsError, match="Expected a refresh token"):
            security.decode_token(token, expected_type="refresh")

    def test_app_error_default_code_used_when_none_given(self):
        err = ConflictError("plain message")  # no code kwarg -> class default
        assert err.code == "conflict"

    def test_unhandled_error_handler_returns_500_envelope(self):
        response = _unhandled_error_handler(None, RuntimeError("boom"))
        assert response.status_code == 500
        assert json.loads(response.body)["error"]["code"] == "internal_error"


# --- mqtt.client pure parts ----------------------------------------------------


class TestMqttClientUnit:
    async def test_subscription_topic_format(self):
        assert mqtt_client._subscription_topic() == f"{settings.MQTT_TOPIC_PREFIX}/+/gps"

    async def test_process_message_bad_topic_discards(self, db):
        await mqtt_client._process_message("garbage/nonsense", json.dumps({"x": 1}).encode())
        assert await db.scalar(select(func.count()).select_from(GPSPoint)) == 0

    async def test_process_message_invalid_payload_discards(self, db, make_vehicle):
        vehicle = await make_vehicle(code="BUS-P")
        await mqtt_client._process_message(f"fleet/{vehicle.id}/gps", b"not json")
        assert await db.scalar(select(func.count()).select_from(GPSPoint)) == 0

    async def test_process_message_unknown_vehicle_discards(self, db):
        payload = {
            "vehicle_id": 999, "lat": 13.0, "lng": 80.0,
            "speed": 5.0, "timestamp": "2026-01-01T00:00:00Z",
        }
        await mqtt_client._process_message("fleet/999/gps", json.dumps(payload).encode())
        assert await db.scalar(select(func.count()).select_from(GPSPoint)) == 0

    async def test_process_message_topic_payload_mismatch_discards(self, db, make_vehicle):
        vehicle = await make_vehicle(code="BUS-Z")
        payload = {
            "vehicle_id": vehicle.id + 1, "lat": 13.0, "lng": 80.0,
            "speed": 5.0, "timestamp": "2026-01-01T00:00:00Z",
        }
        await mqtt_client._process_message(
            f"fleet/{vehicle.id}/gps", json.dumps(payload).encode()
        )
        assert await db.scalar(select(func.count()).select_from(GPSPoint)) == 0

    async def test_process_message_happy_path_stores_fix(self, db, make_vehicle):
        vehicle = await make_vehicle(code="BUS-OK")
        payload = {
            "vehicle_id": vehicle.id, "lat": 13.05, "lng": 80.24,
            "speed": 31.0, "timestamp": "2026-01-01T00:00:00Z",
        }
        await mqtt_client._process_message(
            f"fleet/{vehicle.id}/gps", json.dumps(payload).encode()
        )
        assert await db.scalar(select(func.count()).select_from(GPSPoint)) == 1


# --- lifespan MQTT branch (no broker needed) ------------------------------------


class TestLifespanMqttBranch:
    def test_mqtt_enabled_task_started_and_cancelled(self, monkeypatch):
        from app import main as app_main

        started = asyncio.Event()
        stopped = asyncio.Event()

        async def fake_subscriber():
            started.set()
            try:
                await asyncio.Event().wait()  # forever until cancelled
            except asyncio.CancelledError:
                stopped.set()
                raise

        monkeypatch.setattr(app_main, "mqtt_subscriber_task", fake_subscriber)
        monkeypatch.setattr(app_main.settings, "MQTT_ENABLED", True)
        from fastapi.testclient import TestClient

        with TestClient(app_main.app):
            assert started.is_set()
        assert stopped.is_set()  # lifespan awaited the cancelled task


# --- seed CLI -------------------------------------------------------------------


class TestSeedCli:
    def test_main_prints_summary(self, monkeypatch, capsys):
        from app import seed as seed_module

        monkeypatch.setattr(sys, "argv", ["app.seed"])
        seed_module.main()
        out = capsys.readouterr().out
        assert "seeded:" in out
        assert "password123" in out
