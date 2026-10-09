from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.cache import TransformCache


def count_selects(statements: list[str]) -> int:
    return sum(1 for statement in statements if statement.lstrip().upper().startswith("SELECT"))


async def test_get_many_returns_nothing_for_an_empty_cache(session: AsyncSession) -> None:
    cache = TransformCache(session)

    assert await cache.get_many(["first string"]) == {}


async def test_get_many_does_not_query_for_an_empty_input(
    session: AsyncSession, executed_statements: list[str]
) -> None:
    cache = TransformCache(session)

    assert await cache.get_many([]) == {}
    assert count_selects(executed_statements) == 0


async def test_stored_results_come_back(session: AsyncSession) -> None:
    cache = TransformCache(session)
    await cache.store_many({"first string": "FIRST STRING"})
    await session.commit()

    assert await cache.get_many(["first string"]) == {"first string": "FIRST STRING"}


async def test_get_many_returns_only_the_sources_it_has(session: AsyncSession) -> None:
    cache = TransformCache(session)
    await cache.store_many({"cached": "CACHED"})
    await session.commit()

    assert await cache.get_many(["cached", "missing"]) == {"cached": "CACHED"}


async def test_get_many_uses_one_query_for_the_whole_batch(
    session: AsyncSession, executed_statements: list[str]
) -> None:
    """The cache must not trade N transformer calls for N database queries."""
    cache = TransformCache(session)
    await cache.store_many({f"value {index}": f"VALUE {index}" for index in range(50)})
    await session.commit()
    executed_statements.clear()

    found = await cache.get_many([f"value {index}" for index in range(50)])

    assert len(found) == 50
    assert count_selects(executed_statements) == 1


async def test_storing_a_known_source_twice_is_ignored(session: AsyncSession) -> None:
    """Concurrent requests can both miss on the same string; neither should fail."""
    cache = TransformCache(session)
    await cache.store_many({"first string": "FIRST STRING"})
    await session.commit()

    await cache.store_many({"first string": "FIRST STRING"})
    await session.commit()

    assert await cache.get_many(["first string"]) == {"first string": "FIRST STRING"}


async def test_non_ascii_sources_round_trip(session: AsyncSession) -> None:
    cache = TransformCache(session)
    await cache.store_many({"перший рядок": "ПЕРШИЙ РЯДОК"})
    await session.commit()

    assert await cache.get_many(["перший рядок"]) == {"перший рядок": "ПЕРШИЙ РЯДОК"}
