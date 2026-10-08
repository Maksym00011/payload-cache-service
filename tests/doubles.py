"""Stand-ins for the transformer.

The service depends on a Protocol, so each of these is a few lines and needs no
mocking library.
"""

import asyncio
from collections.abc import Sequence


class RecordingTransformer:
    """Remembers every batch, so tests can assert which strings went out."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def transform_many(self, values: Sequence[str]) -> list[str]:
        self.batches.append(list(values))
        return [value.upper() for value in values]

    @property
    def calls(self) -> int:
        return len(self.batches)


class HangingTransformer:
    """Never answers, standing in for an unresponsive external service."""

    async def transform_many(self, values: Sequence[str]) -> list[str]:
        await asyncio.sleep(60)
        return list(values)


class ShortChangingTransformer:
    """Returns fewer results than asked for, breaking its own contract."""

    async def transform_many(self, values: Sequence[str]) -> list[str]:
        return [value.upper() for value in values][:-1]
