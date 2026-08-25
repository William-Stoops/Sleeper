"""Google Drive destination.

The second implementation of the `Sink` contract, and the reason the contract
was kept minimal in v1. A downstream analysis system reads `latest.json` from
this folder every day.

Three properties matter here, and none of them is about Drive:

* **Credentials never enter the repository.** The credentials file lives
  wherever the operator put it, its path is configuration, and the file itself
  is git-ignored.
* **A failed upload never fails the run.** A collection that found lots is
  worth keeping. The local file stays written, and the error is loud — in the
  logs and in `run.erreurs`.
* **The network is injectable.** `DriveClient` is a two-method protocol, so
  every test here runs offline.

Google offers two ways to authenticate, and which one applies is not a
preference: it depends on the destination account.

* A **service account** is the right answer for a Google Workspace domain
  writing to a *shared drive*. It runs unattended and needs no browser.
* A service account has **no storage quota of its own**, so on a personal
  Google account it can be granted access to a folder and still be refused
  every upload — `storageQuotaExceeded`. There, the only working answer is
  an **OAuth client**: the operator authorises the tool once in a browser,
  and the files belong to them and count against their quota.

Both are supported, told apart by reading the credentials file. The scope is
`drive.file` in both cases — the narrowest one that allows writing: the tool
sees the files it created, and nothing else in the Drive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Protocol

import structlog

from sleeper.errors import OutputError

_LOG = structlog.get_logger(__name__)

#: Scope needed to create and overwrite the tool's own files. Deliberately not
#: `auth/drive`, which would grant read access to the whole account.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

_JSON_MIME = "application/json"
_MARKDOWN_MIME = "text/markdown"

#: Which of the two authentication paths a credentials file describes.
CredentialKind = Literal["service_account", "oauth_client"]


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


def credential_kind(credentials_path: Path) -> CredentialKind:
    """Tell a service-account file from an OAuth client file.

    Read rather than configured: the file states what it is, and asking the
    operator to also declare it in the configuration would only create a
    second source of truth that can disagree with the first.
    """
    if not credentials_path.is_file():
        raise OutputError(
            f"identifiants Drive introuvables : {credentials_path}. "
            "Le chemin est dans la configuration ; le fichier ne doit jamais "
            "entrer dans le dépôt."
        )
    try:
        content = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OutputError(f"identifiants Drive illisibles : {credentials_path} ({exc})") from exc
    if not isinstance(content, dict):
        raise OutputError(f"identifiants Drive invalides : {credentials_path}")
    if content.get("type") == "service_account":
        return "service_account"
    if "installed" in content or "web" in content:
        return "oauth_client"
    raise OutputError(
        f"identifiants Drive non reconnus : {credentials_path}. Attendu un compte "
        'de service ("type": "service_account") ou un identifiant client OAuth '
        '(clé "installed").'
    )


class _GoogleDrive:  # pragma: no cover
    """The real client. Not covered by tests: it talks to Google.

    Everything testable lives in `DriveSink`, which receives this by injection.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def find(self, folder_id: str, name: str) -> str | None:
        escaped = name.replace("'", "\\'")
        response: dict[str, Any] = (
            self._service.files()
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
        self, folder_id: str, name: str, payload: bytes, mime_type: str, file_id: str | None
    ) -> str:
        from googleapiclient.http import MediaInMemoryUpload  # noqa: PLC0415

        media = MediaInMemoryUpload(payload, mimetype=mime_type, resumable=False)
        if file_id:
            updated = self._service.files().update(fileId=file_id, media_body=media).execute()
            return str(updated["id"])
        created = (
            self._service.files()
            .create(
                body={"name": name, "parents": [folder_id]},
                media_body=media,
                fields="id",
            )
            .execute()
        )
        return str(created["id"])


def _require_google() -> None:
    """Fail with the remedy, not with an ImportError traceback."""
    try:
        # Deferred import: a machine that does not publish to Drive should not
        # need the Google libraries installed.
        import googleapiclient.discovery  # noqa: F401, PLC0415
    except ImportError as exc:
        raise OutputError(
            "le dépôt sur Drive requiert les bibliothèques Google : uv sync --extra drive"
        ) from exc


def _oauth_credentials(token_path: Path) -> Any:  # pragma: no cover
    """Load the stored authorisation, refreshing it if it has expired.

    Never opens a browser: this runs unattended every night. A missing or
    unrefreshable token is a loud failure naming the command that fixes it.
    """
    from google.auth.transport.requests import Request  # noqa: PLC0415
    from google.oauth2.credentials import Credentials  # noqa: PLC0415

    if not token_path.is_file():
        raise OutputError(
            f"aucune autorisation Drive enregistrée ({token_path}). "
            "Lancez « sleeper autoriser-drive » une fois, dans une session "
            "où vous pouvez ouvrir un navigateur."
        )
    credentials = Credentials.from_authorized_user_file(str(token_path), [DRIVE_SCOPE])
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _store_token(token_path, credentials)
        return credentials
    raise OutputError(
        f"l'autorisation Drive enregistrée dans {token_path} n'est plus valable. "
        "Relancez « sleeper autoriser-drive »."
    )


def _store_token(token_path: Path, credentials: Any) -> None:  # pragma: no cover
    """Write the refresh token to disk, readable by its owner only."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    token_path.chmod(0o600)


def build_client(credentials_path: Path, token_path: Path) -> DriveClient:  # pragma: no cover
    """Build a real Drive client, by whichever path the credentials describe."""
    _require_google()
    from googleapiclient.discovery import build  # noqa: PLC0415

    if credential_kind(credentials_path) == "service_account":
        from google.oauth2 import service_account  # noqa: PLC0415

        credentials: Any = service_account.Credentials.from_service_account_file(
            str(credentials_path), scopes=[DRIVE_SCOPE]
        )
    else:
        credentials = _oauth_credentials(token_path)
    return _GoogleDrive(build("drive", "v3", credentials=credentials, cache_discovery=False))


def authorise(credentials_path: Path, token_path: Path) -> Path:  # pragma: no cover
    """Run the one-off browser consent and store the resulting token.

    Interactive by design, and separate from `build_client` for that reason:
    a scheduled run must never sit waiting for a browser that nobody will open.
    """
    _require_google()
    if credential_kind(credentials_path) == "service_account":
        raise OutputError(
            f"{credentials_path} est un compte de service : il n'y a rien à "
            "autoriser. Cette commande sert aux identifiants client OAuth, "
            "seuls utilisables sur un compte Google personnel."
        )
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415
    except ImportError as exc:
        raise OutputError(
            "l'autorisation Drive requiert google-auth-oauthlib : uv sync --extra drive"
        ) from exc

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), [DRIVE_SCOPE])
    _store_token(token_path, flow.run_local_server(port=0))
    return token_path
