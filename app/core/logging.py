"""Logging setup.

Plain lines on stdout: in a container the platform collects stdout, so the
service has no business managing log files itself.
"""

import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        # Replace the handlers uvicorn installs, so one format wins.
        force=True,
    )
