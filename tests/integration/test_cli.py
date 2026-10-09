"""The CLI driven against the real app in process."""

import json

import httpx
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


async def test_a_body_the_client_cannot_read_is_reported_not_raised() -> None:
    """Something other than the service can answer on that port: a proxy, a
    login page. The report must survive it."""

    def answer_with_html(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy page</html>")

    settings = CliSettings(_cli_parse_args=["-j", json.dumps(SAMPLE), "-r", "3"])

    report = await run(
        settings,
        PayloadRequest(**SAMPLE),
        transport=httpx.MockTransport(answer_with_html),
    )

    assert report["iterations"] == []
    assert "cannot read" in report["error"]


async def test_a_body_with_the_wrong_shape_is_reported_too() -> None:
    def answer_with_other_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    settings = CliSettings(_cli_parse_args=["-j", json.dumps(SAMPLE)])

    report = await run(
        settings,
        PayloadRequest(**SAMPLE),
        transport=httpx.MockTransport(answer_with_other_json),
    )

    assert "cannot read" in report["error"]
