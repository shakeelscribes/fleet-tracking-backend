"""Phase 6 acceptance: MQTT ingestion - payload parsing, handler persistence, discards.

No live broker needed (decision #17): the subscriber loop is thin I/O; everything
that matters is parse_topic / parse_payload / handle_gps_message, tested here.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import GPSPoint, Vehicle, VehicleCurrentLocation
from app.mqtt.handler import handle_gps_message, latest_fix
from app.mqtt.payload import parse_payload, parse_topic

pytestmark = pytest.mark.usefixtures("_fresh_schema")


def _fix(**overrides) -> str:
    base = {
        "vehicle_id": 1,
        "lat": 13.0827,
        "lng": 80.2707,
        "speed": 42.5,
        "timestamp": "2026-09-05T12:00:00Z",
    }
    return json.dumps({**base, **overrides})


# --- parse_topic --------------------------------------------------------------


class TestParseTopic:
    def test_valid_topic(self):
        assert parse_topic("fleet/7/gps") == 7

    def test_custom_prefix(self):
        assert parse_topic("demo/3/gps", prefix="demo") == 3

    @pytest.mark.parametrize(
        "topic",
        [
            "bus/7/gps",  # wrong prefix
            "fleet/7",  # too short
            "fleet/7/gps/extra",  # too long
            "fleet/seven/gps",  # non-numeric id
            "fleet/0/gps",  # id must be >= 1
            "fleet/7/loc",  # wrong leaf
            "",  # empty
        ],
    )
    def test_invalid_topics(self, topic):
        assert parse_topic(topic) is None


# --- parse_payload -------------------------------------------------------------


class TestParsePayload:
    def test_valid_payload(self):
        msg = parse_payload(_fix())
        assert msg is not None
        assert msg.vehicle_id == 1
        assert msg.lat == pytest.approx(13.0827)
        assert msg.timestamp.utcoffset() == timedelta(0)  # Z parsed as UTC

    def test_offset_timestamp_accepted(self):
        msg = parse_payload(_fix(timestamp="2026-09-05T17:30:00+05:30"))
        assert msg is not None
        assert msg.timestamp.utcoffset() == timedelta(hours=5, minutes=30)

    def test_extra_fields_ignored(self):
        assert parse_payload(_fix(extra_field="whatever")) is not None

    @pytest.mark.parametrize(
        "payload",
        [
            b"not json at all",
            b'{"vehicle_id": 1, "lat": 13.0,}',  # trailing comma
            b'["not", "an", "object"]',
            b"\xff\xfe binary garbage",
        ],
    )
    def test_broken_json_discarded(self, payload):
        assert parse_payload(payload) is None

    @pytest.mark.parametrize(
        "override",
        [
            {"lat": 95.0},  # > 90
            {"lat": -95.0},
            {"lng": 181.0},  # > 180
            {"speed": -1.0},  # negative
            {"speed": 999.0},  # absurd
            {"vehicle_id": 0},
            {"vehicle_id": -3},
        ],
    )
    def test_out_of_range_fields_discarded(self, override):
        assert parse_payload(_fix(**override)) is None

    def test_naive_timestamp_discarded(self):
        assert parse_payload(_fix(timestamp="2026-09-05T12:00:00")) is None

    def test_missing_timestamp_discarded(self):
        payload = {"vehicle_id": 1, "lat": 13.0, "lng": 80.0, "speed": 10}
        assert parse_payload(json.dumps(payload)) is None


# --- handle_gps_message ---------------------------------------------------------


class TestHandler:
    async def test_valid_fix_persists_history_and_current(self, make_vehicle):
        vehicle = await make_vehicle(code="BUS-001")
        message = parse_payload(_fix(vehicle_id=vehicle.id))
        assert message is not None

        async with async_session_factory() as session:
            assert await handle_gps_message(session, message) is True

        async with async_session_factory() as session:
            point = await latest_fix(session, vehicle.id)
            assert point is not None
            assert float(point.lat) == pytest.approx(13.0827)
            current = await session.get(VehicleCurrentLocation, vehicle.id)
            assert current is not None
            assert float(current.speed) == pytest.approx(42.5)

    async def test_second_fix_upserts_current_keeps_history(self, make_vehicle):
        vehicle = await make_vehicle(code="BUS-001")
        t0 = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(seconds=10)

        async with async_session_factory() as session:
            assert await handle_gps_message(
                session, parse_payload(_fix(vehicle_id=vehicle.id, timestamp=t0.isoformat()))
            )
            assert await handle_gps_message(
                session,
                parse_payload(
                    _fix(vehicle_id=vehicle.id, lat=13.09, timestamp=t1.isoformat())
                ),
            )

        async with async_session_factory() as session:
            current = await session.get(VehicleCurrentLocation, vehicle.id)
            assert float(current.lat) == pytest.approx(13.09)  # newest wins
            assert current.recorded_at == t1
            count = len((await session.execute(select(GPSPoint))).scalars().all())
            assert count == 2  # both fixes in history

    async def test_out_of_order_fix_does_not_regress_current(self, make_vehicle):
        vehicle = await make_vehicle(code="BUS-001")
        t0 = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)
        earlier = t0 - timedelta(seconds=5)

        async with async_session_factory() as session:
            await handle_gps_message(
                session, parse_payload(_fix(vehicle_id=vehicle.id, timestamp=t0.isoformat()))
            )
            await handle_gps_message(
                session,
                parse_payload(
                    _fix(vehicle_id=vehicle.id, lat=1.0, timestamp=earlier.isoformat())
                ),
            )

        async with async_session_factory() as session:
            current = await session.get(VehicleCurrentLocation, vehicle.id)
            assert current.recorded_at == t0  # older fix did not regress the live row
            assert float(current.lat) == pytest.approx(13.0827)

    async def test_unknown_vehicle_discarded(self):
        message = parse_payload(_fix(vehicle_id=999))
        assert message is not None
        async with async_session_factory() as session:
            assert await handle_gps_message(session, message) is False

    async def test_inactive_vehicle_discarded(self, make_vehicle):
        vehicle = await make_vehicle(code="BUS-DEAD")
        async with async_session_factory() as session:
            fresh = await session.get(Vehicle, vehicle.id)
            fresh.is_active = False
            await session.commit()

        message = parse_payload(_fix(vehicle_id=vehicle.id))
        async with async_session_factory() as session:
            assert await handle_gps_message(session, message) is False

    async def test_broken_payload_never_reaches_handler(self):
        # The parser is the gate: broken input yields None, handler is never called
        assert parse_payload(b"garbage{") is None


# --- End-to-end shape: ingestion feeds /me endpoints -----------------------------


class TestIngestionFeedsMeEndpoints:
    async def test_current_location_reflects_last_ingested_fix(
        self, client, auth_headers, make_user, make_route, make_vehicle
    ):
        route = await make_route(name="Route A")
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", route=route, vehicle=vehicle)

        t0 = datetime.now(UTC) - timedelta(seconds=30)
        async with async_session_factory() as session:
            await handle_gps_message(
                session,
                parse_payload(
                    _fix(
                        vehicle_id=vehicle.id,
                        lat=13.0827,
                        speed=42.5,
                        timestamp=t0.isoformat(),
                    )
                ),
            )

        r = client.get(
            "/api/v1/me/vehicle/current", headers=auth_headers("u@test.com", "password123")
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "moving"  # fresh (< 60s) + fast (> 5 km/h)
        assert body["lat"] == pytest.approx(13.0827)
        assert body["vehicle_code"] == "BUS-001"

    async def test_stale_fix_reports_offline(
        self, client, auth_headers, make_user, make_route, make_vehicle
    ):
        route = await make_route(name="Route A")
        vehicle = await make_vehicle(code="BUS-001")
        await make_user(email="u@test.com", password="password123", route=route, vehicle=vehicle)

        t0 = datetime.now(UTC) - timedelta(seconds=120)  # > staleness threshold
        async with async_session_factory() as session:
            await handle_gps_message(
                session,
                parse_payload(
                    _fix(vehicle_id=vehicle.id, speed=42.5, timestamp=t0.isoformat())
                ),
            )

        r = client.get(
            "/api/v1/me/vehicle/current", headers=auth_headers("u@test.com", "password123")
        )
        assert r.status_code == 200
        assert r.json()["status"] == "offline"

    async def test_vehicle_still_queryable_after_ingestion(self, make_vehicle):
        vehicle = await make_vehicle(code="BUS-001")
        async with async_session_factory() as session:
            assert await session.get(Vehicle, vehicle.id) is not None
