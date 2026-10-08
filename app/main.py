"""Application factory.

`create_app` takes settings so tests can point the service at a throwaway
database and a fake transformer without touching the environment.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import build_engine, build_session_factory, create_tables
from app.services.transformer import UppercaseTransformer


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    engine = build_engine(settings)
    # A real deployment would run migrations here instead; see the README.
    await create_tables(engine)
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)

    try:
        yield
    finally:
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Payload Cache Service",
        description="Generates payloads from two string lists, caching the expensive part.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.transformer = UppercaseTransformer(settings.transformer_latency_seconds)
    app.include_router(router)
    return app


app = create_app()
