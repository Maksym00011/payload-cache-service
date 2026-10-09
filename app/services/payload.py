"""Creating and reading payloads.

This is where the requirement to keep transformer calls low is actually met:
strings are deduplicated inside the request, looked up in the cache in one
query, and whatever is left over is sent to the transformer in a single call.
"""

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models import Payload
from app.domain.fingerprint import payload_fingerprint
from app.domain.interleave import interleave, render_output
from app.services.cache import TransformCache
from app.services.errors import TransformerError
from app.services.transformer import Transformer

logger = logging.getLogger(__name__)


class PayloadService:
    def __init__(
        self,
        session: AsyncSession,
        cache: TransformCache,
        transformer: Transformer,
    ) -> None:
        self._session = session
        self._cache = cache
        self._transformer = transformer

    async def create(self, list_1: Sequence[str], list_2: Sequence[str]) -> tuple[Payload, bool]:
        """Return the payload for this input, and whether it was created now.

        Takes the two lists rather than the request model, so the service does
        not depend on the HTTP layer's contract.
        """
        fingerprint = payload_fingerprint(list_1, list_2)

        # Same input as before: hand back the same id and touch nothing else.
        existing = await self._find_by_fingerprint(fingerprint)
        if existing is not None:
            logger.info("payload %s reused for a repeated request", existing.id)
            return existing, False

        transforms = await self._resolve_transforms([*list_1, *list_2])
        output = render_output(transforms[value] for value in interleave(list_1, list_2))

        payload = Payload(
            fingerprint=fingerprint,
            source_lists={"list_1": list(list_1), "list_2": list(list_2)},
            output=output,
        )
        self._session.add(payload)

        try:
            # One transaction for the new cache entries and the payload.
            await self._session.commit()
        except IntegrityError:
            # A concurrent request with the same input committed first. Its
            # cache entries cover the same strings, so nothing is lost by
            # dropping ours and returning the payload that won.
            await self._session.rollback()
            winner = await self._find_by_fingerprint(fingerprint)
            if winner is None:
                raise
            logger.info("payload %s won a concurrent create", winner.id)
            return winner, False

        logger.info("payload %s created", payload.id)
        return payload, True

    async def get(self, payload_id: UUID) -> Payload | None:
        return await self._session.get(Payload, payload_id)

    async def _resolve_transforms(self, values: list[str]) -> dict[str, str]:
        """Map every value to its transformed form, calling out at most once."""
        # dict.fromkeys deduplicates but keeps order, so a string repeated
        # within or across the two lists is only ever transformed once.
        unique = list(dict.fromkeys(values))

        cached = await self._cache.get_many(unique)
        missing = [value for value in unique if value not in cached]
        logger.info(
            "%d unique strings: %d from cache, %d to transform",
            len(unique),
            len(cached),
            len(missing),
        )
        if not missing:
            return cached

        # Give the pooled connection back before the slow remote call. Holding
        # it would cap concurrent transformer calls at the pool size, and the
        # health probe competes for the same pool exactly when the service is
        # busy. Nothing is lost: the read above is already in `cached`.
        await self._session.rollback()

        transformed = await self._transformer.transform_many(missing)
        self._check_transformer_contract(missing, transformed)
        fresh = dict(zip(missing, transformed, strict=True))
        await self._cache.store_many(fresh)
        return cached | fresh

    @staticmethod
    def _check_transformer_contract(asked: list[str], answered: list[str]) -> None:
        """A broken upstream is a bad gateway, not an internal error.

        Without the type check, a null slips through to the database and
        surfaces as an unhandled integrity error instead of a 502.
        """
        if len(answered) != len(asked):
            raise TransformerError(
                f"asked the transformer for {len(asked)} values, got {len(answered)}"
            )
        if not all(isinstance(value, str) for value in answered):
            raise TransformerError("the transformer returned a value that is not a string")

    async def _find_by_fingerprint(self, fingerprint: str) -> Payload | None:
        statement = select(Payload).where(col(Payload.fingerprint) == fingerprint)
        return (await self._session.exec(statement)).first()
