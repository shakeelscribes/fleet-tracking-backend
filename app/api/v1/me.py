"""User-facing /me endpoints - strictly scoped to the caller's assignment (decision #12)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models import User
from app.schemas.tracking import (
    AssignmentOut,
    HistoryOut,
    HistoryParams,
    RoutePolylineOut,
    VehicleLiveOut,
)
from app.services import tracking_service

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/assignment", response_model=AssignmentOut)
async def my_assignment(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> AssignmentOut:
    """The caller's route + vehicle summary; 403 no_assignment when unassigned."""
    return await tracking_service.get_assignment(db, user)


@router.get("/route", response_model=RoutePolylineOut)
async def my_route(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> RoutePolylineOut:
    """Waypoints of the caller's assigned route (for map polyline rendering)."""
    return await tracking_service.get_route_polyline(db, user)


@router.get("/vehicle/current", response_model=VehicleLiveOut)
async def my_vehicle_current(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> VehicleLiveOut:
    """Latest known location of the caller's vehicle + derived status."""
    return await tracking_service.get_current_location(db, user)


@router.get("/vehicle/history", response_model=HistoryOut)
async def my_vehicle_history(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[HistoryParams, Query()],
) -> HistoryOut:
    """GPS history of the caller's vehicle (default window: last 24h)."""
    return await tracking_service.get_history(db, user, params)
