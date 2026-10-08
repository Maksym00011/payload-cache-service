import asyncio

import pytest

from app.services.errors import TransformerTimeoutError
from app.services.transformer import TimeoutTransformer, UppercaseTransformer
from tests.doubles import HangingTransformer


async def test_transform_many_uppercases_every_value():
    transformer = UppercaseTransformer(latency_seconds=0)

    assert await transformer.transform_many(["first string", "b"]) == [
        "FIRST STRING",
        "B",
    ]


async def test_transform_many_keeps_the_input_order():
    transformer = UppercaseTransformer(latency_seconds=0)

    assert await transformer.transform_many(["c", "a", "b"]) == ["C", "A", "B"]


async def test_a_batch_counts_as_a_single_call():
    transformer = UppercaseTransformer(latency_seconds=0)

    await transformer.transform_many(["a", "b", "c"])

    assert transformer.calls == 1


async def test_latency_is_paid_once_per_batch(monkeypatch):
    """The cost we are minimising is the round trip, not the per-value work."""
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    transformer = UppercaseTransformer(latency_seconds=0.2)

    await transformer.transform_many(["a", "b", "c"])

    assert sleeps == [0.2]


async def test_the_timeout_wrapper_gives_up_on_a_hanging_transformer():
    wrapped = TimeoutTransformer(HangingTransformer(), timeout_seconds=0.01)

    with pytest.raises(TransformerTimeoutError):
        await wrapped.transform_many(["a"])


async def test_the_timeout_wrapper_passes_results_through():
    wrapped = TimeoutTransformer(UppercaseTransformer(latency_seconds=0), timeout_seconds=1)

    assert await wrapped.transform_many(["a"]) == ["A"]
