"""The Drive destination. Nothing here touches the network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sleeper.errors import OutputError
from sleeper.output.drive import DRIVE_SCOPE, DriveSink, credential_kind


class FakeDrive:
    """A Drive that lives in a dictionary."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self.mimes: dict[str, str] = {}
        self.uploads: list[str] = []
        self._fail_on = fail_on

    def find(self, folder_id: str, name: str) -> str | None:
        return f"id-{name}" if (folder_id, name) in self.files else None

    def upload(
        self, folder_id: str, name: str, payload: bytes, mime_type: str, file_id: str | None
    ) -> str:
        if name == self._fail_on:
            raise RuntimeError("quota dépassé")
        self.files[(folder_id, name)] = payload
        self.mimes[name] = mime_type
        self.uploads.append(name)
        return file_id or f"id-{name}"


class TestUpload:
    def test_it_deposits_a_payload_and_returns_a_link(self) -> None:
        drive = FakeDrive()
        link = DriveSink(drive, "dossier").put("sleeper-2026-08-25-1441.json", b'{"a": 1}')
        assert drive.files[("dossier", "sleeper-2026-08-25-1441.json")] == b'{"a": 1}'
        assert link.startswith("https://drive.google.com/file/d/")

    def test_a_stable_name_is_overwritten_in_place(self) -> None:
        """L'identifiant de latest.json ne bouge pas : l'aval peut le marquer."""
        drive = FakeDrive()
        sink = DriveSink(drive, "dossier")
        first = sink.put("latest.json", b"un")
        second = sink.put("latest.json", b"deux")
        assert first == second
        assert drive.files[("dossier", "latest.json")] == b"deux"

    def test_the_digest_goes_up_as_markdown(self) -> None:
        drive = FakeDrive()
        DriveSink(drive, "dossier").put("latest.md", b"# Titre")
        assert drive.mimes["latest.md"] == "text/markdown"

    def test_the_document_goes_up_as_json(self) -> None:
        drive = FakeDrive()
        DriveSink(drive, "dossier").put("latest.json", b"{}")
        assert drive.mimes["latest.json"] == "application/json"


class TestNoSymlinks:
    def test_pointing_at_latest_is_refused_with_an_explanation(self) -> None:
        with pytest.raises(OutputError, match="pas de liens"):
            DriveSink(FakeDrive(), "dossier").point_at_latest("run.json", "latest.json")


class TestCredentialKind:
    """Which authentication path a credentials file describes.

    Read from the file rather than declared in the configuration: two sources
    of truth can disagree, and the operator would be the one paying for it.
    """

    def test_service_account_is_recognised(self, tmp_path: Path) -> None:
        path = tmp_path / "compte.json"
        path.write_text(
            json.dumps({"type": "service_account", "client_email": "x@y.iam.example"}),
            encoding="utf-8",
        )
        assert credential_kind(path) == "service_account"

    def test_installed_oauth_client_is_recognised(self, tmp_path: Path) -> None:
        path = tmp_path / "client.json"
        path.write_text(
            json.dumps({"installed": {"client_id": "abc.apps.example", "redirect_uris": []}}),
            encoding="utf-8",
        )
        assert credential_kind(path) == "oauth_client"

    def test_web_oauth_client_is_recognised(self, tmp_path: Path) -> None:
        path = tmp_path / "client.json"
        path.write_text(json.dumps({"web": {"client_id": "abc.apps.example"}}), encoding="utf-8")
        assert credential_kind(path) == "oauth_client"

    def test_a_missing_file_names_its_path(self, tmp_path: Path) -> None:
        with pytest.raises(OutputError, match="introuvable"):
            credential_kind(tmp_path / "absent.json")

    def test_unparseable_json_fails_loudly(self, tmp_path: Path) -> None:
        path = tmp_path / "casse.json"
        path.write_text("{ceci n'est pas du JSON", encoding="utf-8")
        with pytest.raises(OutputError, match="illisible"):
            credential_kind(path)

    def test_an_unrelated_json_file_is_refused(self, tmp_path: Path) -> None:
        """A downloaded but wrong file is the likeliest operator mistake."""
        path = tmp_path / "autre.json"
        path.write_text(json.dumps({"api_key": "…"}), encoding="utf-8")
        with pytest.raises(OutputError, match="non reconnus"):
            credential_kind(path)

    def test_a_json_array_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "liste.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(OutputError, match="invalides"):
            credential_kind(path)


class TestScope:
    """The narrowest scope that can write, and no wider."""

    def test_the_tool_never_asks_for_the_whole_drive(self) -> None:
        assert DRIVE_SCOPE.endswith("/auth/drive.file")
