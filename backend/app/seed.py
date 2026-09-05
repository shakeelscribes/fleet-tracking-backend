"""Idempotent database seeding for demos and grading (decision #20).

Usage (from backend/):
    python -m app.seed           # create any missing demo routes/vehicles/users
    python -m app.seed --fresh   # WARNING: wipe all tables, then seed from scratch

Demo dataset (strict 1:1:1 user-route-vehicle assignment, Chennai):
    admin@fleet.com                      (admin, no assignment)
    ravi@fleet.com   -> City Center to Airport  + BUS-001
    priya@fleet.com  -> OMR Tech Corridor       + BUS-002
    arun@fleet.com   -> Marina to Central       + BUS-003
    divya@fleet.com  -> T. Nagar to Guindy      + BUS-004

All seeded accounts share the password from SEED_PASSWORD (default password123).
Existing rows are never modified: re-running the seed cannot clobber demo state
created through the admin API. Use --fresh for a clean rebuild.
"""

import argparse
import asyncio
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models import BusRoute, GPSPoint, User, Vehicle, VehicleCurrentLocation

logger = logging.getLogger("app.seed")

ADMIN_EMAIL = "admin@fleet.com"

DEMO_ROUTES: list[dict] = [
    {
        "name": "City Center to Airport",
        "waypoints": [
            {"lat": 13.0827, "lng": 80.2707},  # Chennai Central
            {"lat": 13.0417, "lng": 80.2345},  # Kathipara
            {"lat": 12.9941, "lng": 80.1709},  # Chennai Airport
        ],
    },
    {
        "name": "OMR Tech Corridor",
        "waypoints": [
            {"lat": 13.0093, "lng": 80.2481},  # Madhya Kailash
            {"lat": 12.9600, "lng": 80.2400},  # Perungudi
            {"lat": 12.9010, "lng": 80.2279},  # Sholinganallur
        ],
    },
    {
        "name": "Marina to Central",
        "waypoints": [
            {"lat": 13.0552, "lng": 80.2824},  # Marina Beach
            {"lat": 13.0665, "lng": 80.2685},  # Triplicane
            {"lat": 13.0827, "lng": 80.2707},  # Chennai Central
        ],
    },
    {
        "name": "T. Nagar to Guindy",
        "waypoints": [
            {"lat": 13.0418, "lng": 80.2341},  # T. Nagar
            {"lat": 13.0254, "lng": 80.2274},  # Ashok Nagar
            {"lat": 13.0104, "lng": 80.2206},  # Guindy
        ],
    },
]

DEMO_VEHICLES: list[dict] = [
    {"code": "BUS-001", "name": "Chennai Express"},
    {"code": "BUS-002", "name": "OMR Flier"},
    {"code": "BUS-003", "name": "Marina Cruiser"},
    {"code": "BUS-004", "name": "Guindy Shuttle"},
]

# (email, route name, vehicle code) - strict 1:1:1 (decision #20)
DEMO_ASSIGNMENTS: list[tuple[str, str, str]] = [
    ("ravi@fleet.com", "City Center to Airport", "BUS-001"),
    ("priya@fleet.com", "OMR Tech Corridor", "BUS-002"),
    ("arun@fleet.com", "Marina to Central", "BUS-003"),
    ("divya@fleet.com", "T. Nagar to Guindy", "BUS-004"),
]


async def _truncate(db: AsyncSession) -> None:
    """Wipe all app tables (demo reset), in FK-safe dependency order."""
    for table in (
        GPSPoint.__table__,
        VehicleCurrentLocation.__table__,
        User.__table__,
        Vehicle.__table__,
        BusRoute.__table__,
    ):
        await db.execute(delete(table))


async def seed(*, fresh: bool = False) -> dict[str, int]:
    """Create any missing demo entities. Returns counts of *created* rows."""
    created = {"routes": 0, "vehicles": 0, "users": 0}
    async with async_session_factory() as db:
        if fresh:
            await _truncate(db)
            await db.commit()
            logger.info("Fresh seed: all tables wiped")

        routes: dict[str, BusRoute] = {}
        for spec in DEMO_ROUTES:
            route = await db.scalar(select(BusRoute).where(BusRoute.name == spec["name"]))
            if route is None:
                route = BusRoute(name=spec["name"], waypoints=spec["waypoints"])
                db.add(route)
                await db.flush()
                created["routes"] += 1
            routes[route.name] = route

        vehicles: dict[str, Vehicle] = {}
        for spec in DEMO_VEHICLES:
            vehicle = await db.scalar(select(Vehicle).where(Vehicle.code == spec["code"]))
            if vehicle is None:
                vehicle = Vehicle(code=spec["code"], name=spec["name"])
                db.add(vehicle)
                await db.flush()
                created["vehicles"] += 1
            vehicles[spec["code"]] = vehicle

        admin = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if admin is None:
            db.add(
                User(
                    email=ADMIN_EMAIL,
                    hashed_password=hash_password(settings.SEED_PASSWORD),
                    is_admin=True,
                )
            )
            created["users"] += 1

        for email, route_name, vehicle_code in DEMO_ASSIGNMENTS:
            user = await db.scalar(select(User).where(User.email == email))
            if user is None:
                db.add(
                    User(
                        email=email,
                        hashed_password=hash_password(settings.SEED_PASSWORD),
                        route_id=routes[route_name].id,
                        vehicle_id=vehicles[vehicle_code].id,
                    )
                )
                created["users"] += 1

        await db.commit()

    logger.info(
        "Seed complete: %s routes, %s vehicles, %s users created",
        created["routes"],
        created["vehicles"],
        created["users"],
    )
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the vehicle-tracking demo database")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="WARNING: wipe all tables before seeding (demo reset)",
    )
    args = parser.parse_args()
    created = asyncio.run(seed(fresh=args.fresh))
    print(
        f"seeded: {created['routes']} routes, "
        f"{created['vehicles']} vehicles, {created['users']} users created"
    )
    print(f"demo password for all seeded accounts: {settings.SEED_PASSWORD}")


if __name__ == "__main__":
    main()
