"""Serialisation, schema publication, and the anti-drift guard rail."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sleeper.domain.models import OutputDocument, Run, RunError
from sleeper.errors import OutputError
from sleeper.output import document


def empty_document() -> OutputDocument:
    return OutputDocument(
        run=Run(
            timestamp=datetime(2026, 8, 25, 4, 30, tzinfo=UTC),
            duration_seconds=1.5,
            sales_scanned=1,
            lots_seen=2,
            lots_kept=1,
            lots_rejected=1,
        ),
        sales=[],
        lots=[],
        rejected=[],
    )


class TestSerialisation:
    def test_produces_readable_utf8_json(self) -> None:
        raw = document.serialize(empty_document())
        payload = json.loads(raw)
        assert payload["schema_version"] == "2.0"
        assert payload["run"]["ventes_scannees"] == 1

    def test_the_wire_format_keeps_the_french_contract(self) -> None:
        """Identifiers are English; the JSON keys stay the specified contract."""
        payload = json.loads(document.serialize(empty_document()))
        assert set(payload) == {"schema_version", "run", "ventes", "lots", "ecartes"}
        assert "duree_secondes" in payload["run"]
        assert "duration_seconds" not in payload["run"]

    def test_keeps_accents_without_escaping_them(self) -> None:
        base = empty_document()
        with_error = base.model_copy(
            update={
                "run": base.run.model_copy(
                    update={
                        "errors": [
                            RunError(
                                step="lots",
                                target="467",
                                kind="UpstreamSchemaError",
                                message="champ réservé absent",
                            )
                        ]
                    }
                )
            }
        )
        raw = document.serialize(with_error)
        assert "réservé".encode() in raw
        assert rb"\u00e9" not in raw


class TestPublishedSchema:
    def test_the_schema_versioned_in_the_repository_is_up_to_date(self) -> None:
        """Guard rail: the published schema must follow the models."""
        path = Path("schemas") / document.SCHEMA_NAME
        assert path.is_file(), "lancer « uv run sleeper schema »"
        published = json.loads(path.read_text(encoding="utf-8"))
        assert published == document.current_schema(), (
            "le schéma publié a dérivé des modèles : relancer « uv run sleeper schema »"
        )

    def test_publishing_writes_the_file(self, tmp_path: Path) -> None:
        path = document.publish_schema(tmp_path)
        assert path.is_file()
        assert json.loads(path.read_text(encoding="utf-8"))["title"] == "OutputDocument"


class TestValidation:
    def test_a_conforming_document_passes(self, tmp_path: Path) -> None:
        document.publish_schema(tmp_path)
        document.validate(empty_document(), tmp_path)

    def test_a_missing_schema_is_an_explicit_error(self, tmp_path: Path) -> None:
        with pytest.raises(OutputError, match="schéma de sortie absent"):
            document.validate(empty_document(), tmp_path)

    def test_an_unreadable_schema_is_an_explicit_error(self, tmp_path: Path) -> None:
        (tmp_path / document.SCHEMA_NAME).write_text("{ pas du json", encoding="utf-8")
        with pytest.raises(OutputError, match="illisible"):
            document.validate(empty_document(), tmp_path)

    def test_a_non_conforming_document_is_rejected(self, tmp_path: Path) -> None:
        schema = document.current_schema()
        schema["required"] = [*schema.get("required", []), "champ_inexistant"]
        (tmp_path / document.SCHEMA_NAME).write_text(json.dumps(schema), encoding="utf-8")
        with pytest.raises(OutputError, match="non conforme"):
            document.validate(empty_document(), tmp_path)


class TestReadingBack:
    """Un consommateur doit échouer bruyamment sur une version inconnue."""

    def test_it_reads_a_document_of_the_current_version(self, tmp_path: Path) -> None:
        path = tmp_path / "run.json"
        path.write_bytes(document.serialize(empty_document()))
        assert document.read_document(path).run.lots_kept == 1

    @pytest.mark.parametrize("version", ["1.0", "3.0", "", None])
    def test_an_unknown_version_is_refused(self, tmp_path: Path, version: str | None) -> None:
        path = tmp_path / "run.json"
        payload = json.loads(document.serialize(empty_document()))
        payload["schema_version"] = version
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(OutputError, match="version de schéma inconnue"):
            document.read_document(path)

    def test_no_degraded_reading_is_attempted(self, tmp_path: Path) -> None:
        """Un 1.0 dit « hors_perimetre: false » là où un 2.0 dit « inconnu ».

        Le lire comme un 2.0 transformerait « on n'a pas su » en « c'est dans
        le périmètre » — exactement ce que le contrat existe pour empêcher.
        """
        path = tmp_path / "v1.json"
        path.write_text(
            json.dumps(
                {"schema_version": "1.0", "run": {}, "ventes": [], "lots": [], "ecartes": []}
            ),
            encoding="utf-8",
        )
        with pytest.raises(OutputError, match=re.escape("« 1.0 »")):
            document.read_document(path)

    def test_an_unreadable_file_is_an_explicit_error(self, tmp_path: Path) -> None:
        path = tmp_path / "cassé.json"
        path.write_text("{ pas du json", encoding="utf-8")
        with pytest.raises(OutputError, match="illisible"):
            document.read_document(path)
