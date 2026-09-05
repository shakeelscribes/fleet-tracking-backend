"""VehicleCurrentLocation - denormalized 1:1 latest location (decision #8).

Upserted by the MQTT handler on every valid message; keeps Home-screen reads fast.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class VehicleCurrentLocation(Base):
    __tablename__ = "vehicle_current_location"

    # PK == FK: strictly one current-location row per vehicle
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), primary_key=True)

    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    lng: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    speed: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)  # km/h
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    vehicle = relationship("Vehicle", back_populates="current_location")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VehicleCurrentLocation vehicle_id={self.vehicle_id}>"
