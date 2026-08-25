"""Google Drive destination.

The second implementation of the `Sink` contract, and the reason the contract
was kept minimal in v1. A downstream analysis system reads `latest.json` from
this folder every day.

Three properties matter here, and none of them is about Drive:

* **Credentials never enter the repository.** The service-account file lives
  wherever the operator put it, its path is configuration, and the file itself
  is git-ignored.
* **A failed upload never fails the run.** A collection that found lots is
  worth keeping. The local file stays written, and the error is loud — in the
  logs and in `run.erreurs`.
* **The network is injectable.** `DriveClient` is a two-method protocol, so
  every test here runs offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import structlog

from sleeper.errors import OutputError

_LOG = structlog.get_logger(__name__)

#: Scope needed to create and overwrite files in the destination folder.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

_JSON_MIME = "application/json"
_MARKDOWN_MIME = "text/markdown"


class DriveClient(Protocol):
    """What the sink needs from Drive, and nothing more."""

    def find(self, folder_id: str, name: str) -> str | None:
        """Id of a file of that name in that folder, if it is there."""
        ...

    def upload(
        self, folder_id: str, name: str, payload: bytes, mime_type: str, file_id: str | None
    ) -> str:
        """Create or overwrite a file, returning its id."""
        ...


class DriveSink:
    """Deposits the run's artefacts in a Drive folder."""

    def __init__(self, client: DriveClient, folder_id: str) -> None:
        self._client = client
        self._folder_id = folder_id

    def put(self, name: str, payload: bytes) -> str:
        """Upload a payload, overwriting any file of the same name.

        The timestamped file is new every day and simply accumulates; the
        `latest` names are overwritten in place, so their id is stable and a
        consumer can bookmark them.
        """
        mime = _MARKDOWN_MIME if name.endswith(".md") else _JSON_MIME
        existing = self._client.find(self._folder_id, name)
        file_id = self._client.upload(self._folder_id, name, payload, mime, existing)
        _LOG.info("drive.uploaded", name=name, file_id=file_id, bytes=len(payload))
        return f"https://drive.google.com/file/d/{file_id}"

    def point_at_latest(self, target_name: str, link_name: str) -> str:
        """Drive has no symlinks, so the stable name is its own upload.

        Rather than fail, the sink honours the contract the only way Drive
        allows: it is the caller that must hand it the payload, so this asks
        for exactly that instead of pretending to link.
        """
        raise OutputError(
            f"Drive n'a pas de liens : déposer « {link_name} » avec put(), "
            f"comme une copie de « {target_name} »."
        )


def build_client(credentials_path: Path) -> DriveClient:  # pragma: no cover
    """Build a real Drive client from a service-account file.

    Not covered by tests: it talks to Google. Everything testable lives in
    `DriveSink`, which receives this client by injection.
    """
    try:
        # Deferred import: a machine that does not publish to Drive should not
        # need the Google libraries installed.
        from google.oauth2 import service_account  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415
        from googleapiclient.http import MediaInMemoryUpload  # noqa: PLC0415
    except ImportError as exc:
        raise OutputError(
            "le dépôt sur Drive requiert les bibliothèques Google : uv sync --extra drive"
        ) from exc

    if not credentials_path.is_file():
        raise OutputError(
            f"compte de service introuvable : {credentials_path}. "
            "Le chemin est dans la configuration ; le fichier ne doit jamais "
            "entrer dans le dépôt."
        )
    credentials = service_account.Credentials.from_service_account_file(
        str(credentials_path), scopes=[DRIVE_SCOPE]
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    class _GoogleDrive:
        def find(self, folder_id: str, name: str) -> str | None:
            escaped = name.replace("'", "\\'")
            response: dict[str, Any] = (
                service.files()
                .list(
                    q=f"name = '{escaped}' and '{folder_id}' in parents and trashed = false",
                    fields="files(id)",
                    pageSize=1,
                )
                .execute()
            )
            files = response.get("files") or []
            return str(files[0]["id"]) if files else None

        def upload(
            self,
            folder_id: str,
            name: str,
            payload: bytes,
            mime_type: str,
            file_id: str | None,
        ) -> str:
            media = MediaInMemoryUpload(payload, mimetype=mime_type, resumable=False)
            if file_id:
                updated = service.files().update(fileId=file_id, media_body=media).execute()
                return str(updated["id"])
            created = (
                service.files()
                .create(
                    body={"name": name, "parents": [folder_id]},
                    media_body=media,
                    fields="id",
                )
                .execute()
            )
            return str(created["id"])

    return _GoogleDrive()
