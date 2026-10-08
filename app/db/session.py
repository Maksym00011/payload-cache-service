"""Async engine and session wiring."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings

_SQLITE_FILE_PREFIX = "sqlite+aiosqlite:///"


def _ensure_sqlite_directory(database_url: str) -> None:
    """Create the folder for a SQLite file, so a fresh checkout just runs."""
    if not database_url.startswith(_SQLITE_FILE_PREFIX):
        return

    raw_path = database_url.removeprefix(_SQLITE_FILE_PREFIX)
    if not raw_path or raw_path.startswith(":memory:"):
        return

    Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, echo=False)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: with an async session, touching an attribute of
    # an expired object would trigger a lazy load outside of `await` and fail.
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables(engine: AsyncEngine) -> None:
    """Create the schema on startup.

    A real deployment would run Alembic migrations. For a two-table service
    this keeps setup to one step; the trade-off is written down in the README.
    """
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
