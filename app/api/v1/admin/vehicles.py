"""Admin vehicle management."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.vehicle import VehicleCreate, VehicleOut, VehicleUpdate
from app.services import fleet_admin_service as svc

router = APIRouter(prefix="/vehicles", tags=["admin:vehicles"])


@router.post("", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(body: VehicleCreate, db: AsyncSession = Depends(get_db)):
    return await svc.create_vehicle(db, body)


@router.get("", response_model=list[VehicleOut])
async def list_vehicles(db: AsyncSession = Depends(get_db)):
    return await svc.list_vehicles(db)


@router.get("/{vehicle_id}", response_model=VehicleOut)
async def get_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    return await svc.get_vehicle(db, vehicle_id)


@router.patch("/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(vehicle_id: int, body: VehicleUpdate, db: AsyncSession = Depends(get_db)):
    vehicle = await svc.get_vehicle(db, vehicle_id)
    return await svc.update_vehicle(db, vehicle, body)


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)) -> None:
    vehicle = await svc.get_vehicle(db, vehicle_id)
    await svc.delete_vehicle(db, vehicle)
