"""File destination: atomic writes and a shortcut to the latest run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sleeper.errors import OutputError
from sleeper.output.sink import FileSink, timestamped_name


class TestPut:
    def test_creates_a_missing_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "sorties" / "2026"
        assert FileSink(target).directory.is_dir()

    def test_writes_the_payload_and_returns_the_path(self, tmp_path: Path) -> None:
        sink = FileSink(tmp_path)
        path = sink.put("run.json", b'{"a": 1}')
        assert Path(path).read_bytes() == b'{"a": 1}'

    def test_leaves_no_staging_file_behind(self, tmp_path: Path) -> None:
        FileSink(tmp_path).put("run.json", b"x")
        assert [p.name for p in tmp_path.iterdir()] == ["run.json"]

    def test_a_second_put_replaces_the_first(self, tmp_path: Path) -> None:
        sink = FileSink(tmp_path)
        sink.put("run.json", b"ancien")
        sink.put("run.json", b"nouveau")
        assert (tmp_path / "run.json").read_bytes() == b"nouveau"


class TestLatestLink:
    def test_points_at_the_latest_drop(self, tmp_path: Path) -> None:
        sink = FileSink(tmp_path)
        sink.put("run-1.json", b"premier")
        sink.point_at_latest("run-1.json", "latest.json")
        assert (tmp_path / "latest.json").read_bytes() == b"premier"

    def test_is_replaceable_from_one_run_to_the_next(self, tmp_path: Path) -> None:
        sink = FileSink(tmp_path)
        sink.put("run-1.json", b"premier")
        sink.point_at_latest("run-1.json", "latest.json")
        sink.put("run-2.json", b"second")
        sink.point_at_latest("run-2.json", "latest.json")
        assert (tmp_path / "latest.json").read_bytes() == b"second"

    def test_falls_back_to_a_copy_when_symlinks_are_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = FileSink(tmp_path)
        sink.put("run-1.json", b"premier")

        def refuse(*_: object, **__: object) -> None:
            raise OSError("liens symboliques indisponibles")

        # Reproduces Windows behaviour without the relevant privilege.
        monkeypatch.setattr(Path, "symlink_to", refuse)
        sink.point_at_latest("run-1.json", "latest.json")
        link = tmp_path / "latest.json"
        assert link.read_bytes() == b"premier"
        assert not link.is_symlink()


class TestTimestampedName:
    def test_produces_a_readable_portable_name(self) -> None:
        name = timestamped_name("sleeper", datetime(2026, 8, 25, 4, 30, tzinfo=UTC), "json")
        assert name == "sleeper-2026-08-25-0430.json"
        assert ":" not in name

    def test_precision_stops_at_the_minute(self) -> None:
        # L'outil tourne une fois par jour : plus fin ne fait qu'illisible.
        first = timestamped_name("sleeper", datetime(2026, 8, 25, 12, 40, 2), "json")
        second = timestamped_name("sleeper", datetime(2026, 8, 25, 12, 40, 59), "json")
        assert first == second == "sleeper-2026-08-25-1240.json"


class TestCloudFolderGuard:
    """Un espace synchronisé absent ne doit jamais être remplacé en silence.

    C'est la panne la plus coûteuse de cette destination : le run réussit,
    les fichiers sont écrits, rien ne part, et personne ne s'en aperçoit.
    """

    def test_it_refuses_a_drive_folder_whose_mount_is_absent(self, tmp_path: Path) -> None:
        absent = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-a@b.example"
        with pytest.raises(OutputError, match="synchronisé"):
            FileSink(absent / "Mon Drive" / "Sleeper")

    def test_the_message_names_the_missing_parent(self, tmp_path: Path) -> None:
        cible = tmp_path / "CloudStorage" / "GoogleDrive-a@b.example" / "Mon Drive" / "Sleeper"
        with pytest.raises(OutputError) as leve:
            FileSink(cible)
        assert str(cible.parent) in str(leve.value)

    def test_it_creates_the_last_level_when_the_mount_is_there(self, tmp_path: Path) -> None:
        """Le dossier Sleeper lui-même, oui : c'est le seul niveau permis."""
        monte = tmp_path / "CloudStorage" / "GoogleDrive-a@b.example" / "Mon Drive"
        monte.mkdir(parents=True)
        sink = FileSink(monte / "Sleeper")
        assert sink.directory.is_dir()

    @pytest.mark.parametrize("racine", ["Dropbox", "OneDrive - Entreprise", "Google Drive"])
    def test_the_other_sync_clients_are_covered_too(self, tmp_path: Path, racine: str) -> None:
        with pytest.raises(OutputError, match="synchronisé"):
            FileSink(tmp_path / racine / "absent" / "Sleeper")

    def test_an_ordinary_path_still_creates_its_whole_branch(self, tmp_path: Path) -> None:
        """Une première exécution sur un dépôt neuf crée var/sorties toute seule."""
        sink = FileSink(tmp_path / "var" / "sorties")
        assert sink.directory.is_dir()


class TestDatedSubdirectory:
    """Les fichiers du run descendent d'un cran, les noms stables restent."""

    def test_sub_creates_the_directory(self, tmp_path: Path) -> None:
        assert FileSink(tmp_path).sub("2026-08-25").directory.is_dir()

    def test_the_link_reaches_into_the_subdirectory(self, tmp_path: Path) -> None:
        racine = FileSink(tmp_path)
        racine.sub("2026-08-25").put("run.json", b'{"a": 1}')
        lien = racine.point_at_latest("2026-08-25/run.json", "latest.json")
        assert Path(lien).read_bytes() == b'{"a": 1}'

    def test_the_link_stays_at_the_top(self, tmp_path: Path) -> None:
        """Sinon le favori de l'opérateur meurt avec la journée."""
        racine = FileSink(tmp_path)
        racine.sub("2026-08-25").put("run.json", b"{}")
        racine.point_at_latest("2026-08-25/run.json", "latest.json")
        assert (tmp_path / "latest.json").exists()

    def test_a_second_day_leaves_the_first_alone(self, tmp_path: Path) -> None:
        racine = FileSink(tmp_path)
        racine.sub("2026-08-25").put("run.json", b"hier")
        racine.sub("2026-08-26").put("run.json", b"aujourd'hui")
        assert (tmp_path / "2026-08-25" / "run.json").read_bytes() == b"hier"
