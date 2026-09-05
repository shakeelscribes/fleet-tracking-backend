"""Admin route management."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models import BusRoute
from app.schemas.route import RouteCreate, RouteOut, RouteUpdate
from app.services import fleet_admin_service as svc

router = APIRouter(prefix="/routes", tags=["admin:routes"])


@router.post("", response_model=RouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(body: RouteCreate, db: AsyncSession = Depends(get_db)) -> BusRoute:
    return await svc.create_route(db, body)


@router.get("", response_model=list[RouteOut])
async def list_routes(db: AsyncSession = Depends(get_db)):
    return await svc.list_routes(db)


@router.get("/{route_id}", response_model=RouteOut)
async def get_route(route_id: int, db: AsyncSession = Depends(get_db)):
    return await svc.get_route(db, route_id)


@router.patch("/{route_id}", response_model=RouteOut)
async def update_route(route_id: int, body: RouteUpdate, db: AsyncSession = Depends(get_db)):
    route = await svc.get_route(db, route_id)
    return await svc.update_route(db, route, body)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(route_id: int, db: AsyncSession = Depends(get_db)) -> None:
    route = await svc.get_route(db, route_id)
    await svc.delete_route(db, route)
