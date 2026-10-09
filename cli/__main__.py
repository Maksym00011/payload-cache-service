"""cache-cli: send a payload to the service and report what came back.

Running it with --repeat greater than one is the quickest way to see the cache
work: the first iteration pays for the transformer, the rest do not, and every
iteration gets the same payload id.
"""

import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from pydantic import ValidationError

from cli.client import CacheClient, UnexpectedResponseError
from cli.settings import STDIO, CliSettings, PayloadRequest

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_BAD_USAGE = 2

# Deliberately longer than the service's own transformer timeout, so a slow
# upstream surfaces as the service's 504 rather than as a client-side timeout
# that says nothing about the cause.
CLIENT_TIMEOUT_SECONDS = 30.0


def load_request(settings: CliSettings) -> PayloadRequest:
    """Read the payload from --json, from a file, or from stdin."""
    if settings.json_payload is not None:
        raw = settings.json_payload
    elif settings.input_file == STDIO:
        raw = sys.stdin.read()
    else:
        raw = Path(str(settings.input_file)).read_text(encoding="utf-8")

    return PayloadRequest.model_validate_json(raw)


def describe(error: Exception) -> str:
    """Name the exception type: several httpx errors stringify to nothing."""
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


async def run(
    settings: CliSettings,
    request: PayloadRequest,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Send the payload `--repeat` times and report every iteration.

    A failure stops the loop but keeps the iterations that already succeeded:
    with --repeat they are the measurement the run was made for.
    """
    body = request.model_dump()
    iterations: list[dict[str, Any]] = []
    output = ""
    error: str | None = None

    async with CacheClient(
        str(settings.host), timeout_seconds=CLIENT_TIMEOUT_SECONDS, transport=transport
    ) as client:
        for number in range(1, settings.repeat + 1):
            try:
                started = perf_counter()
                created = await client.create(body)
                post_ms = (perf_counter() - started) * 1000

                started = perf_counter()
                output = await client.read(created.id)
                get_ms = (perf_counter() - started) * 1000
            except httpx.HTTPStatusError as failure:
                error = (
                    f"iteration {number}: the service answered "
                    f"{failure.response.status_code}: {failure.response.text[:200]}"
                )
                break
            except (httpx.HTTPError, UnexpectedResponseError) as failure:
                error = f"iteration {number}: {describe(failure)}"
                break

            iterations.append(
                {
                    "iteration": number,
                    "payload_id": str(created.id),
                    "created": created.created,
                    "message": created.message,
                    "post_ms": round(post_ms, 2),
                    "get_ms": round(get_ms, 2),
                }
            )

    report: dict[str, Any] = {
        "host": str(settings.host),
        "repeat": settings.repeat,
        "output": output,
        "iterations": iterations,
        "summary": {
            # One id across every iteration is the point: the service reuses it.
            "unique_payload_ids": len({step["payload_id"] for step in iterations}),
            "payloads_created": sum(1 for step in iterations if step["created"]),
            "fastest_post_ms": min((step["post_ms"] for step in iterations), default=None),
            "slowest_post_ms": max((step["post_ms"] for step in iterations), default=None),
        },
    }
    if error is not None:
        report["error"] = error

    return report


def write_report(settings: CliSettings, report: dict[str, Any]) -> None:
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if settings.output_file == STDIO:
        sys.stdout.write(text)
    else:
        Path(settings.output_file).write_text(text, encoding="utf-8")


def fail(message: str, code: int) -> int:
    print(f"cache-cli: {message}", file=sys.stderr)
    return code


def main() -> int:
    try:
        settings = CliSettings()
    except ValidationError as error:
        return fail(str(error), EXIT_BAD_USAGE)

    try:
        request = load_request(settings)
    except (OSError, ValueError) as error:
        return fail(describe(error), EXIT_BAD_USAGE)

    report = asyncio.run(run(settings, request))

    try:
        write_report(settings, report)
    except OSError as error:
        # The run is already paid for, so print the report rather than lose it.
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return fail(f"could not write {settings.output_file}: {error}", EXIT_FAILURE)

    if "error" in report:
        return fail(report["error"], EXIT_FAILURE)

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
