"""Database tables.

Two tables doing two different jobs: `TransformedString` is the cache of
expensive transformer results, and `Payload` records a generated payload so a
repeated request can be answered with the id it already got.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

HASH_LENGTH = 64  # sha256, hex encoded


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TransformedString(SQLModel, table=True):
    """One cached result of the transformer, keyed by the hash of its input."""

    __tablename__ = "transformed_string"

    # The hash is the primary key rather than `source` itself: the input is
    # arbitrary user text, and a PostgreSQL btree index rejects values over
    # roughly 2.7 KB. A digest is always 64 characters.
    source_hash: str = Field(primary_key=True, max_length=HASH_LENGTH)
    source: str
    transformed: str
    created_at: datetime = Field(default_factory=_utcnow)


class Payload(SQLModel, table=True):
    """A generated payload, looked up by id on read and by fingerprint on write."""

    __tablename__ = "payload"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Unique on purpose: two identical requests cannot create two payloads. The
    # second insert fails and the service returns the id that already exists.
    fingerprint: str = Field(unique=True, index=True, max_length=HASH_LENGTH)

    # The original input, kept so the output can be re-rendered if the format
    # changes, and so a stored payload can be debugged. JSON works on both
    # SQLite and PostgreSQL.
    source_lists: dict[str, list[str]] = Field(sa_column=Column(JSON, nullable=False))

    # The rendered output is stored, which makes a read a single row lookup
    # instead of re-joining the cached parts on every request.
    output: str
    created_at: datetime = Field(default_factory=_utcnow)
