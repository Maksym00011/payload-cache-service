"""Errors the service layer raises, free of HTTP concepts.

The API layer maps these to status codes; the service itself stays usable from
a worker or a script.
"""


class TransformerError(RuntimeError):
    """The transformer answered in a way we cannot use."""


class TransformerTimeoutError(TransformerError):
    """The transformer did not answer in time."""
