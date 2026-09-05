"""GPSPoint model - append-only GPS history (decision #8, payload per decision #16)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GPSPoint(Base):
    __tablename__ = "gps_points"
    __table_args__ = (
        # History queries filter by vehicle + time range (decision #14)
        Index("ix_gps_points_vehicle_recorded", "vehicle_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)

    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)  # [-90, 90]
    lng: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)  # [-180, 180]
    speed: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)  # km/h (decision #16)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GPSPoint vehicle_id={self.vehicle_id} at={self.recorded_at}>"
