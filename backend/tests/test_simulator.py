"""Simulator tests: route-walking math + assignment loading (no broker needed)."""

from datetime import UTC, datetime

import pytest

from app.models import GPSPoint
from app.mqtt.payload import GPSMessage
from simulator.runner import _load_assignments
from simulator.walk import BusWalker, _haversine_m

# City Center to Airport (seed route 1): ~6-7 km end to end
ROUTE = [
    (13.0827, 80.2707),  # Chennai Central
    (13.0417, 80.2345),  # Kathipara
    (12.9941, 80.1709),  # Airport
]


def test_haversine_sane_distances():
    d = _haversine_m((13.0827, 80.2707), (13.0417, 80.2345))
    assert 4_500 < d < 9_000  # roughly 6.5 km across Chennai
    assert _haversine_m(ROUTE[0], ROUTE[0]) == 0.0


def test_walker_rejects_degenerate_routes():
    with pytest.raises(ValueError, match="2 waypoints"):
        BusWalker([(13.0, 80.0)])


def test_walker_total_length():
    w = BusWalker(ROUTE)
    assert w.total_m == pytest.approx(
        _haversine_m(ROUTE[0], ROUTE[1]) + _haversine_m(ROUTE[1], ROUTE[2]), rel=1e-9
    )


def test_walker_starts_at_first_waypoint():
    w = BusWalker(ROUTE, distance_m=0.0)
    assert w.position() == pytest.approx(ROUTE[0])


def test_walker_interpolates_mid_segment():
    w = BusWalker(ROUTE, distance_m=0.0)
    w.advance(36.0, 60.0)  # 36 km/h for 60 s = 600 m along the path
    lat, lng = w.position()
    (lat0, lng0), (lat1, lng1) = ROUTE[0], ROUTE[1]
    t = 600.0 / _haversine_m(ROUTE[0], ROUTE[1])
    assert lat == pytest.approx(lat0 + (lat1 - lat0) * t, abs=1e-9)
    assert lng == pytest.approx(lng0 + (lng1 - lng0) * t, abs=1e-9)


def test_walker_bounces_at_terminus():
    w = BusWalker(ROUTE, distance_m=0.0)
    w.advance(500.0, 3600.0)  # far past the end
    assert w.distance_m == w.total_m
    assert w.direction == -1
    assert w.position() == pytest.approx(ROUTE[-1])
    w.advance(50.0, 60.0)  # a modest step back along the path
    assert 0.0 < w.distance_m < w.total_m


def test_walker_never_below_origin():
    w = BusWalker(ROUTE, distance_m=10.0, direction=-1)
    w.advance(100.0, 3600.0)
    assert w.distance_m == 0.0
    assert w.direction == 1


def test_simulator_payloads_match_ingestion_contract():
    """Fixes the simulator generates must always pass the API's own validator."""
    fix = {
        "vehicle_id": 1,
        "lat": round(13.0827, 6),
        "lng": round(80.2707, 6),
        "speed": round(28.4, 1),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    msg = GPSMessage(**fix)  # would raise on contract drift
    assert msg.vehicle_id == 1


async def test_load_assignments_joins_route_and_vehicle(db, make_user, make_route, make_vehicle):
    route = await make_route()
    vehicle = await make_vehicle()
    await make_user(email="sim@fleet.com", route=route, vehicle=vehicle)
    await make_user(email="idle@fleet.com")  # unassigned -> excluded

    rows = await _load_assignments()
    assert len(rows) == 1
    assert rows[0]["vehicle_id"] == vehicle.id
    assert len(rows[0]["waypoints"]) >= 2
    assert all(isinstance(p, tuple) and len(p) == 2 for p in rows[0]["waypoints"])


async def test_end_to_end_fix_persists_like_the_api_pipeline(
    db, make_user, make_route, make_vehicle
):
    """A simulated fix, run through the real handler, lands in gps_points."""
    from app.mqtt.handler import handle_gps_message

    route = await make_route()
    vehicle = await make_vehicle()
    await make_user(email="e2e@fleet.com", route=route, vehicle=vehicle)

    fix = GPSMessage(
        vehicle_id=vehicle.id,
        lat=13.0827,
        lng=80.2707,
        speed=31.5,
        timestamp=datetime.now(UTC),
    )
    async with db.begin():
        await handle_gps_message(db, fix)

    point = await db.get(GPSPoint, 1)
    assert point is not None
    assert float(point.speed) == pytest.approx(31.5)
