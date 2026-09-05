"""Application configuration - pydantic-settings, fully env-driven (decision #1, #22)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Vehicle Tracking API"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://tracking:tracking@localhost:5432/tracking"
    TESTING: bool = False  # true in tests: NullPool (safe across pytest event loops)

    # JWT
    JWT_SECRET_KEY: str = (
        "dev-only-secret-key-change-me-0123456789abcdef-0123456789abcdef"  # >= 32 bytes
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # MQTT
    MQTT_HOST: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    MQTT_TOPIC_PREFIX: str = "fleet"

    # GPS status derivation
    GPS_STALENESS_SECONDS: int = 60
    MOVING_SPEED_KMH: float = 5.0

    # Simulator (cloud demo only)
    SIMULATOR_ENABLED: bool = False
    SIMULATOR_INTERVAL_SECONDS: int = 2

    # CORS
    CORS_ORIGINS: str = "*"  # comma-separated origins in prod


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
