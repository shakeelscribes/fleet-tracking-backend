"""Throwaway smoke seed for manual testing (real seed module comes in Phase 7)."""

import asyncio

from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models import BusRoute, User, Vehicle


async def main() -> None:
    async with async_session_factory() as session:
        admin = User(
            email="admin@fleet.com",
            hashed_password=hash_password("password123"),
            is_admin=True,
        )
        route = BusRoute(
            name="City-Airport",
            waypoints=[{"lat": 13.0827, "lng": 80.2707}, {"lat": 12.99, "lng": 80.17}],
        )
        vehicle = Vehicle(code="BUS-001", name="Chennai Express")
        session.add_all([admin, route, vehicle])
        await session.flush()

        session.add(
            User(
                email="ravi@fleet.com",
                hashed_password=hash_password("password123"),
                route_id=route.id,
                vehicle_id=vehicle.id,
            )
        )
        session.add(User(email="free@fleet.com", hashed_password=hash_password("password123")))
        await session.commit()
        print("seeded: admin, ravi (BUS-001 + City-Airport), free (unassigned)")


if __name__ == "__main__":
    asyncio.run(main())
