"""The CLI driven against the real app in process."""

import json

from httpx import ASGITransport

from app.core.config import Settings
from app.main import create_app
from cli.__main__ import run
from cli.settings import CliSettings, PayloadRequest
from tests.doubles import RecordingTransformer

SAMPLE = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}
SAMPLE_OUTPUT = (
    "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"
)


async def test_repeating_a_payload_calls_the_transformer_once(
    settings: Settings, transformer: RecordingTransformer
) -> None:
    """What --repeat is for: the same id every time, one call to the upstream."""
    app = create_app(settings)
    app.state.transformer = transformer
    cli_settings = CliSettings(_cli_parse_args=["-j", json.dumps(SAMPLE), "-r", "3"])

    async with app.router.lifespan_context(app):
        report = await run(cli_settings, PayloadRequest(**SAMPLE), transport=ASGITransport(app=app))

    assert report["output"] == SAMPLE_OUTPUT
    assert len(report["iterations"]) == 3
    assert report["summary"]["unique_payload_ids"] == 1
    assert report["summary"]["payloads_created"] == 1
    assert transformer.calls == 1


async def test_only_the_first_iteration_reports_a_creation(
    settings: Settings, transformer: RecordingTransformer
) -> None:
    app = create_app(settings)
    app.state.transformer = transformer
    cli_settings = CliSettings(_cli_parse_args=["-j", json.dumps(SAMPLE), "-r", "2"])

    async with app.router.lifespan_context(app):
        report = await run(cli_settings, PayloadRequest(**SAMPLE), transport=ASGITransport(app=app))

    assert [step["created"] for step in report["iterations"]] == [True, False]
