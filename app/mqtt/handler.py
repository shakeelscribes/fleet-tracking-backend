"""GPS message handling: valid fix -> gps_points insert + current-location upsert.

Failures are contained: an invalid message is logged and discarded (decision #15) -
it must never crash the subscriber or poison the DB session.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GPSPoint, Vehicle, VehicleCurrentLocation
from app.mqtt.payload import GPSMessage

logger = logging.getLogger("app.mqtt.handler")


async def handle_gps_message(db: AsyncSession, message: GPSMessage) -> bool:
    """Persist one validated fix. Returns True when stored, False when discarded."""
    vehicle = await db.get(Vehicle, message.vehicle_id)
    if vehicle is None:
        logger.warning("Discarding GPS fix: unknown vehicle_id=%s", message.vehicle_id)
        return False
    if not vehicle.is_active:
        logger.warning("Discarding GPS fix: vehicle %s is inactive", vehicle.code)
        return False

    recorded_at = message.timestamp
    db.add(
        GPSPoint(
            vehicle_id=message.vehicle_id,
            lat=message.lat,
            lng=message.lng,
            speed=message.speed,
            recorded_at=recorded_at,
        )
    )

    # Current location keeps the LATEST fix only (out-of-order delivery is common
    # with QoS 1); history keeps everything.
    current = await db.get(VehicleCurrentLocation, message.vehicle_id)
    if current is None:
        db.add(
            VehicleCurrentLocation(
                vehicle_id=message.vehicle_id,
                lat=message.lat,
                lng=message.lng,
                speed=message.speed,
                recorded_at=recorded_at,
            )
        )
    elif recorded_at > current.recorded_at:
        current.lat = message.lat
        current.lng = message.lng
        current.speed = message.speed
        current.recorded_at = recorded_at

    await db.commit()
    logger.debug(
        "Stored GPS fix vehicle_id=%s lat=%s lng=%s speed=%s",
        message.vehicle_id,
        message.lat,
        message.lng,
        message.speed,
    )
    return True


async def latest_fix(db: AsyncSession, vehicle_id: int) -> GPSPoint | None:
    """Helper for tests/diagnostics: newest history point of a vehicle."""
    result = await db.execute(
        select(GPSPoint)
        .where(GPSPoint.vehicle_id == vehicle_id)
        .order_by(GPSPoint.recorded_at.desc(), GPSPoint.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
