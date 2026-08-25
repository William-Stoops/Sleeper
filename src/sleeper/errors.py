"""Sleeper error hierarchy.

Guiding principle of this project: a scraper that degrades silently is worse
than no scraper at all. Every failure mode therefore has its own type, and
none of them is swallowed into a default value.

Messages are in French: they surface to the operator.
"""

from __future__ import annotations


class SleeperError(Exception):
    """Root of every error raised by this project."""


class ConfigurationError(SleeperError):
    """Missing, malformed or inconsistent configuration. Fails at startup."""


class NetworkError(SleeperError):
    """Transport failure after every retry has been exhausted."""


class AntiBotChallengeError(SleeperError):
    """The site is serving an anti-bot challenge (CAPTCHA, WAF).

    Terminal by design: Sleeper solves no challenge. It bubbles up to the
    operator, whose job is to space runs further apart.
    """


class UpstreamSchemaError(SleeperError):
    """The API response no longer has the expected shape.

    Raised when a structural field disappears. This is the guard against
    silent degradation: a failed run beats an empty one.
    """

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"schéma amont cassé en « {path} » : {detail}")
        self.path = path
        self.detail = detail


class SessionError(SleeperError):
    """Cannot obtain or renew a valid browser session."""


class OutputError(SleeperError):
    """The output document does not satisfy its own JSON Schema."""
