"""The insert builder, including the PostgreSQL branch no live test can reach."""

from typing import cast

import pytest
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine.interfaces import Dialect

from app.services.cache import build_conflict_free_insert

VALUES = [{"source_hash": "h", "source": "a", "transformed": "A"}]


@pytest.mark.parametrize("name", ["sqlite", "postgresql"])
def test_both_dialects_ignore_conflicts(name: str) -> None:
    # SQLAlchemy's dialect() factories are untyped.
    builder = sqlite.dialect if name == "sqlite" else postgresql.dialect
    dialect = cast("Dialect", builder())

    sql = str(build_conflict_free_insert(name, VALUES).compile(dialect=dialect))

    assert "INSERT INTO transformed_string" in sql
    assert "ON CONFLICT DO NOTHING" in sql


def test_an_unsupported_dialect_is_refused() -> None:
    with pytest.raises(RuntimeError, match="unsupported database dialect: mysql"):
        build_conflict_free_insert("mysql", VALUES)
