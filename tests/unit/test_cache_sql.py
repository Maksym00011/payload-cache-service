"""The insert builder, including the PostgreSQL branch no live test can reach."""

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.services.cache import build_conflict_free_insert

VALUES = [{"source_hash": "h", "source": "a", "transformed": "A"}]


@pytest.mark.parametrize(
    ("dialect", "compiler"),
    [("sqlite", sqlite.dialect()), ("postgresql", postgresql.dialect())],
)
def test_both_dialects_ignore_conflicts(dialect: str, compiler: object):
    statement = build_conflict_free_insert(dialect, VALUES)

    sql = str(statement.compile(dialect=compiler))  # type: ignore[arg-type]

    assert "INSERT INTO transformed_string" in sql
    assert "ON CONFLICT DO NOTHING" in sql


def test_an_unsupported_dialect_is_refused():
    with pytest.raises(RuntimeError, match="unsupported database dialect: mysql"):
        build_conflict_free_insert("mysql", VALUES)
