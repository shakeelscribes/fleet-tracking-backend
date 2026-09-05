"""Async engine + session factory (decision #1: PostgreSQL + SQLAlchemy 2.0 async)."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

_engine_kwargs: dict = {"pool_pre_ping": True, "echo": settings.DEBUG}
if settings.TESTING:
    # Connections are event-loop bound; NullPool avoids cross-loop reuse in tests
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
)
