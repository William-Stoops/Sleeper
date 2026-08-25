"""Interface en ligne de commande. Aucun reseau, aucun navigateur."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sleeper import cli
from sleeper.domain.models import DocumentSortie, ErreurRun, Lot, Run
from sleeper.errors import ProtectionAntiRobotError

runner = CliRunner()


def lot_minimal(**remplacements: Any) -> Lot:
    base: dict[str, Any] = {
        "id": "1",
        "url": "https://exemple/lot/1",
        "vente_id": "467",
        "numero": "1",
        "titre": "DACIA DUSTER",
        "categorie": "Véhicules",
        "reserve_aux_professionnels": True,
        "marque": "DACIA",
        "modele": "DUSTER",
        "version": "",
        "premiere_mise_en_circulation": "2015-12-23",
        "kilometrage": 110430,
        "energie": "Gazole",
        "boite": "Boîte manuelle",
        "puissance_fiscale": 6,
        "vin": "",
        "crit_air": "",
        "controle_technique": "",
        "carte_grise": True,
        "cles": True,
        "etat_declare": "",
        "mise_a_prix": 1500.0,
        "enchere_en_cours": None,
        "nb_encherisseurs": None,
        "lieu_retrait": "LILLE",
        "code_postal": "59000",
        "departement": "59",
        "dates_visite": "",
        "frais_acheteur_pct": None,
        "tva_recuperable": None,
        "description_integrale": "",
        "hors_perimetre": False,
        "nouveau_depuis_dernier_run": True,
        "enchere_a_bouge": False,
        "champs_manquants": [],
    }
    base.update(remplacements)
    return Lot(**base)


def document(lots: list[Lot], erreurs: list[ErreurRun] | None = None) -> DocumentSortie:
    return DocumentSortie(
        run=Run(
            horodatage=datetime(2026, 8, 25, 4, 30, tzinfo=UTC),
            duree_secondes=12.0,
            ventes_scannees=1,
            lots_vus=len(lots),
            lots_retenus=len(lots),
            lots_ecartes=0,
            erreurs=erreurs or [],
        ),
        ventes=[],
        lots=lots,
        ecartes=[],
    )


@pytest.fixture
def config_temporaire(tmp_path: Path) -> Path:
    chemin = tmp_path / "config.toml"
    chemin.write_text(
        f"""
[reseau]
user_agent = "SleeperBot/0.1 (+mailto:test@example.org)"

[perimetre]
departements = ["59", "62"]

[sortie]
repertoire = "{tmp_path / "sorties"}"

[etat]
base = "{tmp_path / "etat.sqlite3"}"
""",
        encoding="utf-8",
    )
    return chemin


def brancher(monkeypatch: pytest.MonkeyPatch, resultat: DocumentSortie | Exception) -> None:
    """Court-circuite session, client et collecteur : la CLI seule est testee."""

    class FauxCollecteur:
        def __init__(self, *_: object, **__: object) -> None: ...

        def executer(self) -> DocumentSortie:
            if isinstance(resultat, Exception):
                raise resultat
            return resultat

    class FauxContexte:
        def __init__(self, *_: object, **__: object) -> None: ...

        def __enter__(self) -> FauxContexte:
            return self

        def __exit__(self, *_: object) -> None: ...

    monkeypatch.setattr(cli, "Collecteur", FauxCollecteur)
    monkeypatch.setattr(cli, "ClientDomaine", FauxContexte)
    monkeypatch.setattr(cli, "EtatSleeper", FauxContexte)
    monkeypatch.setattr(cli, "SessionNavigateur", lambda *_, **__: None)


class TestValiderConfig:
    def test_config_livree_est_acceptee(self) -> None:
        resultat = runner.invoke(cli.app, ["valider-config"])
        assert resultat.exit_code == 0
        assert "Configuration valide" in resultat.stdout

    def test_config_invalide_sort_en_erreur_avec_le_detail(self, tmp_path: Path) -> None:
        mauvaise = tmp_path / "ko.toml"
        mauvaise.write_text("[perimetre]\ndepartements = []\n", encoding="utf-8")
        resultat = runner.invoke(cli.app, ["valider-config", "-c", str(mauvaise)])
        assert resultat.exit_code == cli.CODE_ERREUR_METIER
        assert "Configuration invalide" in resultat.stdout

    def test_config_absente_sort_en_erreur(self, tmp_path: Path) -> None:
        resultat = runner.invoke(cli.app, ["valider-config", "-c", str(tmp_path / "rien.toml")])
        assert resultat.exit_code == cli.CODE_ERREUR_METIER
        assert "introuvable" in resultat.stdout


class TestSchema:
    def test_publie_le_schema(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        resultat = runner.invoke(cli.app, ["schema"])
        assert resultat.exit_code == 0
        assert (tmp_path / "schemas" / "sortie-1.0.json").is_file()


class TestCollecter:
    def test_ecrit_le_json_le_digest_et_les_liens_courants(
        self, config_temporaire: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        brancher(monkeypatch, document([lot_minimal()]))
        resultat = runner.invoke(cli.app, ["collecter", "-c", str(config_temporaire)])
        assert resultat.exit_code == 0, resultat.stdout

        sorties = config_temporaire.parent / "sorties"
        charge = json.loads((sorties / "latest.json").read_text(encoding="utf-8"))
        assert charge["run"]["lots_retenus"] == 1
        assert "DACIA DUSTER" in (sorties / "latest.md").read_text(encoding="utf-8")

    def test_affiche_le_bilan_du_run(
        self, config_temporaire: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        brancher(monkeypatch, document([lot_minimal()]))
        resultat = runner.invoke(cli.app, ["collecter", "-c", str(config_temporaire)])
        assert "Lots retenus" in resultat.stdout

    def test_un_lot_incomplet_fait_sortir_en_erreur(
        self, config_temporaire: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        incomplet = lot_minimal(
            reserve_aux_professionnels=None, champs_manquants=["reserve_aux_professionnels"]
        )
        brancher(monkeypatch, document([incomplet]))
        resultat = runner.invoke(cli.app, ["collecter", "-c", str(config_temporaire)])
        # Le document est ecrit, mais le code de sortie alerte la tache planifiee.
        assert resultat.exit_code == cli.CODE_ERREUR_METIER
        assert (config_temporaire.parent / "sorties" / "latest.json").is_file()

    def test_un_challenge_anti_robot_a_son_propre_code_de_sortie(
        self, config_temporaire: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        brancher(monkeypatch, ProtectionAntiRobotError("captcha présenté"))
        resultat = runner.invoke(cli.app, ["collecter", "-c", str(config_temporaire)])
        assert resultat.exit_code == cli.CODE_ANTI_ROBOT
        assert "Arrêt volontaire" in resultat.stdout or "Arret volontaire" in resultat.stdout

    def test_les_erreurs_du_run_sont_affichees(
        self, config_temporaire: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        erreur = ErreurRun(etape="lots", cible="467", type="SchemaAmontError", message="cassé")
        brancher(monkeypatch, document([lot_minimal()], [erreur]))
        resultat = runner.invoke(cli.app, ["collecter", "-c", str(config_temporaire)])
        assert "cassé" in resultat.stdout
