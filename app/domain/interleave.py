"""Building the payload output from two lists of strings."""

from collections.abc import Iterable, Sequence

OUTPUT_SEPARATOR = ", "


def interleave(first: Sequence[str], second: Sequence[str]) -> list[str]:
    """Return the items of both lists alternating, starting with `first`."""
    if len(first) != len(second):
        raise ValueError(
            f"both lists must have the same length, got {len(first)} and {len(second)}"
        )

    # strict=True keeps the invariant enforced even if the check above is ever
    # moved or removed.
    return [value for pair in zip(first, second, strict=True) for value in pair]


def render_output(values: Iterable[str]) -> str:
    """Join payload items into the single string the API returns."""
    return OUTPUT_SEPARATOR.join(values)
