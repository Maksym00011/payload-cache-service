"""Shared fixtures: a throwaway SQLite database per test."""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.db.session import build_engine, build_session_factory, create_tables
from app.main import create_app
from tests.doubles import RecordingTransformer


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Point the service at a fresh database file and remove the fake latency."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        transformer_latency_seconds=0,
        # Short, so the test for an unresponsive transformer finishes quickly.
        transformer_timeout_seconds=0.5,
    )


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = build_engine(settings)
    await create_tables(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with build_session_factory(engine)() as session:
        yield session


@pytest.fixture
def executed_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    """Record every SQL statement, so tests can prove there is no N+1."""
    statements: list[str] = []

    # The argument list is fixed by SQLAlchemy's event API.
    def record(  # noqa: PLR0913, PLR0917
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    yield statements
    event.remove(engine.sync_engine, "before_cursor_execute", record)


@pytest.fixture
def transformer() -> RecordingTransformer:
    return RecordingTransformer()


@pytest.fixture
def make_client(
    settings: Settings,
) -> Callable[[object], AbstractAsyncContextManager[AsyncClient]]:
    """Build a client for an app wired to the transformer a test wants."""

    @asynccontextmanager
    async def build(transformer: object) -> AsyncIterator[AsyncClient]:
        app = create_app(settings)
        app.state.transformer = transformer
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            yield client

    return build


@pytest.fixture
async def client(
    make_client: Callable[[object], AbstractAsyncContextManager[AsyncClient]],
    transformer: RecordingTransformer,
) -> AsyncIterator[AsyncClient]:
    async with make_client(transformer) as client:
        yield client
