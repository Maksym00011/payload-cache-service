import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cli.__main__ import load_request, write_report
from cli.settings import CliSettings

SAMPLE = {"list_1": ["first string"], "list_2": ["other string"]}


def test_a_payload_given_as_json_is_parsed():
    settings = CliSettings(_cli_parse_args=["-j", json.dumps(SAMPLE)])

    assert load_request(settings).list_1 == ["first string"]


def test_a_payload_is_read_from_a_file(tmp_path: Path):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    settings = CliSettings(_cli_parse_args=["-i", str(path)])

    assert load_request(settings).list_2 == ["other string"]


def test_a_payload_is_read_from_stdin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(SAMPLE)))
    settings = CliSettings(_cli_parse_args=["-i", "-"])

    assert load_request(settings).list_1 == ["first string"]


def test_a_missing_file_is_an_error():
    settings = CliSettings(_cli_parse_args=["-i", "/nope/payload.json"])

    with pytest.raises(OSError):
        load_request(settings)


def test_malformed_json_is_an_error():
    settings = CliSettings(_cli_parse_args=["-j", "{not json"])

    with pytest.raises(ValidationError):
        load_request(settings)


def test_the_report_goes_to_a_file(tmp_path: Path):
    path = tmp_path / "report.json"
    settings = CliSettings(_cli_parse_args=["-j", json.dumps(SAMPLE), "-o", str(path)])

    write_report(settings, {"host": "http://localhost:8000"})

    assert json.loads(path.read_text(encoding="utf-8"))["host"] == "http://localhost:8000"
