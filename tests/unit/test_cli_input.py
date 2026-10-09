import io
import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cli.__main__ import load_request, main, write_report
from cli.settings import CliSettings

SAMPLE = {"list_1": ["first string"], "list_2": ["other string"]}


def stub_run(
    report: dict[str, object],
) -> Callable[[Coroutine[Any, Any, Any]], dict[str, object]]:
    """Replace asyncio.run, closing the coroutine so it is not left pending."""

    def run(coroutine: Coroutine[Any, Any, Any]) -> dict[str, object]:
        coroutine.close()
        return report

    return run


def test_a_payload_given_as_json_is_parsed() -> None:
    settings = CliSettings(_cli_parse_args=["-j", json.dumps(SAMPLE)])

    assert load_request(settings).list_1 == ["first string"]


def test_a_payload_is_read_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    settings = CliSettings(_cli_parse_args=["-i", str(path)])

    assert load_request(settings).list_2 == ["other string"]


def test_a_payload_is_read_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(SAMPLE)))
    settings = CliSettings(_cli_parse_args=["-i", "-"])

    assert load_request(settings).list_1 == ["first string"]


def test_a_missing_file_is_an_error() -> None:
    settings = CliSettings(_cli_parse_args=["-i", "/nope/payload.json"])

    with pytest.raises(OSError):
        load_request(settings)


def test_malformed_json_is_an_error() -> None:
    settings = CliSettings(_cli_parse_args=["-j", "{not json"])

    with pytest.raises(ValidationError):
        load_request(settings)


def test_the_report_goes_to_a_file(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    settings = CliSettings(_cli_parse_args=["-j", json.dumps(SAMPLE), "-o", str(path)])

    write_report(settings, {"host": "http://localhost:8000"})

    assert json.loads(path.read_text(encoding="utf-8"))["host"] == "http://localhost:8000"


def test_a_failed_output_write_still_prints_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run is already paid for, so the report must not be lost."""
    unwritable = tmp_path / "missing-dir" / "report.json"
    monkeypatch.setattr("sys.argv", ["cache-cli", "-j", json.dumps(SAMPLE), "-o", str(unwritable)])
    monkeypatch.setattr(
        "cli.__main__.asyncio.run", stub_run({"host": "http://x", "iterations": []})
    )

    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "http://x" in captured.out
    assert "could not write" in captured.err


def test_bad_arguments_exit_with_two(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["cache-cli", "-j", json.dumps(SAMPLE), "-r", "0"])

    assert main() == 2
    assert "greater than or equal to 1" in capsys.readouterr().err


def test_unreadable_input_exits_with_two(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["cache-cli", "-i", "/nope/payload.json"])

    assert main() == 2
    assert "FileNotFoundError" in capsys.readouterr().err


def test_a_failed_iteration_is_reported_and_exits_with_one(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["cache-cli", "-j", json.dumps(SAMPLE)])
    monkeypatch.setattr(
        "cli.__main__.asyncio.run",
        stub_run({"iterations": [], "error": "iteration 1: ConnectError"}),
    )

    assert main() == 1
    assert "ConnectError" in capsys.readouterr().err


def test_a_file_that_is_not_utf8_exits_with_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A UnicodeDecodeError is a ValueError, not an OSError, so it used to
    escape as a traceback."""
    broken = tmp_path / "payload.json"
    broken.write_bytes(b"\xff\xfe\x00bad")
    monkeypatch.setattr("sys.argv", ["cache-cli", "-i", str(broken)])

    assert main() == 2
    assert "UnicodeDecodeError" in capsys.readouterr().err
