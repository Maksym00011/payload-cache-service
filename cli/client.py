"""HTTP client for the caching service."""

from dataclasses import dataclass
from types import TracebackType
from uuid import UUID

import httpx


@dataclass(frozen=True)
class CreatedPayload:
    id: UUID
    created: bool
    message: str


class CacheClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # `transport` is a seam for tests: it lets them drive the app in process
        # instead of binding a port.
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout_seconds, transport=transport
        )

    async def __aenter__(self) -> "CacheClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def create(self, body: dict[str, list[str]]) -> CreatedPayload:
        response = await self._client.post("/payload", json=body)
        response.raise_for_status()
        data = response.json()
        return CreatedPayload(id=UUID(data["id"]), created=data["created"], message=data["message"])

    async def read(self, payload_id: UUID) -> str:
        response = await self._client.get(f"/payload/{payload_id}")
        response.raise_for_status()
        return str(response.json()["output"])
