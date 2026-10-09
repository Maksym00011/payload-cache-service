"""Database access for cached transformer results.

Every method works on a whole batch. The point of the cache is to turn N calls
to the transformer into one, so it must not reintroduce N queries against the
database instead.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql.dml import Insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models import TransformedString
from app.domain.fingerprint import hash_source


def build_conflict_free_insert(dialect: str, values: list[dict[str, Any]]) -> Insert:
    """Build an INSERT that ignores rows another writer already stored.

    ON CONFLICT DO NOTHING is dialect specific in SQLAlchemy, so both
    supported dialects are spelled out. The dialect is an argument rather than
    read from a session, so each branch can be tested without that server.
    """
    if dialect == "sqlite":
        return sqlite_insert(TransformedString).values(values).on_conflict_do_nothing()
    if dialect == "postgresql":
        return postgres_insert(TransformedString).values(values).on_conflict_do_nothing()

    raise RuntimeError(f"unsupported database dialect: {dialect}")


class TransformCache:
    """Reads and writes the cache of transformed strings."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_many(self, sources: Sequence[str]) -> dict[str, str]:
        """Return `{source: transformed}` for the sources already cached.

        One SELECT for the whole batch, whatever its size.
        """
        if not sources:
            return {}

        hashes = [hash_source(source) for source in sources]
        # Two columns rather than whole rows: up to 2000 entities per request
        # would be built only to read two fields off each.
        statement = select(TransformedString.source, TransformedString.transformed).where(
            col(TransformedString.source_hash).in_(hashes)
        )
        rows = (await self._session.exec(statement)).all()
        return dict(rows)

    async def store_many(self, transforms: Mapping[str, str]) -> None:
        """Store new results, ignoring any a concurrent request already wrote.

        Two requests can miss on the same string at the same time. Letting the
        database drop the duplicate is cheaper and safer than locking.
        """
        if not transforms:
            return

        values: list[dict[str, Any]] = [
            {
                "source_hash": hash_source(source),
                "source": source,
                "transformed": transformed,
            }
            for source, transformed in transforms.items()
        ]
        statement = build_conflict_free_insert(self._session.get_bind().dialect.name, values)
        await self._session.exec(statement)
