"""Async engine + session factory (decision #1: PostgreSQL + SQLAlchemy 2.0 async)."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
)
