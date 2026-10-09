"""Command line parsing for cache-cli.

Pydantic Settings does the parsing and the validation, so bad input is rejected
before a single request goes out.
"""

from typing import Annotated, Self

from pydantic import AliasChoices, BaseModel, Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Both --input and --output accept "-" to mean stdin / stdout.
STDIO = "-"


class CliSettings(BaseSettings):
    """Arguments for cache-cli, taken from the command line only."""

    model_config = SettingsConfigDict(
        cli_parse_args=True,
        cli_prog_name="cache-cli",
        # Keeps the short flag for --host as -H. With the default
        # case-insensitive matching it would be lowered to -h and collide with
        # --help, which argparse owns. The task's own spec has that conflict.
        case_sensitive=True,
        # Show "-i str" in --help rather than "-i {str,null}".
        cli_hide_none_type=True,
    )

    # The signature is fixed by pydantic-settings; we use one source of five.
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],  # noqa: ARG003
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Command line only, no environment.

        The short flags are declared as aliases, and the environment source
        matches aliases too, so a stray one-letter variable such as `H` would
        silently override --host. A test client is invoked by hand; dropping
        the environment is cheaper than making every alias collision safe.
        """
        return (init_settings,)

    host: Annotated[
        HttpUrl,
        Field(
            validation_alias=AliasChoices("H", "host"),
            description="base URL of the service",
        ),
    ] = HttpUrl("http://localhost:8000")

    repeat: Annotated[
        int,
        Field(
            ge=1,
            validation_alias=AliasChoices("r", "repeat"),
            description="how many times to send the payload",
        ),
    ] = 1

    input_file: Annotated[
        str | None,
        Field(
            validation_alias=AliasChoices("i", "input"),
            description='file to read the payload from, or "-" for stdin',
        ),
    ] = None

    json_payload: Annotated[
        str | None,
        Field(
            validation_alias=AliasChoices("j", "json"),
            description="the payload itself, as a JSON string",
        ),
    ] = None

    output_file: Annotated[
        str,
        Field(
            validation_alias=AliasChoices("o", "output"),
            description='file to write the report to, or "-" for stdout',
        ),
    ] = STDIO

    @model_validator(mode="after")
    def exactly_one_input_source(self) -> Self:
        if (self.input_file is None) == (self.json_payload is None):
            raise ValueError("pass exactly one of --input/-i or --json/-j")
        return self


class PayloadRequest(BaseModel):
    """The request body, validated here so the server is not asked in vain.

    Deliberately not imported from the service package: the CLI is a client
    that only speaks HTTP, and stays usable if the service moves elsewhere.
    """

    list_1: list[str]
    list_2: list[str]

    @model_validator(mode="after")
    def lists_must_have_the_same_length(self) -> Self:
        if len(self.list_1) != len(self.list_2):
            raise ValueError("list_1 and list_2 must have the same length")
        return self
