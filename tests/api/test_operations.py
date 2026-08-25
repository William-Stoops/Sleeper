"""Les requetes GraphQL doivent rester identiques a celles de l'application.

Le pare-feu applicatif du site valide la forme des parametres : une requete
forgee, meme semantiquement equivalente, est rejetee puis suivie d'un
challenge anti-robot. Ce test est donc un garde-fou, pas une formalite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sleeper.api import operations

REFERENCE = json.loads(
    (Path(__file__).parent.parent / "fixtures/api/operations_reference.json").read_text(
        encoding="utf-8"
    )
)

CORRESPONDANCES = {
    "LISTE_VENTES": "getAuctions",
    "ENTETE_VENTE": "getAuctionHeaderInfos",
    "LOTS_DE_VENTE": "getAuctionLots",
    "FICHE_LOT_PRINCIPALE": "getProductPageMain",
    "FICHE_LOT_ENCHERE": "getProductPageSide",
}


@pytest.mark.parametrize(("constante", "operation"), CORRESPONDANCES.items())
def test_requete_identique_a_la_capture(constante: str, operation: str) -> None:
    assert getattr(operations, constante) == REFERENCE[operation]["query"]


@pytest.mark.parametrize(("constante", "operation"), CORRESPONDANCES.items())
def test_nom_doperation_declare(constante: str, operation: str) -> None:
    assert operations.NOM_OPERATION[getattr(operations, constante)] == operation


def test_chemin_de_passerelle() -> None:
    assert operations.CHEMIN_GRAPHQL == "/gateway/magento/graphql/"
