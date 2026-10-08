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

import cli.client as client_module
from cli.settings import STDIO, CliSettings, PayloadRequest

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_BAD_USAGE = 2


def load_request(settings: CliSettings) -> PayloadRequest:
    """Read the payload from --json, from a file, or from stdin."""
    if settings.json_payload is not None:
        raw = settings.json_payload
    elif settings.input_file == STDIO:
        raw = sys.stdin.read()
    else:
        raw = Path(str(settings.input_file)).read_text(encoding="utf-8")

    return PayloadRequest.model_validate_json(raw)


async def run(
    settings: CliSettings,
    request: PayloadRequest,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    body = request.model_dump()
    iterations: list[dict[str, Any]] = []
    output = ""

    async with client_module.CacheClient(str(settings.host), transport=transport) as client:
        for number in range(1, settings.repeat + 1):
            started = perf_counter()
            created = await client.create(body)
            post_ms = (perf_counter() - started) * 1000

            started = perf_counter()
            output = await client.read(created.id)
            get_ms = (perf_counter() - started) * 1000

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

    return {
        "host": str(settings.host),
        "repeat": settings.repeat,
        "output": output,
        "iterations": iterations,
        "summary": {
            # One id across every iteration is the point: the service reuses it.
            "unique_payload_ids": len({step["payload_id"] for step in iterations}),
            "payloads_created": sum(1 for step in iterations if step["created"]),
            "fastest_post_ms": min(step["post_ms"] for step in iterations),
            "slowest_post_ms": max(step["post_ms"] for step in iterations),
        },
    }


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
    except (OSError, ValidationError) as error:
        return fail(str(error), EXIT_BAD_USAGE)

    try:
        report = asyncio.run(run(settings, request))
    except httpx.HTTPStatusError as error:
        return fail(
            f"the service answered {error.response.status_code}: {error.response.text}",
            EXIT_FAILURE,
        )
    except httpx.HTTPError as error:
        return fail(f"could not reach {settings.host}: {error}", EXIT_FAILURE)

    write_report(settings, report)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
