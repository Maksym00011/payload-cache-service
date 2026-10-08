"""Service configuration, read from the environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything the service needs to run, with safe local defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite keeps the service runnable with no setup. Point this at
    # postgresql+asyncpg://... to use PostgreSQL instead; nothing else changes.
    database_url: str = "sqlite+aiosqlite:///./data/cache.db"

    # Pretend the transformer is a slow remote service.
    transformer_latency_seconds: float = 0.05

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once per process."""
    return Settings()
