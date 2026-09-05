"""GPS bus simulator (Phase 11).

Walks seeded vehicles along their assigned route polylines and publishes valid
GPS fixes to the broker, exactly like real devices would (topic
``fleet/<vehicle_id>/gps``, payload validated by ``app.mqtt.payload.GPSMessage``).

Run standalone (same image as the API, or the venv):

    python -m simulator

In docker compose it is the profile-gated ``simulator`` service:

    docker compose --profile sim up
"""

from simulator.walk import BusWalker

__all__ = ["BusWalker"]
