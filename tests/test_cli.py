"""Command-line interface. No network, no browser.

Command names and messages stay French: they are the user interface.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sleeper import cli
from sleeper.domain.inspection import Inspection
from sleeper.domain.models import Lot, OutputDocument, Run, RunError
from sleeper.errors import AntiBotChallengeError

runner = CliRunner()


def minimal_lot(**overrides: Any) -> Lot:
    base: dict[str, Any] = {
        "id": "1",
        "url": "https://exemple/lot/1",
        "sale_id": "467",
        "number": "1",
        "title": "DACIA DUSTER",
        "category": "Véhicules",
        "trade_only": True,
        "make": "DACIA",
        "model": "DUSTER",
        "variant": "",
        "first_registration": "2015-12-23",
        "mileage": 110430,
        "fuel": "Gazole",
        "gearbox": "Boîte manuelle",
        "tax_horsepower": 6,
        "vin": "",
        "crit_air": "",
        "inspection": Inspection(),
        "registration_certificate": True,
        "keys": True,
        "declared_condition": "",
        "starting_price": 1500.0,
        "current_bid": None,
        "bidder_count": None,
        "collection_place": "LILLE",
        "postcode": "59000",
        "department": "59",
        "viewing_dates": "",
        "buyer_fee_pct": None,
        "vat_reclaimable": None,
        "full_description": "",
        "scope": "dans",
        "new_since_last_run": True,
        "bid_moved": False,
        "missing_fields": [],
    }
    base.update(overrides)
    return Lot(**base)


def make_document(lots: list[Lot], errors: list[RunError] | None = None) -> OutputDocument:
    return OutputDocument(
        run=Run(
            timestamp=datetime(2026, 8, 25, 4, 30, tzinfo=UTC),
            duration_seconds=12.0,
            sales_scanned=1,
            lots_seen=len(lots),
            lots_kept=len(lots),
            lots_rejected=0,
            errors=errors or [],
        ),
        sales=[],
        lots=lots,
        rejected=[],
    )


@pytest.fixture
def temp_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
[reseau]
user_agent = "SleeperBot/0.1 (+mailto:test@example.org)"

[perimetre]
departements = ["59", "62"]

[sortie]
repertoire = "{tmp_path / "sorties"}"

[etat]
base = "{tmp_path / "state.sqlite3"}"
""",
        encoding="utf-8",
    )
    return path


def stub_runtime(monkeypatch: pytest.MonkeyPatch, outcome: OutputDocument | Exception) -> None:
    """Short-circuit session, client and collector: only the CLI is under test."""

    class FakeCollector:
        def __init__(self, *_: object, **__: object) -> None: ...

        def run(self) -> OutputDocument:
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class FakeContext:
        def __init__(self, *_: object, **__: object) -> None: ...

        def __enter__(self) -> FakeContext:
            return self

        def __exit__(self, *_: object) -> None: ...

    monkeypatch.setattr(cli, "Collector", FakeCollector)
    monkeypatch.setattr(cli, "BrowserTransport", FakeContext)
    monkeypatch.setattr(cli, "SleeperState", FakeContext)
    monkeypatch.setattr(cli, "DomaineClient", lambda *_, **__: None)


class TestValidateConfig:
    def test_the_shipped_configuration_is_accepted(self) -> None:
        result = runner.invoke(cli.app, ["valider-config"])
        assert result.exit_code == 0
        assert "Configuration valide" in result.stdout

    def test_an_invalid_configuration_exits_with_the_details(self, tmp_path: Path) -> None:
        bad = tmp_path / "ko.toml"
        bad.write_text("[perimetre]\ndepartements = []\n", encoding="utf-8")
        result = runner.invoke(cli.app, ["valider-config", "-c", str(bad)])
        assert result.exit_code == cli.EXIT_BUSINESS_ERROR
        assert "Configuration invalide" in result.stdout

    def test_a_missing_configuration_exits_in_error(self, tmp_path: Path) -> None:
        result = runner.invoke(cli.app, ["valider-config", "-c", str(tmp_path / "rien.toml")])
        assert result.exit_code == cli.EXIT_BUSINESS_ERROR
        assert "introuvable" in result.stdout


class TestSchema:
    def test_publishes_the_schema(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli.app, ["schema"])
        assert result.exit_code == 0
        assert (tmp_path / "schemas" / "sortie-2.0.json").is_file()


class TestCollect:
    def test_writes_the_json_the_digest_and_the_current_links(
        self, temp_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub_runtime(monkeypatch, make_document([minimal_lot()]))
        result = runner.invoke(cli.app, ["collecter", "-c", str(temp_config)])
        assert result.exit_code == 0, result.stdout

        outputs = temp_config.parent / "sorties"
        payload = json.loads((outputs / "latest.json").read_text(encoding="utf-8"))
        assert payload["run"]["lots_retenus"] == 1
        assert "DACIA DUSTER" in (outputs / "latest.md").read_text(encoding="utf-8")

    def test_shows_the_run_summary(
        self, temp_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub_runtime(monkeypatch, make_document([minimal_lot()]))
        result = runner.invoke(cli.app, ["collecter", "-c", str(temp_config)])
        assert "Lots retenus" in result.stdout

    def test_an_incomplete_lot_exits_in_error(
        self, temp_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        incomplete = minimal_lot(trade_only=None, missing_fields=["reserve_aux_professionnels"])
        stub_runtime(monkeypatch, make_document([incomplete]))
        result = runner.invoke(cli.app, ["collecter", "-c", str(temp_config)])
        # The document is still written, but the exit code alerts the scheduler.
        assert result.exit_code == cli.EXIT_BUSINESS_ERROR
        assert (temp_config.parent / "sorties" / "latest.json").is_file()

    def test_an_anti_bot_challenge_has_its_own_exit_code(
        self, temp_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub_runtime(monkeypatch, AntiBotChallengeError("captcha présenté"))
        result = runner.invoke(cli.app, ["collecter", "-c", str(temp_config)])
        assert result.exit_code == cli.EXIT_ANTI_BOT
        assert "Arrêt volontaire" in result.stdout

    def test_run_errors_are_displayed(
        self, temp_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        error = RunError(step="lots", target="467", kind="UpstreamSchemaError", message="cassé")
        stub_runtime(monkeypatch, make_document([minimal_lot()], [error]))
        result = runner.invoke(cli.app, ["collecter", "-c", str(temp_config)])
        assert "cassé" in result.stdout
