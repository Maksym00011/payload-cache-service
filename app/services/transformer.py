"""The "transformer function" that the task models as an external service.

The interface takes a batch on purpose. The task asks to minimise the number of
calls, so the service collects every cache miss of a request and sends them in
one call instead of one call per string.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol


class Transformer(Protocol):
    """What the payload service needs from the external transformer."""

    async def transform_many(self, values: Sequence[str]) -> list[str]:
        """Transform every value, returning results in the same order."""
        ...


class UppercaseTransformer:
    """Stand-in for the real service: uppercases the strings, slowly.

    `calls` counts round trips. The tests assert on it to prove the cache
    really prevents repeated work.
    """

    def __init__(self, latency_seconds: float = 0.05) -> None:
        self._latency_seconds = latency_seconds
        self.calls = 0

    async def transform_many(self, values: Sequence[str]) -> list[str]:
        self.calls += 1
        # One sleep per call, not per value: a batch endpoint pays the network
        # round trip once.
        await asyncio.sleep(self._latency_seconds)
        return [value.upper() for value in values]
