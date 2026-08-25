"""Journalisation : format, niveau, et re-entrance.

Les assertions portent sur le flux d'erreur reel : `configurer` reinstalle le
handler racine, ce qui rend les captures de pytest sur `logging` inoperantes —
et c'est exactement le comportement voulu en production.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from sleeper.config import Journalisation
from sleeper.logging_setup import configurer


@pytest.fixture(autouse=True)
def _restaurer() -> Iterator[None]:
    """Remet la journalisation dans son etat par defaut apres chaque test."""
    yield
    structlog.reset_defaults()
    logging.basicConfig(force=True)


def test_format_json_produit_une_ligne_exploitable(capsys: pytest.CaptureFixture[str]) -> None:
    configurer(Journalisation(niveau="INFO", format="json"))
    structlog.get_logger("essai").info("run.termine", retenus=8, ecartes=2)
    charge = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert charge["event"] == "run.termine"
    assert (charge["retenus"], charge["ecartes"]) == (8, 2)
    assert charge["level"] == "info"


def test_format_json_nechappe_pas_les_accents(capsys: pytest.CaptureFixture[str]) -> None:
    configurer(Journalisation(niveau="INFO", format="json"))
    structlog.get_logger("essai").info("lot.ecarte", motif="véhicule non roulant")
    sortie = capsys.readouterr().err
    assert "véhicule non roulant" in sortie


def test_format_console_reste_lisible(capsys: pytest.CaptureFixture[str]) -> None:
    configurer(Journalisation(niveau="INFO", format="console"))
    structlog.get_logger("essai").info("run.termine", retenus=8)
    sortie = capsys.readouterr().err
    assert "run.termine" in sortie
    assert not sortie.strip().startswith("{")


def test_le_niveau_filtre_les_evenements(capsys: pytest.CaptureFixture[str]) -> None:
    configurer(Journalisation(niveau="WARNING", format="json"))
    journal = structlog.get_logger("essai")
    journal.info("ignore")
    journal.warning("retenu")
    sortie = capsys.readouterr().err
    assert "retenu" in sortie
    assert "ignore" not in sortie


def test_reconfigurer_rebranche_sur_le_flux_courant(capsys: pytest.CaptureFixture[str]) -> None:
    """Garde-fou : sans cela, un second appel ecrirait sur un flux perime."""
    configurer(Journalisation(niveau="INFO", format="json"))
    structlog.get_logger("essai").info("premier")
    capsys.readouterr()
    configurer(Journalisation(niveau="INFO", format="console"))
    structlog.get_logger("essai").info("second")
    assert "second" in capsys.readouterr().err
