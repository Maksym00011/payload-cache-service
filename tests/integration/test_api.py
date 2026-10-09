"""End to end tests over HTTP, with a fake transformer we can count."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.main import create_app
from app.schemas import MAX_LIST_LENGTH, MAX_STRING_LENGTH
from app.services.transformer import Transformer
from tests.doubles import (
    HangingTransformer,
    RecordingTransformer,
    ShortChangingTransformer,
)

ClientFactory = Callable[[Transformer], AbstractAsyncContextManager[AsyncClient]]

# The example straight out of the task description.
SAMPLE_REQUEST = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}
SAMPLE_OUTPUT = (
    "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"
)


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_create_then_read_matches_the_task_example(client: AsyncClient) -> None:
    created = await client.post("/payload", json=SAMPLE_REQUEST)

    assert created.status_code == 201
    assert created.json()["created"] is True

    read = await client.get(f"/payload/{created.json()['id']}")

    assert read.status_code == 200
    assert read.json() == {"output": SAMPLE_OUTPUT}


async def test_a_first_request_transforms_everything_in_one_call(
    client: AsyncClient, transformer: RecordingTransformer
) -> None:
    response = await client.post("/payload", json=SAMPLE_REQUEST)

    assert response.status_code == 201
    assert transformer.calls == 1
    assert len(transformer.batches[0]) == 6


async def test_repeating_a_request_reuses_the_id_and_calls_nobody(
    client: AsyncClient, transformer: RecordingTransformer
) -> None:
    first = await client.post("/payload", json=SAMPLE_REQUEST)

    second = await client.post("/payload", json=SAMPLE_REQUEST)

    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["id"] == first.json()["id"]
    assert transformer.calls == 1


async def test_only_strings_that_are_new_reach_the_transformer(
    client: AsyncClient, transformer: RecordingTransformer
) -> None:
    first = await client.post("/payload", json=SAMPLE_REQUEST)
    assert first.status_code == 201

    second = await client.post(
        "/payload",
        json={
            "list_1": ["first string", "fourth string"],
            "list_2": ["other string", "second string"],
        },
    )

    assert second.status_code == 201
    assert transformer.calls == 2
    assert transformer.batches[1] == ["fourth string"]


async def test_a_string_repeated_in_one_request_is_transformed_once(
    client: AsyncClient, transformer: RecordingTransformer
) -> None:
    response = await client.post(
        "/payload",
        json={"list_1": ["same", "same"], "list_2": ["same", "other"]},
    )

    assert response.status_code == 201
    assert transformer.batches == [["same", "other"]]


async def test_lists_of_different_length_are_rejected(client: AsyncClient) -> None:
    response = await client.post("/payload", json={"list_1": ["a"], "list_2": ["x", "y"]})

    assert response.status_code == 422
    assert "same length" in response.text


async def test_empty_lists_are_rejected(client: AsyncClient) -> None:
    response = await client.post("/payload", json={"list_1": [], "list_2": []})

    assert response.status_code == 422


async def test_reading_an_unknown_payload_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/payload/{uuid4()}")

    assert response.status_code == 404


async def test_reading_a_malformed_id_returns_422(client: AsyncClient) -> None:
    response = await client.get("/payload/not-a-uuid")

    assert response.status_code == 422


async def test_concurrent_identical_requests_produce_one_payload(
    client: AsyncClient, transformer: RecordingTransformer
) -> None:
    """Five racing requests must settle on a single payload and a single id.

    The number of transformer calls is deliberately not asserted: without a
    single-flight lock, racing requests can all miss the cache. That is the
    documented trade-off, and the unique constraint keeps the data correct.
    """
    responses = await asyncio.gather(
        *(client.post("/payload", json=SAMPLE_REQUEST) for _ in range(5))
    )

    assert {response.json()["id"] for response in responses} == {responses[0].json()["id"]}
    assert sum(response.status_code == 201 for response in responses) == 1


async def test_a_request_over_the_total_size_limit_is_rejected(client: AsyncClient) -> None:
    """Per-item limits alone would still let one call carry megabytes."""
    big = "x" * 4000
    body = {"list_1": [big] * 30, "list_2": [big] * 30}

    response = await client.post("/payload", json=body)

    assert response.status_code == 422
    assert "must not exceed" in response.text
    # The rejected request must not come back with the answer. At the size
    # limit that would mean echoing hundreds of kilobytes to the caller, and
    # into the access log with it.
    assert big not in response.text
    assert len(response.content) < 1000


async def test_an_unresponsive_transformer_answers_504(make_client: ClientFactory) -> None:
    async with make_client(HangingTransformer()) as client:
        response = await client.post("/payload", json=SAMPLE_REQUEST)

    assert response.status_code == 504


async def test_a_transformer_breaking_its_contract_answers_502(
    make_client: ClientFactory,
) -> None:
    """Wrong number of results is the upstream's fault, not a 500 on our side."""
    async with make_client(ShortChangingTransformer()) as client:
        response = await client.post("/payload", json=SAMPLE_REQUEST)

    assert response.status_code == 502


async def test_requests_differing_only_in_list_2_get_different_payloads(
    client: AsyncClient,
) -> None:
    """The fingerprint must cover both lists, not just the first one."""
    first = await client.post("/payload", json={"list_1": ["same"], "list_2": ["one"]})
    second = await client.post("/payload", json={"list_1": ["same"], "list_2": ["two"]})

    assert first.json()["id"] != second.json()["id"]
    assert second.status_code == 201

    outputs = [
        (await client.get(f"/payload/{response.json()['id']}")).json()["output"]
        for response in (first, second)
    ]
    assert outputs == ["SAME, ONE", "SAME, TWO"]


async def test_a_single_item_over_the_length_limit_is_rejected(client: AsyncClient) -> None:
    too_long = "x" * (MAX_STRING_LENGTH + 1)

    response = await client.post("/payload", json={"list_1": [too_long], "list_2": ["ok"]})

    assert response.status_code == 422


async def test_a_list_over_the_length_limit_is_rejected(client: AsyncClient) -> None:
    too_many = ["x"] * (MAX_LIST_LENGTH + 1)

    response = await client.post("/payload", json={"list_1": too_many, "list_2": too_many})

    assert response.status_code == 422


async def test_unknown_fields_are_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/payload",
        json={"list_1": ["a"], "list_2": ["b"], "list_3": ["typo"]},
    )

    assert response.status_code == 422


async def test_a_created_payload_is_announced_with_its_location(client: AsyncClient) -> None:
    response = await client.post("/payload", json=SAMPLE_REQUEST)

    assert response.headers["location"] == f"/payload/{response.json()['id']}"


async def test_health_fails_when_the_database_is_unreachable(settings: Settings) -> None:
    """Guards the database touch in /health: without it the probe reported "ok"
    while the database was gone, and the container healthcheck relies on it."""
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        broken = create_async_engine("sqlite+aiosqlite:////nonexistent-dir/cache.db")
        app.state.engine = broken
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/health")
        await broken.dispose()

    # 503, not 500: an unreachable database means "not ready", which is what a
    # probe and a load balancer need to hear.
    assert response.status_code == 503


async def test_a_repeat_costs_one_query_and_no_writes(
    settings: Settings, transformer: RecordingTransformer
) -> None:
    """The headline claim, measured over HTTP rather than at the cache layer."""
    app = create_app(settings)
    app.state.transformer = transformer

    async with app.router.lifespan_context(app):
        statements: list[str] = []

        # The listener signature is fixed by SQLAlchemy; only the statement
        # matters here.
        def record(*arguments: object) -> None:
            statements.append(str(arguments[2]))

        event.listen(app.state.engine.sync_engine, "before_cursor_execute", record)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/payload", json=SAMPLE_REQUEST)
            statements.clear()
            repeat = await client.post("/payload", json=SAMPLE_REQUEST)
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", record)

    assert repeat.status_code == 200
    assert transformer.calls == 1
    kinds = [statement.lstrip().split(maxsplit=1)[0].upper() for statement in statements]
    assert kinds.count("SELECT") == 1
    assert "INSERT" not in kinds


async def test_a_busy_database_answers_503_not_500(
    settings: Settings, transformer: RecordingTransformer
) -> None:
    """SQLite allows one writer, so a burst can fail with "database is locked".
    That is a retry, not a server fault."""
    app = create_app(settings)
    app.state.transformer = transformer

    async with app.router.lifespan_context(app):
        broken = create_async_engine("sqlite+aiosqlite:////nonexistent-dir/cache.db")
        app.state.session_factory = async_sessionmaker(
            broken, class_=AsyncSession, expire_on_commit=False
        )
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post("/payload", json=SAMPLE_REQUEST)
        await broken.dispose()

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"


async def test_an_oversized_body_is_refused_before_it_is_parsed(
    client: AsyncClient,
) -> None:
    """The schema limit only applies after decoding, so a large body used to be
    held in memory before being rejected."""
    body = "x" * (600 * 1024)

    response = await client.post(
        "/payload", content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 413
    assert "must not exceed" in response.text
