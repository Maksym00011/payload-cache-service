"""The HTTP contract: what the API accepts and what it returns."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# Guardrails so one request cannot ask us to hash and store megabytes. These
# live next to the contract they describe rather than in deployment settings.
MAX_LIST_LENGTH = 1000
MAX_STRING_LENGTH = 4096
# Per-item limits alone would still allow 8 MB of text in one call, which we
# would hash, transform and store twice. Cap the request as a whole.
MAX_TOTAL_CHARACTERS = 200_000

PayloadString = Annotated[str, Field(max_length=MAX_STRING_LENGTH)]
PayloadList = Annotated[list[PayloadString], Field(min_length=1, max_length=MAX_LIST_LENGTH)]


class PayloadCreate(BaseModel):
    """Two lists of strings of the same length."""

    list_1: PayloadList
    list_2: PayloadList

    @model_validator(mode="after")
    def lists_must_have_the_same_length(self) -> "PayloadCreate":
        if len(self.list_1) != len(self.list_2):
            raise ValueError("list_1 and list_2 must have the same length")
        return self

    @model_validator(mode="after")
    def request_must_stay_within_the_size_limit(self) -> "PayloadCreate":
        total = sum(map(len, self.list_1)) + sum(map(len, self.list_2))
        if total > MAX_TOTAL_CHARACTERS:
            raise ValueError(
                f"the two lists together must not exceed {MAX_TOTAL_CHARACTERS} characters"
            )
        return self


class PayloadCreated(BaseModel):
    """Answer to POST: the confirmation and the id the task asks for."""

    id: UUID
    message: str
    # False when an identical payload already existed and its id was reused.
    created: bool


class PayloadRead(BaseModel):
    """Answer to GET, exactly the shape given in the task."""

    output: str
