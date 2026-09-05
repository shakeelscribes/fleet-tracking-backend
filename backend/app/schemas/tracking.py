"""User-facing tracking schemas (decision #14, #16)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.route import Waypoint

# --- Assignment --------------------------------------------------------------


class RouteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class VehicleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class AssignmentOut(BaseModel):
    route: RouteSummary | None = None
    vehicle: VehicleSummary | None = None


# --- Route polyline ----------------------------------------------------------


class RoutePolylineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    waypoints: list[Waypoint]


# --- Live location -----------------------------------------------------------


class VehicleLiveOut(BaseModel):
    """Current location + derived status; nulls when nothing received yet."""

    vehicle_id: int
    vehicle_code: str
    lat: float | None = None
    lng: float | None = None
    speed: float | None = None  # km/h (decision #16)
    recorded_at: datetime | None = None
    status: Literal["moving", "idle", "offline"]


# --- History -----------------------------------------------------------------


class HistoryPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lat: float
    lng: float
    speed: float
    recorded_at: datetime


class HistoryOut(BaseModel):
    vehicle_id: int
    count: int
    points: list[HistoryPointOut]


class HistoryParams(BaseModel):
    """Query params for /me/vehicle/history (decision #14).

    Default window: last 24 hours. `limit` capped at 1000.
    """

    model_config = ConfigDict(populate_by_name=True)

    date_from: datetime | None = Field(default=None, alias="from")
    date_to: datetime | None = Field(default=None, alias="to")
    limit: int = Field(default=500, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
