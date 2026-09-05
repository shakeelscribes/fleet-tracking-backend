"""User-scoped tracking reads (decision #14, #16).

Every function derives the vehicle from the caller's own assignment - there is
no path/query parameter that can address another user's vehicle, so cross-user
access is structurally impossible. Tests still verify the isolation end-to-end.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NoAssignmentError
from app.models import BusRoute, GPSPoint, User, Vehicle, VehicleCurrentLocation
from app.schemas.tracking import (
    AssignmentOut,
    HistoryOut,
    HistoryParams,
    HistoryPointOut,
    RoutePolylineOut,
    RouteSummary,
    VehicleLiveOut,
    VehicleSummary,
)

STALE_AFTER = timedelta(seconds=60)  # decision #16: no update for 60s => offline
MOVING_THRESHOLD_KMH = Decimal("5.0")  # decision #16: > 5 km/h => moving
DEFAULT_HISTORY_WINDOW = timedelta(hours=24)  # decision #14: default window 24h


def derive_status(
    recorded_at: datetime | None,
    speed: Decimal | float | None,
    now: datetime | None = None,
) -> Literal["moving", "idle", "offline"]:
    """Derived vehicle status (decision #16): moving / idle / offline."""
    if recorded_at is None:
        return "offline"
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    if now - recorded_at > STALE_AFTER:
        return "offline"
    speed_value = Decimal(str(speed)) if speed is not None else Decimal(0)
    return "moving" if speed_value > MOVING_THRESHOLD_KMH else "idle"


def _require_assignment(user: User) -> None:
    if user.route_id is None and user.vehicle_id is None:
        raise NoAssignmentError(
            "No route/vehicle assigned yet - contact your fleet administrator"
        )


async def get_assignment(db: AsyncSession, user: User) -> AssignmentOut:
    _require_assignment(user)
    route = await db.get(BusRoute, user.route_id) if user.route_id else None
    vehicle = await db.get(Vehicle, user.vehicle_id) if user.vehicle_id else None
    return AssignmentOut(
        route=RouteSummary.model_validate(route) if route else None,
        vehicle=VehicleSummary.model_validate(vehicle) if vehicle else None,
    )


async def get_route_polyline(db: AsyncSession, user: User) -> RoutePolylineOut:
    if user.route_id is None:
        raise NoAssignmentError("No route assigned yet - contact your fleet administrator")
    route = await db.get(BusRoute, user.route_id)
    if route is None:  # pragma: no cover - FK guarantees existence
        raise NoAssignmentError("Assigned route no longer exists")
    return RoutePolylineOut.model_validate(route)


async def get_current_location(db: AsyncSession, user: User) -> VehicleLiveOut:
    if user.vehicle_id is None:
        raise NoAssignmentError("No vehicle assigned yet - contact your fleet administrator")
    vehicle = await db.get(Vehicle, user.vehicle_id)
    if vehicle is None:  # pragma: no cover - FK guarantees existence
        raise NoAssignmentError("Assigned vehicle no longer exists")

    current = await db.get(VehicleCurrentLocation, user.vehicle_id)
    status = derive_status(
        current.recorded_at if current else None,
        current.speed if current else None,
    )
    return VehicleLiveOut(
        vehicle_id=vehicle.id,
        vehicle_code=vehicle.code,
        lat=float(current.lat) if current else None,
        lng=float(current.lng) if current else None,
        speed=float(current.speed) if current else None,
        recorded_at=current.recorded_at if current else None,
        status=status,
    )


async def get_history(db: AsyncSession, user: User, params: HistoryParams) -> HistoryOut:
    if user.vehicle_id is None:
        raise NoAssignmentError("No vehicle assigned yet - contact your fleet administrator")

    date_to = params.date_to or datetime.now(UTC)
    date_from = params.date_from or (date_to - DEFAULT_HISTORY_WINDOW)
    if date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=UTC)
    if date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=UTC)

    conditions = (
        GPSPoint.vehicle_id == user.vehicle_id,
        GPSPoint.recorded_at >= date_from,
        GPSPoint.recorded_at <= date_to,
    )
    total = await db.scalar(select(func.count()).select_from(GPSPoint).where(*conditions))
    result = await db.execute(
        select(GPSPoint)  # chronological order: ready for polyline drawing
        .where(*conditions)
        .order_by(GPSPoint.recorded_at.asc(), GPSPoint.id.asc())
        .limit(params.limit)
        .offset(params.offset)
    )
    points = [HistoryPointOut.model_validate(p) for p in result.scalars().all()]
    return HistoryOut(vehicle_id=user.vehicle_id, count=total or 0, points=points)
