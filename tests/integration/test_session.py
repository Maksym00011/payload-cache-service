from pathlib import Path

from app.core.config import Settings
from app.db.session import build_engine, create_tables


async def test_a_missing_sqlite_directory_is_created(tmp_path: Path):
    """Regression: the default DATABASE_URL points at ./data, which a fresh
    checkout does not have, and the service used to fail to start."""
    database = tmp_path / "nested" / "cache.db"
    engine = build_engine(Settings(database_url=f"sqlite+aiosqlite:///{database}"))

    try:
        await create_tables(engine)
    finally:
        await engine.dispose()

    assert database.exists()
