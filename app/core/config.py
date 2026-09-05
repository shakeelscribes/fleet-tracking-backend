"""Application configuration - pydantic-settings, fully env-driven (decision #1, #22)."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(url: str) -> str:
    """Map common non-async schemes onto asyncpg (PaaS like Render hand out
    postgresql:// URLs; SQLAlchemy's async engine needs postgresql+asyncpg://).
    postgresql+asyncpg:// and postgres+asyncpg:// pass through unchanged."""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Vehicle Tracking API"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://tracking:tracking@localhost:5432/tracking"
    TESTING: bool = False  # true in tests: NullPool (safe across pytest event loops)

    @field_validator("DATABASE_URL")
    @classmethod
    def _async_db_scheme(cls, v: str) -> str:
        return _normalize_database_url(v)

    # JWT
    JWT_SECRET_KEY: str = (
        "dev-only-secret-key-change-me-0123456789abcdef-0123456789abcdef"  # >= 32 bytes
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # MQTT
    MQTT_ENABLED: bool = True  # false in tests / when running without a broker
    MQTT_HOST: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    MQTT_TLS: bool = False  # true for cloud brokers (HiveMQ Cloud listens on 8883/TLS)
    MQTT_TOPIC_PREFIX: str = "fleet"

    # GPS status derivation (moving vs idle threshold is a code constant:
    # MOVING_SPEED_KMH = 5.0 in app/services/tracking_service.py)
    GPS_STALENESS_SECONDS: int = 60
    # Seeding (decision #20): demo password for seeded accounts
    SEED_PASSWORD: str = "password123"

    # Simulator (cloud demo only)
    SIMULATOR_ENABLED: bool = False
    SIMULATOR_INTERVAL_SECONDS: int = 2

    # CORS
    CORS_ORIGINS: str = "*"  # comma-separated origins in prod


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
