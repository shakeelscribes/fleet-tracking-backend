"""Pure route-walking math for the simulator: no I/O, no app imports (unit-testable).

A bus has a position expressed as distance-along-polyline (metres) plus a
direction. Each tick it advances by ``speed * dt``; at either terminus it
dwells there (ping-pong), so a bus never teleports back to its start.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field

Waypoint = tuple[float, float]  # (lat, lng)

EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(a: Waypoint, b: Waypoint) -> float:
    """Great-circle distance between two (lat, lng) points, in metres."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


@dataclass
class BusWalker:
    """Position of one bus along one route polyline (metres along the path)."""

    waypoints: list[Waypoint]
    distance_m: float = 0.0
    direction: int = 1  # +1 toward the last waypoint, -1 back toward the first
    _cumulative: list[float] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if len(self.waypoints) < 2:
            raise ValueError("a route needs at least 2 waypoints to be walkable")
        cum: list[float] = [0.0]
        for a, b in zip(self.waypoints, self.waypoints[1:], strict=False):
            cum.append(cum[-1] + _haversine_m(a, b))
        self._cumulative = cum

    @property
    def total_m(self) -> float:
        return self._cumulative[-1]

    def advance(self, speed_kmh: float, dt_seconds: float) -> None:
        """Move by speed*dt; bounce direction at the termini."""
        step_m = speed_kmh * 1000.0 * dt_seconds / 3600.0
        self.distance_m += self.direction * step_m
        if self.distance_m >= self.total_m:
            self.distance_m = self.total_m
            self.direction = -1
        elif self.distance_m <= 0.0:
            self.distance_m = 0.0
            self.direction = 1

    def position(self) -> Waypoint:
        """Linear interpolation inside the segment containing distance_m."""
        if self.distance_m >= self.total_m:
            return self.waypoints[-1]
        idx = bisect_right(self._cumulative, self.distance_m) - 1
        idx = max(0, min(idx, len(self.waypoints) - 2))
        seg_start = self._cumulative[idx]
        seg_len = self._cumulative[idx + 1] - seg_start
        t = 0.0 if seg_len == 0 else (self.distance_m - seg_start) / seg_len
        (lat1, lng1), (lat2, lng2) = self.waypoints[idx], self.waypoints[idx + 1]
        return (lat1 + (lat2 - lat1) * t, lng1 + (lng2 - lng1) * t)
