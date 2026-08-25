"""The Drive destination. Nothing here touches the network."""

from __future__ import annotations

import pytest

from sleeper.errors import OutputError
from sleeper.output.drive import DriveSink


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
