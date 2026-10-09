"""Content hashes used as cache keys.

We index hashes rather than the strings themselves. Inputs are arbitrary user
text, and a PostgreSQL btree index refuses values larger than roughly 2.7 KB,
so indexing the raw string would fail on long input. A sha256 hex digest is
always 64 characters.
"""

import hashlib
import json
from collections.abc import Sequence

# Bump this when the output format or the transformer contract changes. It is
# part of both keys below, so old payloads and old cached transforms are both
# superseded rather than served stale.
FINGERPRINT_VERSION = "v1"


def hash_source(value: str) -> str:
    """Cache key for one string sent to the transformer.

    The version is part of the key, so bumping it really does invalidate the
    cached transforms and not just the payload fingerprints.
    """
    return hashlib.sha256(f"{FINGERPRINT_VERSION}:{value}".encode()).hexdigest()


def payload_fingerprint(first: Sequence[str], second: Sequence[str]) -> str:
    """Stable key for one payload request, so a repeat reuses the same id.

    The input is serialised as JSON instead of being concatenated: with a plain
    separator, `["a,b"]` and `["a", "b"]` would hash to the same value.
    """
    canonical = json.dumps(
        {
            "version": FINGERPRINT_VERSION,
            "list_1": list(first),
            "list_2": list(second),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
