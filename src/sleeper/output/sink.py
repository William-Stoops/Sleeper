"""Output destinations.

The contract is deliberately minimal — drop a named payload, and point a
stable name at the latest drop — so that a remote destination (Git repository,
object storage) can be added later without touching the rest of the chain.

Only the local-file destination is implemented today.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol

from sleeper.errors import OutputError

#: Directory names that mark the root of a synchronising cloud folder. Not
#: configuration: these are facts about operating systems, not a business
#: decision, and an operator who had to declare them could only get them wrong.
_CLOUD_MARKERS: Final = re.compile(
    r"^(CloudStorage|Google ?Drive.*|Dropbox|OneDrive.*|iCloud Drive|Mobile Documents)$",
    re.IGNORECASE,
)


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
        _refuse_to_forge_a_cloud_folder(directory)
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


def _refuse_to_forge_a_cloud_folder(directory: Path) -> None:
    """Inside a sync folder, only the last level may be created.

    A cloud folder exists only while its client runs. If the destination is
    `.../Mon Drive/Sleeper` and Drive is not running that night, `mkdir` would
    quietly rebuild the whole branch as ordinary local directories: the run
    would report a success, the files would land on the disk, and nothing
    would ever be synchronised. The operator would believe they had been
    publishing for weeks.

    So the rule is narrow and stated once: under a sync root, the parent must
    already be there. Everything outside such a path keeps the old behaviour —
    a first run on a fresh clone still creates `var/sorties` on its own.
    """
    if not any(_CLOUD_MARKERS.match(part) for part in directory.parts):
        return
    parent = directory.parent
    if parent.is_dir():
        return
    raise OutputError(
        f"le dossier de destination {directory} est dans un espace synchronisé, "
        f"mais {parent} n'existe pas. Le client de synchronisation n'est "
        "probablement pas lancé. Refus de créer un dossier local qui ne "
        "partirait jamais : lancez-le, puis relancez la collecte."
    )


def timestamped_name(prefix: str, instant: datetime, extension: str) -> str:
    """Build a portable file name: `sleeper-2026-08-25-1441.json`.

    Minute precision, no offset, no separators a filesystem dislikes. The tool
    runs once a day; anything finer only makes the name unreadable.
    """
    return f"{prefix}-{instant:%Y-%m-%d-%H%M}.{extension}"
