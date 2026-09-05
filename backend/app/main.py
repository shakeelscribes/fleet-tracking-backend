"""FastAPI application factory + lifespan (MQTT subscriber, decision #5)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.mqtt.client import mqtt_subscriber_task
from simulator.runner import run_simulator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: in-process MQTT subscriber (decision #5); swap point for a worker.
    # In-process simulator (decision #22) for the cloud demo, where there is no
    # second container to run `python -m simulator`.
    background: list[asyncio.Task] = []
    if settings.MQTT_ENABLED:
        background.append(asyncio.create_task(mqtt_subscriber_task()))
    if settings.SIMULATOR_ENABLED:
        stop = asyncio.Event()
        background.append(asyncio.create_task(run_simulator(stop)))
    yield
    for task in background:
        task.cancel()
    await asyncio.gather(*background, return_exceptions=True)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS (decision #12: permissive in dev, configurable via env)
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    register_exception_handlers(app)
    return app


app = create_app()
