"""Traduction des reponses de l'API en objets typés.

Regle cardinale : si un champ structurant disparait de la source, on echoue
bruyamment. Un scraper qui renvoie `null` en silence ferait prendre une
decision d'achat sur des donnees incompletes.
"""

from __future__ import annotations

from typing import Any

import pytest

from sleeper.api import mapping
from sleeper.errors import SchemaAmontError


class TestLireVentes:
    def test_lit_la_pagination(self, payload_ventes: dict[str, Any]) -> None:
        _, pagination = mapping.lire_ventes(payload_ventes)
        assert pagination.total_count == 11
        assert pagination.total_pages == 2

    def test_lit_les_ventes(self, payload_ventes: dict[str, Any]) -> None:
        ventes, _ = mapping.lire_ventes(payload_ventes)
        assert len(ventes) == 8
        premiere = ventes[0]
        assert premiere.id == 467
        assert premiere.direction_regionale == "LA REUNION"
        assert premiere.nb_lots == 161
        assert "Véhicules" in premiere.categories
        assert premiere.statut == 3

    def test_absorbe_le_professional_only_en_chaine(self, payload_ventes: dict[str, Any]) -> None:
        # Au niveau vente l'API renvoie "0"/"1" ; au niveau lot, 0/1.
        ventes, _ = mapping.lire_ventes(payload_ventes)
        assert {v.reserve_aux_professionnels for v in ventes} == {True, False}

    def test_lit_les_dates_en_datetime_aware(self, payload_ventes: dict[str, Any]) -> None:
        ventes, _ = mapping.lire_ventes(payload_ventes)
        assert ventes[0].date_cloture is not None
        assert ventes[0].date_cloture.tzinfo is not None

    def test_erreur_graphql_est_terminale(self) -> None:
        with pytest.raises(SchemaAmontError, match="erreur GraphQL"):
            mapping.lire_ventes({"errors": [{"message": "Cannot query field"}]})

    def test_bloc_manquant_est_terminale(self) -> None:
        with pytest.raises(SchemaAmontError, match="auctionsList"):
            mapping.lire_ventes({"data": {}})

    def test_items_absent_est_terminale(self) -> None:
        with pytest.raises(SchemaAmontError, match="items"):
            mapping.lire_ventes({"data": {"auctionsList": {"total_count": 0}}})


class TestLireLots:
    def test_lit_la_pagination(self, payload_lots: dict[str, Any]) -> None:
        _, pagination = mapping.lire_lots(payload_lots)
        assert pagination.total_count == 161
        assert pagination.total_pages == 21

    def test_lit_les_champs_decisifs(self, payload_lots: dict[str, Any]) -> None:
        lots, _ = mapping.lire_lots(payload_lots)
        premier = lots[0]
        assert premier.id == 267804
        assert premier.url_key == "daciadustersecteurest-1"
        assert premier.reserve_aux_professionnels is True
        assert premier.mise_a_prix == 1500
        assert premier.code_postal_retrait == "97470"
        assert premier.ville_retrait == "SAINT-BENOIT"
        assert premier.vente_id == 467

    def test_enchere_en_cours_absente_reste_nulle(self, payload_lots: dict[str, Any]) -> None:
        lots, _ = mapping.lire_lots(payload_lots)
        assert lots[0].enchere_en_cours is None

    def test_enchere_en_cours_presente_est_lue(self, payload_lots: dict[str, Any]) -> None:
        lots, _ = mapping.lire_lots(payload_lots)
        avec_enchere = [lot for lot in lots if lot.enchere_en_cours is not None]
        assert {lot.enchere_en_cours for lot in avec_enchere} == {2000.0, 900.0}

    def test_description_est_degagee_du_html(self, payload_lots: dict[str, Any]) -> None:
        lots, _ = mapping.lire_lots(payload_lots)
        assert "<p>" not in lots[0].description
        assert lots[0].description.startswith("Lot réservé aux professionnels")

    def test_professional_only_illisible_alimente_les_anomalies(self) -> None:
        payload = {
            "data": {
                "products": {
                    "total_count": 1,
                    "page_info": {"total_pages": 1},
                    "items": [_lot_brut(professional_only="peut-etre")],
                }
            }
        }
        lots, _ = mapping.lire_lots(payload)
        assert lots[0].reserve_aux_professionnels is None
        assert "reserve_aux_professionnels" in lots[0].champs_illisibles

    def test_professional_only_absent_est_terminale(self) -> None:
        brut = _lot_brut()
        del brut["professional_only"]
        payload = {
            "data": {
                "products": {"total_count": 1, "page_info": {"total_pages": 1}, "items": [brut]}
            }
        }
        with pytest.raises(SchemaAmontError, match="professional_only"):
            mapping.lire_lots(payload)


class TestLireAttributsVehicule:
    def test_lit_les_attributs_structures(self, payload_fiche: dict[str, Any]) -> None:
        attrs = mapping.lire_attributs(payload_fiche)
        assert attrs.marque == "DACIA"
        assert attrs.modele == "DUSTER"
        assert attrs.energie == "Gazole"
        assert attrs.boite == "Boîte manuelle"
        assert attrs.genre == "VP"
        assert attrs.kilometrage == 110430
        assert attrs.a_une_cle is True
        assert attrs.certificat_immatriculation is True
        assert attrs.controle_technique is False
        assert attrs.annee_mise_en_circulation == 2015
        assert attrs.premiere_mise_en_circulation == "2015-12-23"

    def test_signale_le_lieu_de_retrait_detaille(self, payload_fiche: dict[str, Any]) -> None:
        attrs = mapping.lire_attributs(payload_fiche)
        assert attrs.code_postal_retrait == "97470"
        assert attrs.ville_retrait == "SAINT-BENOIT"

    def test_nexpose_aucun_attribut_sensible(self, payload_fiche: dict[str, Any]) -> None:
        attrs = mapping.lire_attributs(payload_fiche)
        assert "biciban" not in attrs.attributs_bruts
        assert "contact_dropoff_location_id" not in attrs.attributs_bruts

    def test_produit_vide_est_terminale(self) -> None:
        with pytest.raises(SchemaAmontError, match="items"):
            mapping.lire_attributs({"data": {"products": {"items": []}}})


def _lot_brut(**remplacements: Any) -> dict[str, Any]:
    """Item de lot minimal conforme au schema amont."""
    base: dict[str, Any] = {
        "id": 1,
        "sku": "SKU1",
        "url_key": "un-lot-1",
        "lot_number": 1,
        "name": "UN LOT",
        "auction": 467,
        "professional_only": 1,
        "price_auction": 100,
        "last_bid": None,
        "reserve_price": None,
        "lot_status_label": "Vente en cours",
        "start_date": None,
        "end_date": None,
        "dropoff_location": {"city": "LILLE", "postcode": "59000"},
        "short_description": {"html": "<p>Un lot</p>"},
        "description": {"html": ""},
        "sales_inspector_data": {"cav_name": "LILLE"},
    }
    base.update(remplacements)
    return base
