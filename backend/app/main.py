"""FastAPI application factory + lifespan (MQTT subscriber starts here in Phase 6)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    # Phase 6 (decision #5): MQTT subscriber task starts here via app.mqtt.client
    # Phase 10 (decision #22): in-process simulator starts here when SIMULATOR_ENABLED=true
    yield
    # Shutdown


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
