"""HTTP routes. They translate requests into service calls and nothing more."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import PayloadServiceDep
from app.schemas import PayloadCreate, PayloadCreated, PayloadRead

router = APIRouter()


# A probe that hangs is as bad as one that lies: the orchestrator would wait
# instead of restarting the container.
HEALTH_TIMEOUT_SECONDS = 5.0


@router.get("/health", summary="Readiness probe")
async def health(request: Request) -> dict[str, str]:
    """Touch the database, so a probe cannot report "ok" while it is down."""
    engine: AsyncEngine = request.app.state.engine
    async with asyncio.timeout(HEALTH_TIMEOUT_SECONDS), engine.connect() as connection:
        await connection.execute(sql_text("SELECT 1"))

    return {"status": "ok"}


@router.post(
    "/payload",
    response_model=PayloadCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a payload, or reuse the one made for the same input",
    responses={
        status.HTTP_200_OK: {"description": "An identical payload already existed"},
        status.HTTP_502_BAD_GATEWAY: {"description": "The transformer misbehaved"},
        status.HTTP_504_GATEWAY_TIMEOUT: {"description": "The transformer timed out"},
    },
)
async def create_payload(
    request: PayloadCreate,
    service: PayloadServiceDep,
    response: Response,
) -> PayloadCreated:
    payload, created = await service.create(request.list_1, request.list_2)

    if not created:
        # A repeat is not a creation, so it answers 200 rather than 201.
        response.status_code = status.HTTP_200_OK

    # Point at the payload either way, so a client never has to build the URL.
    response.headers["Location"] = f"/payload/{payload.id}"

    return PayloadCreated(
        id=payload.id,
        created=created,
        message="payload created" if created else "payload already existed",
    )


@router.get(
    "/payload/{payload_id}",
    response_model=PayloadRead,
    summary="Read a generated payload",
    responses={status.HTTP_404_NOT_FOUND: {"description": "No payload with that id"}},
)
async def read_payload(payload_id: UUID, service: PayloadServiceDep) -> PayloadRead:
    payload = await service.get(payload_id)
    if payload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="payload not found")

    return PayloadRead(output=payload.output)
