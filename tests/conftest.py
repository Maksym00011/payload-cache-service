"""Shared fixtures: a throwaway SQLite database per test."""

from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.db.session import build_engine, build_session_factory, create_tables
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Point the service at a fresh database file and remove the fake latency."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        transformer_latency_seconds=0,
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


class RecordingTransformer:
    """Test double that remembers every batch it was asked to transform.

    The service depends on a Protocol, so this is all a fake needs to be: no
    mocking library, and tests can assert on exactly which strings went out.
    """

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def transform_many(self, values: Sequence[str]) -> list[str]:
        self.batches.append(list(values))
        return [value.upper() for value in values]

    @property
    def calls(self) -> int:
        return len(self.batches)


@pytest.fixture
def transformer() -> RecordingTransformer:
    return RecordingTransformer()


@pytest.fixture
async def client(
    settings: Settings, transformer: RecordingTransformer
) -> AsyncIterator[AsyncClient]:
    """An HTTP client talking to the app in-process, lifespan included."""
    app = create_app(settings)
    app.state.transformer = transformer

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client,
    ):
        yield http_client
