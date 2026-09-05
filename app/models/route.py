"""BusRoute model - named route with ordered waypoint polyline (decision #6)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BusRoute(Base):
    __tablename__ = "bus_routes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Ordered polyline [{lat: float, lng: float}, ...] - served to the Flutter map (decision #6)
    waypoints: Mapped[list[dict[str, Decimal]]] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BusRoute id={self.id} name={self.name!r} waypoints={len(self.waypoints)}>"
