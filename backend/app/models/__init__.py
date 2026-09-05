"""SQLAlchemy 2.0 models (decision #1, #8). Importing this package registers all models."""

from app.models.current_location import VehicleCurrentLocation
from app.models.gps_point import GPSPoint
from app.models.route import BusRoute
from app.models.user import User
from app.models.vehicle import Vehicle

__all__ = ["BusRoute", "GPSPoint", "User", "Vehicle", "VehicleCurrentLocation"]
