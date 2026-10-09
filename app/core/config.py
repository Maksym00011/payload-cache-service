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

    # Upper bound on one transformer call, so a hung upstream cannot pin a
    # request, a session and a pooled connection indefinitely.
    transformer_timeout_seconds: float = 10.0

    log_level: str = "INFO"

    # Ceiling on the request body, checked before anything is parsed. The
    # largest request the schema allows is about 210 KB, so this leaves room
    # without letting a 50 MB body be decoded into memory first.
    max_request_bytes: int = 512 * 1024


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once per process."""
    return Settings()
