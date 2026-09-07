"""Vehicle schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tracking import VehicleLiveOut

CODE_PATTERN = r"^[A-Za-z0-9-]+$"  # e.g. BUS-001


class VehicleCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True


class VehicleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=CODE_PATTERN)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    is_active: bool
    created_at: datetime


class AdminVehicleOut(BaseModel):
    """Vehicle with its live location for the admin fleet view.

    `current_location` is None until the vehicle's first GPS fix arrives;
    status is derived server-side with the same rule as /me endpoints.
    """

    id: int
    code: str
    name: str
    is_active: bool
    created_at: datetime
    current_location: VehicleLiveOut | None = None
