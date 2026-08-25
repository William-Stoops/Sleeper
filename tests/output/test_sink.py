"""Destination fichier : ecriture atomique et raccourci vers le dernier run."""

from __future__ import annotations

from pathlib import Path

import pytest

from sleeper.output.sink import SinkFichier, nom_horodate


class TestDepot:
    def test_cree_le_repertoire_absent(self, tmp_path: Path) -> None:
        cible = tmp_path / "sorties" / "2026"
        assert SinkFichier(cible).repertoire.is_dir()

    def test_ecrit_le_contenu_et_rend_le_chemin(self, tmp_path: Path) -> None:
        sink = SinkFichier(tmp_path)
        chemin = sink.deposer("run.json", b'{"a": 1}')
        assert Path(chemin).read_bytes() == b'{"a": 1}'

    def test_ne_laisse_aucun_fichier_provisoire(self, tmp_path: Path) -> None:
        SinkFichier(tmp_path).deposer("run.json", b"x")
        assert [p.name for p in tmp_path.iterdir()] == ["run.json"]

    def test_un_second_depot_remplace_le_premier(self, tmp_path: Path) -> None:
        sink = SinkFichier(tmp_path)
        sink.deposer("run.json", b"ancien")
        sink.deposer("run.json", b"nouveau")
        assert (tmp_path / "run.json").read_bytes() == b"nouveau"


class TestLienCourant:
    def test_pointe_vers_le_dernier_depot(self, tmp_path: Path) -> None:
        sink = SinkFichier(tmp_path)
        sink.deposer("run-1.json", b"premier")
        sink.pointer_vers_courant("run-1.json", "latest.json")
        assert (tmp_path / "latest.json").read_bytes() == b"premier"

    def test_est_remplacable_dun_run_a_lautre(self, tmp_path: Path) -> None:
        sink = SinkFichier(tmp_path)
        sink.deposer("run-1.json", b"premier")
        sink.pointer_vers_courant("run-1.json", "latest.json")
        sink.deposer("run-2.json", b"second")
        sink.pointer_vers_courant("run-2.json", "latest.json")
        assert (tmp_path / "latest.json").read_bytes() == b"second"

    def test_retombe_sur_une_copie_si_le_lien_symbolique_est_refuse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = SinkFichier(tmp_path)
        sink.deposer("run-1.json", b"premier")

        def refuser(*_: object, **__: object) -> None:
            raise OSError("liens symboliques indisponibles")

        # Reproduit le comportement de Windows sans privilege particulier.
        monkeypatch.setattr(Path, "symlink_to", refuser)
        sink.pointer_vers_courant("run-1.json", "latest.json")
        lien = tmp_path / "latest.json"
        assert lien.read_bytes() == b"premier"
        assert not lien.is_symlink()


class TestNomHorodate:
    def test_produit_un_nom_portable(self) -> None:
        nom = nom_horodate("sleeper", "2026-08-25T04:30:00+02:00", "json")
        assert nom == "sleeper-2026-08-25T04-30-00_02-00.json"
        assert ":" not in nom
