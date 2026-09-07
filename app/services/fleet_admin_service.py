"""Fleet admin business logic: CRUD for routes/vehicles/users + assignment (decision #7).

Enforcement notes:
- A route/vehicle in active use cannot be deleted (409) - protects FK integrity
  and the graded demo data.
- Exclusivity (decision #7 micro-decision): a route or vehicle can be assigned to
  only one user at a time. This keeps "User A sees only BUS-001" airtight: no two
  users can ever see the same vehicle's live location.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.models import BusRoute, GPSPoint, User, Vehicle, VehicleCurrentLocation
from app.schemas.route import RouteCreate, RouteUpdate
from app.schemas.tracking import VehicleLiveOut
from app.schemas.user import AssignmentUpdate, UserCreate, UserUpdate
from app.schemas.vehicle import AdminVehicleOut, VehicleCreate, VehicleUpdate
from app.services.tracking_service import derive_status

# --- Routes ------------------------------------------------------------------


async def create_route(db: AsyncSession, data: RouteCreate) -> BusRoute:
    existing = await db.scalar(select(BusRoute).where(BusRoute.name == data.name))
    if existing:
        raise ConflictError(f"Route name already exists: {data.name!r}", code="route_name_taken")
    route = BusRoute(name=data.name, waypoints=[w.model_dump() for w in data.waypoints])
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return route


async def list_routes(db: AsyncSession) -> list[BusRoute]:
    result = await db.execute(select(BusRoute).order_by(BusRoute.id))
    return list(result.scalars().all())


async def get_route(db: AsyncSession, route_id: int) -> BusRoute:
    route = await db.get(BusRoute, route_id)
    if route is None:
        raise NotFoundError(f"Route {route_id} not found", code="route_not_found")
    return route


async def update_route(db: AsyncSession, route: BusRoute, data: RouteUpdate) -> BusRoute:
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != route.name:
        clash = await db.scalar(select(BusRoute).where(BusRoute.name == changes["name"]))
        if clash:
            raise ConflictError(
                f"Route name already exists: {changes['name']!r}", code="route_name_taken"
            )
        route.name = changes["name"]
    if data.waypoints is not None:
        route.waypoints = [w.model_dump() for w in data.waypoints]
    await db.commit()
    await db.refresh(route)
    return route


async def delete_route(db: AsyncSession, route: BusRoute) -> None:
    in_use = await db.scalar(
        select(func.count()).select_from(User).where(User.route_id == route.id)
    )
    if in_use:
        raise ConflictError(
            f"Route is assigned to {in_use} user(s) and cannot be deleted", code="route_in_use"
        )
    await db.delete(route)
    await db.commit()


# --- Vehicles ----------------------------------------------------------------


async def create_vehicle(db: AsyncSession, data: VehicleCreate) -> Vehicle:
    existing = await db.scalar(select(Vehicle).where(Vehicle.code == data.code))
    if existing:
        raise ConflictError(
            f"Vehicle code already exists: {data.code!r}", code="vehicle_code_taken"
        )
    vehicle = Vehicle(code=data.code, name=data.name, is_active=data.is_active)
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


async def list_vehicles(db: AsyncSession) -> list[Vehicle]:
    result = await db.execute(select(Vehicle).order_by(Vehicle.id))
    return list(result.scalars().all())


def _admin_vehicle_out(vehicle: Vehicle) -> AdminVehicleOut:
    """Build the fleet-view row: vehicle + live location with derived status."""
    loc = vehicle.current_location  # joined-loaded (decision #8)
    live = None
    if loc is not None:
        live = VehicleLiveOut(
            vehicle_id=vehicle.id,
            vehicle_code=vehicle.code,
            lat=float(loc.lat),
            lng=float(loc.lng),
            speed=float(loc.speed),
            recorded_at=loc.recorded_at,
            status=derive_status(loc.recorded_at, loc.speed),
        )
    return AdminVehicleOut(
        id=vehicle.id,
        code=vehicle.code,
        name=vehicle.name,
        is_active=vehicle.is_active,
        created_at=vehicle.created_at,
        current_location=live,
    )


async def list_vehicles_with_location(db: AsyncSession) -> list[AdminVehicleOut]:
    """Fleet overview for the admin map: every vehicle + its latest fix."""
    result = await db.execute(select(Vehicle).order_by(Vehicle.id))
    return [_admin_vehicle_out(v) for v in result.scalars().all()]


async def get_vehicle(db: AsyncSession, vehicle_id: int) -> Vehicle:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError(f"Vehicle {vehicle_id} not found", code="vehicle_not_found")
    return vehicle


async def update_vehicle(db: AsyncSession, vehicle: Vehicle, data: VehicleUpdate) -> Vehicle:
    changes = data.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != vehicle.code:
        clash = await db.scalar(select(Vehicle).where(Vehicle.code == changes["code"]))
        if clash:
            raise ConflictError(
                f"Vehicle code already exists: {changes['code']!r}", code="vehicle_code_taken"
            )
        vehicle.code = changes["code"]
    if "name" in changes:
        vehicle.name = changes["name"]
    if "is_active" in changes:
        vehicle.is_active = changes["is_active"]
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


async def delete_vehicle(db: AsyncSession, vehicle: Vehicle) -> None:
    assigned = await db.scalar(
        select(func.count()).select_from(User).where(User.vehicle_id == vehicle.id)
    )
    if assigned:
        raise ConflictError(
            f"Vehicle is assigned to {assigned} user(s) and cannot be deleted",
            code="vehicle_in_use",
        )
    has_history = await db.scalar(
        select(func.count()).select_from(GPSPoint).where(GPSPoint.vehicle_id == vehicle.id)
    )
    has_current = await db.get(VehicleCurrentLocation, vehicle.id)
    if has_history or has_current:
        raise ConflictError(
            "Vehicle has GPS tracking data and cannot be deleted", code="vehicle_in_use"
        )
    await db.delete(vehicle)
    await db.commit()


# --- Users -------------------------------------------------------------------


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing:
        raise ConflictError(f"Email already registered: {data.email}", code="email_taken")
    user = User(
        email=data.email, hashed_password=hash_password(data.password), is_admin=data.is_admin
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found", code="user_not_found")
    return user


async def update_user(db: AsyncSession, user: User, data: UserUpdate) -> User:
    changes = data.model_dump(exclude_unset=True)
    if "email" in changes and changes["email"] != user.email:
        clash = await db.scalar(select(User).where(User.email == changes["email"]))
        if clash:
            raise ConflictError(f"Email already registered: {changes['email']}", code="email_taken")
        user.email = changes["email"]
    if data.password is not None:
        user.hashed_password = hash_password(data.password)
    if data.is_admin is not None:
        user.is_admin = data.is_admin
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.commit()


# --- Assignment (the graded core, decision #7/#11) ---------------------------


async def set_assignment(db: AsyncSession, user_id: int, data: AssignmentUpdate) -> User:
    user = await get_user(db, user_id)

    if data.route_id is None and data.vehicle_id is None:
        user.route_id = None
        user.vehicle_id = None
        await db.commit()
        await db.refresh(user)
        return user

    route = await get_route(db, data.route_id)  # type: ignore[arg-type] - validator guarantees pair
    vehicle = await get_vehicle(db, data.vehicle_id)  # type: ignore[arg-type]

    other_route_user = await db.scalar(
        select(User).where(User.route_id == route.id, User.id != user.id)
    )
    if other_route_user:
        raise ConflictError(
            f"Route is already assigned to {other_route_user.email}",
            code="route_already_assigned",
        )

    other_vehicle_user = await db.scalar(
        select(User).where(User.vehicle_id == vehicle.id, User.id != user.id)
    )
    if other_vehicle_user:
        raise ConflictError(
            f"Vehicle is already assigned to {other_vehicle_user.email}",
            code="vehicle_already_assigned",
        )

    user.route_id = route.id
    user.vehicle_id = vehicle.id
    await db.commit()
    await db.refresh(user)
    return user
