"""Async engine and session wiring."""

from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings

_SQLITE_PREFIX = "sqlite"
_SQLITE_FILE_PREFIX = "sqlite+aiosqlite:///"

# How long SQLite waits for another writer before giving up. SQLite locks the
# whole file for writes, so concurrent requests need this to avoid
# "database is locked".
_SQLITE_BUSY_TIMEOUT_MS = 5000


def _ensure_sqlite_directory(database_url: str) -> None:
    """Create the folder for a SQLite file, so a fresh checkout just runs."""
    if not database_url.startswith(_SQLITE_FILE_PREFIX):
        return

    raw_path = database_url.removeprefix(_SQLITE_FILE_PREFIX)
    if not raw_path or raw_path.startswith(":memory:"):
        return

    Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Make SQLite usable for a service, not just for a single script."""

    @event.listens_for(engine.sync_engine, "connect")
    def set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        # WAL lets readers work while a writer holds the lock.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        cursor.close()


def build_engine(settings: Settings) -> AsyncEngine:
    is_sqlite = settings.database_url.startswith(_SQLITE_PREFIX)
    if is_sqlite:
        _ensure_sqlite_directory(settings.database_url)

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        # Discard pooled connections the database closed behind our back,
        # instead of failing the first query after an idle period.
        pool_pre_ping=True,
    )
    if is_sqlite:
        _apply_sqlite_pragmas(engine)

    return engine


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
