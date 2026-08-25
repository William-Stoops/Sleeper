"""Fixtures partagees. Aucun test ne touche le reseau."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "api"


def charger(nom: str) -> dict[str, Any]:
    """Charge une reponse d'API reelle, capturee puis expurgee des donnees personnelles."""
    donnees: dict[str, Any] = json.loads((FIXTURES / nom).read_text(encoding="utf-8"))
    return donnees


@pytest.fixture
def payload_ventes() -> dict[str, Any]:
    return charger("auctions_list_page1.json")


@pytest.fixture
def payload_lots() -> dict[str, Any]:
    return charger("auction_lots_467_page1.json")


@pytest.fixture
def payload_fiche() -> dict[str, Any]:
    return charger("product_main_dacia_duster.json")


@pytest.fixture
def payload_enchere() -> dict[str, Any]:
    return charger("product_side_dacia_duster.json")
