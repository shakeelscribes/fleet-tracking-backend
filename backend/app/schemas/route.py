"""Route schemas - waypoint validation guards the map polyline (decision #6)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Waypoint(BaseModel):
    lat: float = Field(ge=-90, le=90, description="Latitude in decimal degrees")
    lng: float = Field(ge=-180, le=180, description="Longitude in decimal degrees")


class RouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # A polyline needs at least two points
    waypoints: list[Waypoint] = Field(min_length=2, max_length=500)


class RouteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    waypoints: list[Waypoint] | None = Field(default=None, min_length=2, max_length=500)


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    waypoints: list[Waypoint]
    created_at: datetime
