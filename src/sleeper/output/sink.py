"""Output destinations.

The contract is deliberately minimal — drop a named payload, and point a
stable name at the latest drop — so that a remote destination (Git repository,
object storage) can be added later without touching the rest of the chain.

Only the local-file destination is implemented today.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
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

    def sub(self, name: str) -> Sink:
        """A destination nested one level down, created if it is missing.

        The stable names stay at the top: a dated folder that also swallowed
        `latest.json` would give it a new identity every night, and any link
        an operator had kept would die with the previous day.
        """
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

    def sub(self, name: str) -> FileSink:
        """A subdirectory of this one."""
        return FileSink(self._directory / name)

    def point_at_latest(self, target_name: str, link_name: str) -> str:
        """Create `latest.json`: a symlink when possible, a copy otherwise.

        Windows refuses symlinks without a specific privilege; we then fall
        back to a copy, which renders the same service.

        `target_name` may point into a subdirectory (`2026-08-25/run.json`):
        the link stays at the top, the artefact it names does not have to.
        """
        link = self._directory / link_name
        target = self._directory / target_name
        link.unlink(missing_ok=True)
        try:
            # Path(), not the raw string: a relative target keeps its forward
            # slashes on Windows, which stores the reparse point verbatim and
            # can no longer resolve it.
            link.symlink_to(Path(target_name))
            if not link.exists():
                raise OSError(f"lien créé mais non résoluble : {link}")
        except (OSError, NotImplementedError):
            # Not only refusals: Windows accepts a symlink it cannot follow,
            # and says nothing. Trusting the absence of an exception left a
            # dangling `latest.json` that no one would have noticed.
            link.unlink(missing_ok=True)
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
    """Build a portable file name: `sleeper-20260825T144107Z.json`.

    ISO 8601 basic format, in UTC. Three properties, and the tool needs all
    three:

    * **Unambiguous.** A local-time name says nothing about its offset. On the
      night the clocks go back, two runs an hour apart would claim the same
      name, and the second would overwrite the first.
    * **Sortable.** Lexicographic order is chronological order, so a listing
      is a history without anyone having to parse it.
    * **Portable.** No colon: Windows refuses them in file names, which rules
      out the extended format ISO 8601 would otherwise prefer.
    """
    return f"{prefix}-{instant.astimezone(UTC):%Y%m%dT%H%M%SZ}.{extension}"
