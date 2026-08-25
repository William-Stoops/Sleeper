"""Output destinations.

The contract is deliberately minimal — drop a named payload, and point a
stable name at the latest drop — so that a remote destination (Git repository,
object storage) can be added later without touching the rest of the chain.

Only the local-file destination is implemented today.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol


class Sink(Protocol):
    """Destination for the artefacts a run produces."""

    def put(self, name: str, payload: bytes) -> str:
        """Drop a payload and return where it landed, readable by a human."""
        ...

    def point_at_latest(self, target_name: str, link_name: str) -> str:
        """Point a stable name at the most recent artefact."""
        ...


class FileSink:
    """Writes into a local directory, with a shortcut to the latest run."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._directory

    def put(self, name: str, payload: bytes) -> str:
        """Write atomically: never a half-written file."""
        target = self._directory / name
        staging = target.with_name(f".{name}.partiel")
        staging.write_bytes(payload)
        staging.replace(target)
        return str(target)

    def point_at_latest(self, target_name: str, link_name: str) -> str:
        """Create `latest.json`: a symlink when possible, a copy otherwise.

        Windows refuses symlinks without a specific privilege; we then fall
        back to a copy, which renders the same service.
        """
        link = self._directory / link_name
        target = self._directory / target_name
        link.unlink(missing_ok=True)
        try:
            link.symlink_to(target_name)
        except (OSError, NotImplementedError):
            link.write_bytes(target.read_bytes())
        return str(link)


def timestamped_name(prefix: str, instant: datetime, extension: str) -> str:
    """Build a portable file name: `sleeper-2026-08-25-1441.json`.

    Minute precision, no offset, no separators a filesystem dislikes. The tool
    runs once a day; anything finer only makes the name unreadable.
    """
    return f"{prefix}-{instant:%Y-%m-%d-%H%M}.{extension}"
