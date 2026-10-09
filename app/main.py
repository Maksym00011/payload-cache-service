"""Application factory.

`create_app` takes settings so tests can point the service at a throwaway
database and a fake transformer without touching the environment.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import build_engine, build_session_factory, create_tables
from app.services.errors import TransformerError, TransformerTimeoutError
from app.services.transformer import Transformer, UppercaseTransformer

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    engine = build_engine(settings)
    try:
        # A real deployment would run migrations here instead; see the README.
        await create_tables(engine)
    except Exception:
        # Startup failed; let go of the connection rather than leaking it.
        await engine.dispose()
        raise

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
    # Annotated so the type checker verifies the implementation against the
    # Protocol; app.state itself is untyped.
    transformer: Transformer = UppercaseTransformer(settings.transformer_latency_seconds)
    app.state.transformer = transformer
    app.include_router(router)
    _register_body_limit(app, settings.max_request_bytes)
    _register_error_handlers(app)
    return app


def _register_body_limit(app: FastAPI, max_bytes: int) -> None:
    """Refuse an oversized body before it is parsed.

    The schema limit only applies after the JSON has been decoded, so a 50 MB
    body was being held in memory before being rejected. The README used to
    point at a reverse proxy for this, but compose publishes the port directly,
    so the service has to defend itself.

    A chunked request carries no Content-Length and is not caught here; a proxy
    or an ASGI server limit is still the complete answer.
    """

    @app.middleware("http")
    async def limit_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={"detail": f"the request body must not exceed {max_bytes} bytes"},
            )

        return await call_next(request)


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TransformerError)
    async def handle_transformer_error(_request: Request, error: Exception) -> JSONResponse:
        """A broken upstream is a gateway error, not an internal server error."""
        timed_out = isinstance(error, TransformerTimeoutError)
        logger.warning("transformer failed: %s", error)

        # The client gets a fixed message. The exception text names internal
        # details such as the configured timeout, which is ours to know.
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT
            if timed_out
            else status.HTTP_502_BAD_GATEWAY,
            content={
                "detail": "the transformer did not answer in time"
                if timed_out
                else "the transformer answered with something unusable"
            },
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(PoolTimeoutError)
    async def handle_database_pressure(_request: Request, error: Exception) -> JSONResponse:
        """Busy is not broken.

        SQLite allows a single writer, and the connection pool is finite, so a
        burst of writes can fail with "database is locked" or a pool timeout.
        Both mean "try again", which is 503 and not the 500 these used to
        become.
        """
        logger.warning("database under pressure: %s", error)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "the service is busy, please retry"},
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, error: Exception) -> JSONResponse:
        """Report what is wrong without echoing the request back.

        FastAPI's default body includes the rejected input, so a request at the
        size limit was returned to the caller in full and written to the access
        log with it.
        """
        errors = error.errors() if isinstance(error, RequestValidationError) else []
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": [
                    {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
                    for item in errors
                ]
            },
        )


app = create_app()
