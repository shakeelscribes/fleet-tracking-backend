"""Application entrypoint: `python run.py` (from backend/).

Uses a SelectorEventLoop via app.core.loops so aiomqtt works on Windows too
(see app/core/loops.py). On Linux/Docker the behavior is identical to
uvicorn's default asyncio loop.
"""

import logging
import os

import uvicorn

if __name__ == "__main__":
    # Surface app-level INFO logs (MQTT lifecycle, ingestion) next to uvicorn's
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
        loop="app.core.loops:selector_event_loop_factory",
    )
