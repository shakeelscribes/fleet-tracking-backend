"""User + assignment schemas (decision #7, #11, #12)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_admin: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_admin: bool
    route_id: int | None
    vehicle_id: int | None
    created_at: datetime


class AssignmentUpdate(BaseModel):
    """Assignment is a strict pair: both set, or both null to unassign (decision #11)."""

    route_id: int | None = None
    vehicle_id: int | None = None

    @model_validator(mode="after")
    def _pair_must_be_complete(self) -> "AssignmentUpdate":
        if (self.route_id is None) != (self.vehicle_id is None):
            raise ValueError(
                "route_id and vehicle_id must be set together, or both null to unassign"
            )
        return self
