"""HTTP routes. They translate requests into service calls and nothing more."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import PayloadServiceDep
from app.schemas import PayloadCreate, PayloadCreated, PayloadRead

router = APIRouter()


@router.get("/health", summary="Readiness probe")
async def health(request: Request) -> dict[str, str]:
    """Touch the database, so a probe cannot report "ok" while it is down."""
    engine: AsyncEngine = request.app.state.engine
    async with engine.connect() as connection:
        await connection.execute(sql_text("SELECT 1"))

    return {"status": "ok"}


@router.post(
    "/payload",
    response_model=PayloadCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a payload, or reuse the one made for the same input",
)
async def create_payload(
    request: PayloadCreate,
    service: PayloadServiceDep,
    response: Response,
) -> PayloadCreated:
    payload, created = await service.create(request)

    if not created:
        # A repeat is not a creation, so it answers 200 rather than 201.
        response.status_code = status.HTTP_200_OK

    return PayloadCreated(
        id=payload.id,
        created=created,
        message="payload created" if created else "payload already existed",
    )


@router.get(
    "/payload/{payload_id}",
    response_model=PayloadRead,
    summary="Read a generated payload",
)
async def read_payload(payload_id: UUID, service: PayloadServiceDep) -> PayloadRead:
    payload = await service.get(payload_id)
    if payload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="payload not found")

    return PayloadRead(output=payload.output)
