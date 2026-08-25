"""File destination: atomic writes and a shortcut to the latest run."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    def test_produces_a_portable_name(self) -> None:
        name = timestamped_name("sleeper", "2026-08-25T04:30:00+02:00", "json")
        assert name == "sleeper-2026-08-25T04-30-00_02-00.json"
        assert ":" not in name

    def test_drops_sub_second_precision(self) -> None:
        # Relevé sur un run réel : « 12-40-02.254400 » est illisible, et deux
        # runs à une seconde d'intervalle n'existent pas.
        name = timestamped_name("sleeper", "2026-08-25T12:40:02.254400+00:00", "json")
        assert name == "sleeper-2026-08-25T12-40-02_00-00.json"
