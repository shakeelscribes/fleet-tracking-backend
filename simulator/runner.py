"""Simulator loop: DB assignments -> BusWalkers -> MQTT publishes.

Runs in two modes (decision #22):
- standalone process: ``python -m simulator`` / compose ``sim`` profile
- in-process task: lifespan spawns it when ``SIMULATOR_ENABLED=true`` (cloud demo,
  where there is no second container to run it)
"""

import asyncio
import json
import logging
import random
from datetime import UTC, datetime
from typing import Any

from aiomqtt import Client
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_factory
from app.models import BusRoute, User, Vehicle
from app.mqtt.client import mqtt_client_kwargs
from app.mqtt.payload import GPSMessage
from simulator.walk import BusWalker

logger = logging.getLogger("app.simulator")

# Per-bus cruising speed band (km/h); each tick jitters around the base and
# occasionally idles at a "bus stop".
SPEED_RANGE = (18.0, 42.0)
HALT_PROBABILITY = 0.05


async def _load_assignments() -> list[dict[str, Any]]:
    """Assigned driver rows joined with their route polyline and vehicle."""
    stmt = (
        select(User.id, Vehicle.id, BusRoute.waypoints)
        .join(Vehicle, User.vehicle_id == Vehicle.id)
        .join(BusRoute, User.route_id == BusRoute.id)
        .where(User.route_id.is_not(None), User.vehicle_id.is_not(None))
        .distinct()
    )
    async with async_session_factory() as session:
        rows = (await session.execute(stmt)).all()
    return [
        {"vehicle_id": vehicle_id, "waypoints": [(w["lat"], w["lng"]) for w in waypoints]}
        for _, vehicle_id, waypoints in rows
    ]


def _next_speed(base: float) -> float:
    if random.random() < HALT_PROBABILITY:
        return 0.0  # waiting at a stop -> shows as "idle" in the API
    return max(0.0, base + random.uniform(-6.0, 6.0))


async def run_simulator(stop: asyncio.Event | None = None) -> None:
    """Publish one fix per assigned vehicle every SIMULATOR_INTERVAL_SECONDS.

    Args:
        stop: optional event; set it to end the loop gracefully (lifespan mode).
    """
    interval = settings.SIMULATOR_INTERVAL_SECONDS
    assignments = await _load_assignments()
    if not assignments:
        logger.warning("Simulator found no assigned vehicles - nothing to publish")
        return

    walkers = [
        (BusWalker(a["waypoints"], distance_m=random.uniform(0, 500)), a["vehicle_id"])
        for a in assignments
    ]
    bases = {vid: random.uniform(*SPEED_RANGE) for _, vid in walkers}
    logger.info(
        "Simulator publishing for %d vehicle(s) every %ss to %s:%s",
        len(walkers),
        interval,
        settings.MQTT_HOST,
        settings.MQTT_PORT,
    )

    while stop is None or not stop.is_set():
        async with Client(
            settings.MQTT_HOST,
            port=settings.MQTT_PORT,
            username=settings.MQTT_USERNAME or None,
            password=settings.MQTT_PASSWORD or None,
            **mqtt_client_kwargs(),
        ) as client:
            while stop is None or not stop.is_set():
                for walker, vid in walkers:
                    speed = _next_speed(bases[vid])
                    walker.advance(speed, interval)
                    lat, lng = walker.position()
                    fix = {
                        "vehicle_id": vid,
                        "lat": round(lat, 6),
                        "lng": round(lng, 6),
                        "speed": round(speed, 1),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    GPSMessage(**fix)  # contract check: our own payloads must always validate
                    await client.publish(
                        f"{settings.MQTT_TOPIC_PREFIX}/{vid}/gps",
                        json.dumps(fix),
                        qos=1,
                    )
                if stop is None:  # standalone mode: plain tick
                    await asyncio.sleep(interval)
                else:  # in-process mode: wake early on graceful stop
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=interval)
                    except TimeoutError:
                        pass
