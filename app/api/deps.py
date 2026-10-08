"""Dependency providers.

The engine, the session factory and the transformer live on `app.state`, so a
test can build an app with a fake transformer instead of patching globals.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.services.cache import TransformCache
from app.services.payload import PayloadService
from app.services.transformer import TimeoutTransformer, Transformer


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request, closed when the request ends."""
    async with request.app.state.session_factory() as session:
        yield session


def get_transformer(request: Request) -> Transformer:
    """Wrap the configured transformer in the call timeout.

    Applying it here rather than at startup means a transformer injected by a
    test runs under the same policy as the real one.
    """
    settings: Settings = request.app.state.settings
    transformer: Transformer = request.app.state.transformer
    return TimeoutTransformer(transformer, settings.transformer_timeout_seconds)


def get_payload_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    transformer: Annotated[Transformer, Depends(get_transformer)],
) -> PayloadService:
    return PayloadService(
        session=session,
        cache=TransformCache(session),
        transformer=transformer,
    )


PayloadServiceDep = Annotated[PayloadService, Depends(get_payload_service)]
