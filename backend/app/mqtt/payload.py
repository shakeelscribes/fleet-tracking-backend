"""Topic + payload parsing/validation for GPS ingestion (decision #15).

Topic contract:  {prefix}/{vehicle_id}/gps   e.g. "fleet/1/gps"
Payload contract (JSON, UTF-8):
    {
      "vehicle_id": 1,
      "lat": 13.0827,
      "lng": 80.2707,
      "speed": 42.5,                    # km/h (decision #16)
      "timestamp": "2026-09-05T12:00:00Z"  # timezone-aware ISO-8601, UTC preferred
    }

Everything that fails validation is rejected here; the handler just logs + discards.
"""

import json
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger("app.mqtt.payload")


class GPSMessage(BaseModel):
    """Validated shape of one GPS fix from the broker."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    vehicle_id: int = Field(ge=1)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    speed: float = Field(ge=0, le=300)  # km/h; absurd values are sensor glitches
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be timezone-aware (UTC expected)")
        return v


def parse_topic(topic: str, *, prefix: str = "fleet") -> int | None:
    """`fleet/{vehicle_id}/gps` -> vehicle_id, else None (wrong shape/prefix/id)."""
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != prefix or parts[2] != "gps":
        return None
    try:
        vehicle_id = int(parts[1])
    except ValueError:
        return None
    return vehicle_id if vehicle_id >= 1 else None


def parse_payload(payload: bytes | str) -> GPSMessage | None:
    """JSON bytes -> GPSMessage, or None when malformed/invalid (logged, never raises)."""
    try:
        data: Any = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Discarding GPS payload: not valid JSON (%s)", exc)
        return None
    if not isinstance(data, dict):
        logger.warning("Discarding GPS payload: JSON root is not an object")
        return None
    try:
        return GPSMessage.model_validate(data)
    except ValueError as exc:
        logger.warning("Discarding GPS payload: schema violation (%s)", exc)
        return None
