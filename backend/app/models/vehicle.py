"""Vehicle model - the tracked bus (decision #8)."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 1:1 latest-location row (decision #8) - upserted by the MQTT handler
    current_location = relationship(
        "VehicleCurrentLocation", back_populates="vehicle", uselist=False, lazy="joined"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Vehicle id={self.id} code={self.code!r}>"
