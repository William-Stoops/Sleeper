"""Test de bout en bout du run, sur les charges utiles reelles capturees.

Aucun reseau : un client factice rejoue les fixtures.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sleeper.api import mapping, operations
from sleeper.config import Configuration, charger_configuration
from sleeper.domain.models import DocumentSortie
from sleeper.errors import ProtectionAntiRobotError, SchemaAmontError
from sleeper.output import document
from sleeper.pipeline import Collecteur, _empreinte
from sleeper.state.store import EtatSleeper
from tests.conftest import charger

T0 = datetime(2026, 8, 25, 4, 30, tzinfo=UTC)


class ClientFactice:
    """Rejoue les fixtures et compte les appels, operation par operation."""

    def __init__(self, **remplacements: dict[str, Any] | Exception) -> None:
        self.appels: list[tuple[str, dict[str, Any]]] = []
        self._reponses: dict[str, dict[str, Any] | Exception] = {
            operations.LISTE_VENTES: _une_seule_page(
                charger("auctions_list_page1.json"), "auctionsList"
            ),
            operations.LOTS_DE_VENTE: _une_seule_page(
                charger("auction_lots_467_page1.json"), "products"
            ),
            operations.FICHE_LOT_PRINCIPALE: charger("product_main_dacia_duster.json"),
        }
        self._reponses.update(remplacements)

    def interroger(self, requete: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        self.appels.append((operations.NOM_OPERATION.get(requete, "?"), dict(variables)))
        reponse = self._reponses.get(requete)
        if reponse is None:
            raise AssertionError(f"operation non prevue par le test : {requete[:60]}")
        if isinstance(reponse, Exception):
            raise reponse
        # La fixture de lots appartient a la vente 467 : les autres ventes
        # repondent vide, comme le ferait la source.
        if requete is operations.LOTS_DE_VENTE:
            filtre: Any = variables.get("filter", {})
            demandee = str(filtre.get("auction", {}).get("eq", ""))
            if demandee != "467":
                return _sans_lot()
        return copy.deepcopy(reponse)

    def compte(self, operation: str) -> int:
        return sum(1 for nom, _ in self.appels if nom == operation)


def _sans_lot() -> dict[str, Any]:
    return {"data": {"products": {"total_count": 0, "page_info": {"total_pages": 1}, "items": []}}}


def _une_seule_page(payload: dict[str, Any], bloc: str) -> dict[str, Any]:
    """Ramene une fixture paginee a une page unique, pour borner le test."""
    copie = copy.deepcopy(payload)
    copie["data"][bloc]["page_info"]["total_pages"] = 1
    return copie


@pytest.fixture
def config(tmp_path: Path) -> Configuration:
    base = charger_configuration(Path("config/default.toml"))
    return base.model_copy(
        update={
            "sortie": base.sortie.model_copy(update={"repertoire": tmp_path / "sorties"}),
            "etat": base.etat.model_copy(update={"base": tmp_path / "etat.sqlite3"}),
        }
    )


def executer(config: Configuration, client: ClientFactice, quand: datetime = T0) -> DocumentSortie:
    """Execute un run avec une horloge figee : la duree du run est deterministe."""
    with EtatSleeper(config.etat.base) as etat:
        instants = iter([quand, quand + timedelta(seconds=12)])
        return Collecteur(config, client, etat, horloge=lambda: next(instants)).executer()


class TestRunNominal:
    def test_ne_retient_que_les_ventes_de_vehicules(self, config: Configuration) -> None:
        client = ClientFactice()
        resultat = executer(config, client)
        # La fixture contient 8 ventes, dont une « Licence IV » sans vehicules.
        assert resultat.run.ventes_scannees < 8
        assert all("Licence IV" not in v.intitule for v in resultat.ventes)

    def test_produit_un_document_conforme_a_son_schema(self, config: Configuration) -> None:
        document.valider(executer(config, ClientFactice()))

    def test_lit_la_mention_reservee_aux_professionnels(self, config: Configuration) -> None:
        resultat = executer(config, ClientFactice())
        retenus = [lot for lot in resultat.lots if lot.vente_id == "467"]
        assert retenus
        assert all(lot.reserve_aux_professionnels is True for lot in retenus)

    def test_marque_les_lots_hors_perimetre_sans_les_supprimer(self, config: Configuration) -> None:
        resultat = executer(config, ClientFactice())
        reunion = [lot for lot in resultat.lots if lot.departement == "974"]
        assert reunion, "les lots de La Réunion doivent être conservés"
        assert all(lot.hors_perimetre for lot in reunion)

    def test_renseigne_les_attributs_vehicule(self, config: Configuration) -> None:
        resultat = executer(config, ClientFactice())
        lot = next(lot for lot in resultat.lots if lot.id == "267804")
        assert (lot.marque, lot.modele, lot.energie) == ("DACIA", "DUSTER", "Gazole")
        assert lot.kilometrage == 110430
        assert lot.carte_grise is True
        assert lot.cles is True
        assert lot.vin == "UU1HSDJ9G53808834"
        assert lot.puissance_fiscale == 6

    def test_conserve_la_description_source_telle_quelle(self, config: Configuration) -> None:
        resultat = executer(config, ClientFactice())
        lot = next(lot for lot in resultat.lots if lot.id == "267804")
        assert lot.description_integrale.startswith("Lot réservé aux professionnels")
        assert "<" not in lot.description_integrale

    def test_la_duree_du_run_est_mesuree(self, config: Configuration) -> None:
        assert executer(config, ClientFactice()).run.duree_secondes == 12.0

    def test_les_compteurs_sont_coherents(self, config: Configuration) -> None:
        resultat = executer(config, ClientFactice())
        assert resultat.run.lots_vus == resultat.run.lots_retenus + resultat.run.lots_ecartes
        assert len(resultat.lots) == resultat.run.lots_retenus
        assert len(resultat.ecartes) == resultat.run.lots_ecartes


class TestIdempotence:
    def test_le_premier_run_declare_tout_nouveau(self, config: Configuration) -> None:
        resultat = executer(config, ClientFactice())
        assert all(lot.nouveau_depuis_dernier_run for lot in resultat.lots)

    def test_un_second_run_identique_ne_signale_aucune_nouveaute(
        self, config: Configuration
    ) -> None:
        executer(config, ClientFactice())
        second = executer(config, ClientFactice(), T0 + timedelta(days=1))
        assert not any(lot.nouveau_depuis_dernier_run for lot in second.lots)
        assert not any(lot.enchere_a_bouge for lot in second.lots)

    def test_une_enchere_qui_monte_est_signalee(self, config: Configuration) -> None:
        executer(config, ClientFactice())
        montee = _une_seule_page(charger("auction_lots_467_page1.json"), "products")
        montee["data"]["products"]["items"][0]["last_bid"] = 3000
        client = ClientFactice(**{operations.LOTS_DE_VENTE: montee})
        second = executer(config, client, T0 + timedelta(days=1))
        bouges = [lot for lot in second.lots if lot.enchere_a_bouge]
        assert [lot.enchere_en_cours for lot in bouges] == [3000.0]


class TestCache:
    def test_la_fiche_nest_telechargee_quune_fois(self, config: Configuration) -> None:
        premier = ClientFactice()
        executer(config, premier)
        second = ClientFactice()
        executer(config, second, T0 + timedelta(days=1))
        assert premier.compte("getProductPageMain") > 0
        assert second.compte("getProductPageMain") == 0


class TestGestionDesErreurs:
    def test_une_casse_amont_sur_les_lots_nannule_pas_le_run(self, config: Configuration) -> None:
        client = ClientFactice(
            **{operations.LOTS_DE_VENTE: {"data": {"products": {"total_count": 0}}}}
        )
        resultat = executer(config, client)
        assert resultat.run.erreurs
        assert resultat.run.erreurs[0].type == SchemaAmontError.__name__
        assert resultat.run.ventes_scannees > 0

    def test_un_challenge_anti_robot_interrompt_tout(self, config: Configuration) -> None:
        client = ClientFactice(**{operations.LOTS_DE_VENTE: ProtectionAntiRobotError("captcha")})
        with pytest.raises(ProtectionAntiRobotError):
            executer(config, client)

    def test_un_lot_sans_mention_pro_lisible_est_signale_incomplet(
        self, config: Configuration
    ) -> None:
        abime = _une_seule_page(charger("auction_lots_467_page1.json"), "products")
        abime["data"]["products"]["items"][0]["professional_only"] = "peut-être"
        client = ClientFactice(**{operations.LOTS_DE_VENTE: abime})
        resultat = executer(config, client)
        incomplets = [lot for lot in resultat.lots if lot.incomplet]
        assert len(incomplets) == 1
        assert incomplets[0].reserve_aux_professionnels is None
        assert any(e.type == "ChampCritiqueIllisible" for e in resultat.run.erreurs)


class TestCachePerime:
    def test_un_cache_ecrit_par_une_version_anterieure_est_retelecharge(
        self, config: Configuration
    ) -> None:
        """Garde-fou : un cache devenu incompatible ne doit pas faire tomber le run."""
        executer(config, ClientFactice())

        # On remplace chaque fiche memorisee par une forme obsolete, sous son
        # empreinte courante — exactement ce que laisserait une version
        # anterieure du modele.
        lots, _ = mapping.lire_lots(charger("auction_lots_467_page1.json"))
        with EtatSleeper(config.etat.base) as etat:
            for brut in lots:
                etat.memoriser_fiche(brut.id, _empreinte(brut), {"champ_disparu": 1}, T0)

        client = ClientFactice()
        resultat = executer(config, client, T0 + timedelta(days=1))
        assert client.compte("getProductPageMain") == len(lots)
        assert resultat.lots
        assert all(lot.marque == "DACIA" for lot in resultat.lots)


class TestHistoriqueDesAdjudications:
    """La série historique qui donnera, dans six mois, le rapport prix/mise à prix."""

    def _avec_adjudication(self, montant: float) -> dict[str, Any]:
        charge = _une_seule_page(charger("auction_lots_467_page1.json"), "products")
        charge["data"]["products"]["items"][0]["bid_winner_amount"] = montant
        return charge

    def test_consigne_le_prix_des_quil_devient_visible(self, config: Configuration) -> None:
        client = ClientFactice(**{operations.LOTS_DE_VENTE: self._avec_adjudication(2400)})
        executer(config, client)
        with EtatSleeper(config.etat.base) as etat:
            assert etat.adjudications() == [(267804, 2400.0, 1500.0)]

    def test_reste_idempotent_dun_run_a_lautre(self, config: Configuration) -> None:
        charge = self._avec_adjudication(2400)
        executer(config, ClientFactice(**{operations.LOTS_DE_VENTE: charge}))
        executer(
            config,
            ClientFactice(**{operations.LOTS_DE_VENTE: charge}),
            T0 + timedelta(days=1),
        )
        with EtatSleeper(config.etat.base) as etat:
            assert len(etat.adjudications()) == 1

    def test_aucune_adjudication_tant_que_rien_nest_vendu(self, config: Configuration) -> None:
        executer(config, ClientFactice())
        with EtatSleeper(config.etat.base) as etat:
            assert etat.adjudications() == []
