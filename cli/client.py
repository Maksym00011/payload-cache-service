"""HTTP client for the caching service."""

from types import TracebackType
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError


class UnexpectedResponseError(Exception):
    """The service answered with something this client cannot read.

    Anything can sit between the client and the service — a proxy, a login
    page, a different service on the same port — so a 200 is not a promise that
    the body is the payload API's.
    """


class CreatedPayload(BaseModel):
    id: UUID
    created: bool
    message: str


class PayloadOutput(BaseModel):
    output: str


def _parse[ModelT: BaseModel](model: type[ModelT], response: httpx.Response, what: str) -> ModelT:
    """Read the body as `model`, or say plainly that it is not ours.

    A 2xx is no promise that the body came from this API: a proxy, a login page
    or another service on the same port can answer too.
    """
    try:
        return model.model_validate_json(response.content)
    except ValidationError as error:
        raise UnexpectedResponseError(
            f"{what} answered {response.status_code} with a body this client "
            f"cannot read: {response.text[:120]!r}"
        ) from error


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
        return _parse(CreatedPayload, response, "POST /payload")

    async def read(self, payload_id: UUID) -> str:
        response = await self._client.get(f"/payload/{payload_id}")
        response.raise_for_status()
        return _parse(PayloadOutput, response, f"GET /payload/{payload_id}").output
