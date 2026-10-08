"""Logging setup.

Plain lines on stdout: in a container the platform collects stdout, so the
service has no business managing log files itself.
"""

import logging

# uvicorn gives these loggers their own handlers and stops propagation, so the
# access log would otherwise keep uvicorn's format next to ours.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        force=True,
    )
    # Route uvicorn through the root handler, so one format wins.
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
