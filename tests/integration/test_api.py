"""End to end tests over HTTP, with a fake transformer we can count."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

from httpx import AsyncClient

from tests.doubles import (
    HangingTransformer,
    RecordingTransformer,
    ShortChangingTransformer,
)

ClientFactory = Callable[[object], AbstractAsyncContextManager[AsyncClient]]

# The example straight out of the task description.
SAMPLE_REQUEST = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}
SAMPLE_OUTPUT = (
    "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"
)


async def test_health(client: AsyncClient):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_create_then_read_matches_the_task_example(client: AsyncClient):
    created = await client.post("/payload", json=SAMPLE_REQUEST)

    assert created.status_code == 201
    assert created.json()["created"] is True

    read = await client.get(f"/payload/{created.json()['id']}")

    assert read.status_code == 200
    assert read.json() == {"output": SAMPLE_OUTPUT}


async def test_a_first_request_transforms_everything_in_one_call(
    client: AsyncClient, transformer: RecordingTransformer
):
    await client.post("/payload", json=SAMPLE_REQUEST)

    assert transformer.calls == 1
    assert len(transformer.batches[0]) == 6


async def test_repeating_a_request_reuses_the_id_and_calls_nobody(
    client: AsyncClient, transformer: RecordingTransformer
):
    first = await client.post("/payload", json=SAMPLE_REQUEST)

    second = await client.post("/payload", json=SAMPLE_REQUEST)

    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["id"] == first.json()["id"]
    assert transformer.calls == 1


async def test_only_strings_that_are_new_reach_the_transformer(
    client: AsyncClient, transformer: RecordingTransformer
):
    await client.post("/payload", json=SAMPLE_REQUEST)

    await client.post(
        "/payload",
        json={
            "list_1": ["first string", "fourth string"],
            "list_2": ["other string", "second string"],
        },
    )

    assert transformer.calls == 2
    assert transformer.batches[1] == ["fourth string"]


async def test_a_string_repeated_in_one_request_is_transformed_once(
    client: AsyncClient, transformer: RecordingTransformer
):
    await client.post(
        "/payload",
        json={"list_1": ["same", "same"], "list_2": ["same", "other"]},
    )

    assert transformer.batches == [["same", "other"]]


async def test_lists_of_different_length_are_rejected(client: AsyncClient):
    response = await client.post("/payload", json={"list_1": ["a"], "list_2": ["x", "y"]})

    assert response.status_code == 422
    assert "same length" in response.text


async def test_empty_lists_are_rejected(client: AsyncClient):
    response = await client.post("/payload", json={"list_1": [], "list_2": []})

    assert response.status_code == 422


async def test_reading_an_unknown_payload_returns_404(client: AsyncClient):
    response = await client.get(f"/payload/{uuid4()}")

    assert response.status_code == 404


async def test_reading_a_malformed_id_returns_422(client: AsyncClient):
    response = await client.get("/payload/not-a-uuid")

    assert response.status_code == 422


async def test_concurrent_identical_requests_produce_one_payload(
    client: AsyncClient, transformer: RecordingTransformer
):
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


async def test_a_request_over_the_total_size_limit_is_rejected(client: AsyncClient):
    """Per-item limits alone would still let one call carry megabytes."""
    big = "x" * 4000
    response = await client.post("/payload", json={"list_1": [big] * 30, "list_2": [big] * 30})

    assert response.status_code == 422
    assert "characters" in response.text


async def test_an_unresponsive_transformer_answers_504(make_client: ClientFactory):
    async with make_client(HangingTransformer()) as client:
        response = await client.post("/payload", json=SAMPLE_REQUEST)

    assert response.status_code == 504


async def test_a_transformer_breaking_its_contract_answers_502(
    make_client: ClientFactory,
):
    """Wrong number of results is the upstream's fault, not a 500 on our side."""
    async with make_client(ShortChangingTransformer()) as client:
        response = await client.post("/payload", json=SAMPLE_REQUEST)

    assert response.status_code == 502
