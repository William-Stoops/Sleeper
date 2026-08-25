"""Structured logging.

The `json` format is the one for the scheduled task: every event is a usable
line. The `console` format is for human diagnosis.

Logs carry a counter of what was seen, kept, rejected and why: that is the
only way to notice that a "successful" run in fact collected nothing.

`configure` is idempotent and re-entrant: each call reinstalls the handler on
the CURRENT error stream. Without that, a process reconfiguring its logging
would keep writing to a stream that has become invalid.
"""

from __future__ import annotations

import logging
import sys

import structlog

from sleeper.config import LoggingConfig


def configure(settings: LoggingConfig) -> None:
    """Install the process-wide structlog configuration."""
    level = getattr(logging, settings.level)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level, force=True)

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if settings.format == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Without this, a logger captured on first use would keep writing to
        # the stream of the previous configuration.
        cache_logger_on_first_use=False,
    )
