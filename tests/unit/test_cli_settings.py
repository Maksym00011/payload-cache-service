import json

import pytest
from pydantic import ValidationError

from cli.settings import CliSettings, PayloadRequest

SAMPLE_JSON = json.dumps(
    {"list_1": ["first string"], "list_2": ["other string"]}, ensure_ascii=False
)


def parse(*args: str) -> CliSettings:
    return CliSettings(_cli_parse_args=list(args))


def test_short_flags():
    settings = parse("-H", "http://service:9000", "-r", "3", "-i", "payload.json")

    assert str(settings.host) == "http://service:9000/"
    assert settings.repeat == 3
    assert settings.input_file == "payload.json"


def test_long_flags():
    settings = parse("--host", "http://service:9000", "--repeat", "2", "--json", SAMPLE_JSON)

    assert settings.repeat == 2
    assert settings.json_payload == SAMPLE_JSON


def test_defaults_point_at_localhost_and_stdout():
    settings = parse("--json", SAMPLE_JSON)

    assert str(settings.host) == "http://localhost:8000/"
    assert settings.repeat == 1
    assert settings.output_file == "-"


def test_a_dash_means_stdin_or_stdout():
    settings = parse("-i", "-", "-o", "-")

    assert settings.input_file == "-"
    assert settings.output_file == "-"


def test_input_and_json_together_are_rejected():
    with pytest.raises(ValidationError, match="exactly one"):
        parse("-i", "payload.json", "-j", SAMPLE_JSON)


def test_neither_input_nor_json_is_rejected():
    with pytest.raises(ValidationError, match="exactly one"):
        parse("-r", "2")


def test_repeat_below_one_is_rejected():
    with pytest.raises(ValidationError):
        parse("-j", SAMPLE_JSON, "-r", "0")


def test_a_host_that_is_not_a_url_is_rejected():
    with pytest.raises(ValidationError):
        parse("-j", SAMPLE_JSON, "-H", "not a url")


def test_payload_lists_must_have_the_same_length():
    with pytest.raises(ValidationError, match="same length"):
        PayloadRequest(list_1=["a"], list_2=["x", "y"])
