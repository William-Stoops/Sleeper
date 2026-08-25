"""Serialisation, publication du schema, et garde-fou anti-derive."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sleeper.domain.models import DocumentSortie, ErreurRun, Run
from sleeper.errors import SortieError
from sleeper.output import document


def document_vide() -> DocumentSortie:
    return DocumentSortie(
        run=Run(
            horodatage=datetime(2026, 8, 25, 4, 30, tzinfo=UTC),
            duree_secondes=1.5,
            ventes_scannees=1,
            lots_vus=2,
            lots_retenus=1,
            lots_ecartes=1,
        ),
        ventes=[],
        lots=[],
        ecartes=[],
    )


class TestSerialisation:
    def test_produit_du_json_utf8_lisible(self) -> None:
        brut = document.serialiser(document_vide())
        charge = json.loads(brut)
        assert charge["schema_version"] == "1.0"
        assert charge["run"]["ventes_scannees"] == 1

    def test_conserve_les_accents_sans_les_echapper(self) -> None:
        base = document_vide()
        avec_erreur = base.model_copy(
            update={
                "run": base.run.model_copy(
                    update={
                        "erreurs": [
                            ErreurRun(
                                etape="lots",
                                cible="467",
                                type="SchemaAmontError",
                                message="champ réservé absent",
                            )
                        ]
                    }
                )
            }
        )
        brut = document.serialiser(avec_erreur)
        assert "réservé".encode() in brut
        assert rb"\u00e9" not in brut


class TestSchemaPublie:
    def test_le_schema_versionne_dans_le_depot_est_a_jour(self) -> None:
        """Garde-fou : le schema publie doit suivre les modeles."""
        chemin = Path("schemas") / document.NOM_SCHEMA
        assert chemin.is_file(), "lancer « uv run sleeper schema »"
        publie = json.loads(chemin.read_text(encoding="utf-8"))
        assert publie == document.schema_courant(), (
            "le schema publie a derive des modeles : relancer « uv run sleeper schema »"
        )

    def test_publier_ecrit_le_fichier(self, tmp_path: Path) -> None:
        chemin = document.publier_schema(tmp_path)
        assert chemin.is_file()
        assert json.loads(chemin.read_text(encoding="utf-8"))["title"] == "DocumentSortie"


class TestValidation:
    def test_un_document_conforme_passe(self, tmp_path: Path) -> None:
        document.publier_schema(tmp_path)
        document.valider(document_vide(), tmp_path)

    def test_schema_absent_est_une_erreur_explicite(self, tmp_path: Path) -> None:
        with pytest.raises(SortieError, match="schema de sortie absent"):
            document.valider(document_vide(), tmp_path)

    def test_schema_illisible_est_une_erreur_explicite(self, tmp_path: Path) -> None:
        (tmp_path / document.NOM_SCHEMA).write_text("{ pas du json", encoding="utf-8")
        with pytest.raises(SortieError, match="illisible"):
            document.valider(document_vide(), tmp_path)

    def test_document_non_conforme_est_rejete(self, tmp_path: Path) -> None:
        schema = document.schema_courant()
        schema["required"] = [*schema.get("required", []), "champ_inexistant"]
        (tmp_path / document.NOM_SCHEMA).write_text(json.dumps(schema), encoding="utf-8")
        with pytest.raises(SortieError, match="non conforme"):
            document.valider(document_vide(), tmp_path)
