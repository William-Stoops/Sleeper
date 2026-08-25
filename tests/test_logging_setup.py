"""Logging: format, level, and re-entrance.

Assertions look at the real error stream: `configure` reinstalls the root
handler, which makes pytest's `logging` captures inoperative — and that is
exactly the behaviour wanted in production.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from sleeper.config import LoggingConfig
from sleeper.logging_setup import configure


@pytest.fixture(autouse=True)
def _restore() -> Iterator[None]:
    """Put logging back to its default state after each test."""
    yield
    structlog.reset_defaults()
    logging.basicConfig(force=True)


def test_json_format_produces_a_usable_line(capsys: pytest.CaptureFixture[str]) -> None:
    configure(LoggingConfig(level="INFO", format="json"))
    structlog.get_logger("essai").info("run.finished", kept=8, rejected=2)
    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert payload["event"] == "run.finished"
    assert (payload["kept"], payload["rejected"]) == (8, 2)
    assert payload["level"] == "info"


def test_json_format_does_not_escape_accents(capsys: pytest.CaptureFixture[str]) -> None:
    configure(LoggingConfig(level="INFO", format="json"))
    structlog.get_logger("essai").info("lot.rejected", reason="véhicule non roulant")
    assert "véhicule non roulant" in capsys.readouterr().err


def test_console_format_stays_readable(capsys: pytest.CaptureFixture[str]) -> None:
    configure(LoggingConfig(level="INFO", format="console"))
    structlog.get_logger("essai").info("run.finished", kept=8)
    output = capsys.readouterr().err
    assert "run.finished" in output
    assert not output.strip().startswith("{")


def test_the_level_filters_events(capsys: pytest.CaptureFixture[str]) -> None:
    configure(LoggingConfig(level="WARNING", format="json"))
    logger = structlog.get_logger("essai")
    logger.info("ignored")
    logger.warning("kept")
    output = capsys.readouterr().err
    assert "kept" in output
    assert "ignored" not in output


def test_reconfiguring_rebinds_to_the_current_stream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Guard rail: without this, a second call would write to a stale stream."""
    configure(LoggingConfig(level="INFO", format="json"))
    structlog.get_logger("essai").info("first")
    capsys.readouterr()
    configure(LoggingConfig(level="INFO", format="console"))
    structlog.get_logger("essai").info("second")
    assert "second" in capsys.readouterr().err
