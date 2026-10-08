"""Database access for cached transformer results.

Every method works on a whole batch. The point of the cache is to turn N calls
to the transformer into one, so it must not reintroduce N queries against the
database instead.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql import Executable
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models import TransformedString
from app.domain.fingerprint import hash_source


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
        statement = select(TransformedString).where(col(TransformedString.source_hash).in_(hashes))
        rows = (await self._session.exec(statement)).all()
        return {row.source: row.transformed for row in rows}

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
        # SQLModel asks for exec() over execute(), but types it for SELECT only,
        # hence the ignore on an INSERT.
        await self._session.exec(self._insert_ignoring_duplicates(values))  # type: ignore[call-overload]

    def _insert_ignoring_duplicates(self, values: list[dict[str, Any]]) -> Executable:
        """ON CONFLICT DO NOTHING is dialect specific, so spell out both."""
        dialect = self._session.get_bind().dialect.name
        if dialect == "sqlite":
            return sqlite_insert(TransformedString).values(values).on_conflict_do_nothing()
        if dialect == "postgresql":
            return postgres_insert(TransformedString).values(values).on_conflict_do_nothing()

        raise RuntimeError(f"unsupported database dialect: {dialect}")
