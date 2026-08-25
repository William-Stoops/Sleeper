"""Etat persistant : nouveautes, mouvements d'enchere, cache, historique.

L'idempotence est la propriete la plus importante ici : deux executions
successives sans changement amont ne doivent produire aucune fausse alerte.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sleeper.state.store import EtatSleeper, ObservationLot

T0 = datetime(2026, 8, 25, 4, 30, tzinfo=UTC)
T1 = T0 + timedelta(days=1)


@pytest.fixture
def etat(tmp_path: Path) -> Iterator[EtatSleeper]:
    with EtatSleeper(tmp_path / "etat.sqlite3") as ouvert:
        yield ouvert


def observer(
    etat: EtatSleeper, *, lot_id: int = 1, enchere: float | None = None, quand: datetime = T0
) -> ObservationLot:
    return etat.observer_lot(
        lot_id=lot_id,
        vente_id=467,
        url=f"https://exemple/lot/{lot_id}",
        titre="DACIA DUSTER",
        reserve_aux_professionnels=True,
        mise_a_prix=1500.0,
        enchere_en_cours=enchere,
        code_postal="59000",
        departement="59",
        horodatage=quand,
    )


class TestMigrations:
    def test_cree_le_schema_et_note_sa_version(self, tmp_path: Path) -> None:
        with EtatSleeper(tmp_path / "etat.sqlite3") as etat:
            assert etat.version_schema() >= 1

    def test_rouvrir_une_base_existante_ne_la_recree_pas(self, tmp_path: Path) -> None:
        chemin = tmp_path / "etat.sqlite3"
        with EtatSleeper(chemin) as etat:
            observer(etat)
            version = etat.version_schema()
        with EtatSleeper(chemin) as etat:
            assert etat.version_schema() == version
            assert observer(etat, quand=T1).nouveau is False


class TestDetectionDesNouveautes:
    def test_un_lot_jamais_vu_est_nouveau(self, etat: EtatSleeper) -> None:
        assert observer(etat).nouveau is True

    def test_un_lot_deja_vu_ne_lest_plus(self, etat: EtatSleeper) -> None:
        observer(etat)
        assert observer(etat, quand=T1).nouveau is False

    def test_deux_executions_identiques_ne_produisent_aucune_alerte(
        self, etat: EtatSleeper
    ) -> None:
        observer(etat, enchere=900.0)
        seconde = observer(etat, enchere=900.0, quand=T1)
        assert (seconde.nouveau, seconde.enchere_a_bouge) == (False, False)


class TestMouvementDenchere:
    def test_premiere_enchere_constatee_est_un_mouvement(self, etat: EtatSleeper) -> None:
        observer(etat, enchere=None)
        assert observer(etat, enchere=900.0, quand=T1).enchere_a_bouge is True

    def test_enchere_stable_nest_pas_un_mouvement(self, etat: EtatSleeper) -> None:
        observer(etat, enchere=900.0)
        assert observer(etat, enchere=900.0, quand=T1).enchere_a_bouge is False

    def test_enchere_qui_monte_est_un_mouvement(self, etat: EtatSleeper) -> None:
        observer(etat, enchere=900.0)
        assert observer(etat, enchere=1000.0, quand=T1).enchere_a_bouge is True

    def test_un_lot_neuf_sans_enchere_ne_bouge_pas(self, etat: EtatSleeper) -> None:
        assert observer(etat, enchere=None).enchere_a_bouge is False

    def test_lhistorique_ne_retient_que_les_changements(self, etat: EtatSleeper) -> None:
        observer(etat, enchere=900.0)
        observer(etat, enchere=900.0, quand=T1)
        observer(etat, enchere=1200.0, quand=T1 + timedelta(days=1))
        historique = etat.historique_encheres(1)
        assert [montant for _, montant in historique] == [900.0, 1200.0]


class TestCacheDeFiche:
    def test_absence_de_cache_rend_none(self, etat: EtatSleeper) -> None:
        assert etat.fiche_en_cache(1, "empreinte") is None

    def test_relit_une_fiche_a_empreinte_identique(self, etat: EtatSleeper) -> None:
        etat.memoriser_fiche(1, "e1", {"marque": "DACIA"}, T0)
        assert etat.fiche_en_cache(1, "e1") == {"marque": "DACIA"}

    def test_une_empreinte_differente_invalide_le_cache(self, etat: EtatSleeper) -> None:
        etat.memoriser_fiche(1, "e1", {"marque": "DACIA"}, T0)
        assert etat.fiche_en_cache(1, "e2") is None

    def test_memoriser_deux_fois_remplace(self, etat: EtatSleeper) -> None:
        etat.memoriser_fiche(1, "e1", {"marque": "DACIA"}, T0)
        etat.memoriser_fiche(1, "e2", {"marque": "RENAULT"}, T1)
        assert etat.fiche_en_cache(1, "e2") == {"marque": "RENAULT"}


class TestVentesEtAdjudications:
    def test_enregistre_puis_cloture_une_vente(self, etat: EtatSleeper) -> None:
        etat.enregistrer_vente(
            vente_id=467,
            intitule="Vente du 27 août",
            direction_regionale="LILLE",
            statut=3,
            nb_lots=161,
            date_ouverture=T0,
            date_cloture=T0,
            horodatage=T0,
        )
        etat.cloturer_ventes_absentes({999}, T1)
        assert etat.ventes_cloturees() == [467]

    def test_une_vente_encore_vue_nest_pas_cloturee(self, etat: EtatSleeper) -> None:
        etat.enregistrer_vente(
            vente_id=467,
            intitule="Vente",
            direction_regionale="LILLE",
            statut=3,
            nb_lots=161,
            date_ouverture=T0,
            date_cloture=T0,
            horodatage=T0,
        )
        etat.cloturer_ventes_absentes({467}, T1)
        assert etat.ventes_cloturees() == []

    def test_conserve_le_prix_dadjudication(self, etat: EtatSleeper) -> None:
        observer(etat, enchere=900.0)
        etat.enregistrer_adjudication(1, 2400.0, 1500.0, T1)
        assert etat.adjudications() == [(1, 2400.0, 1500.0)]

    def test_ladjudication_est_idempotente(self, etat: EtatSleeper) -> None:
        observer(etat)
        etat.enregistrer_adjudication(1, 2400.0, 1500.0, T0)
        etat.enregistrer_adjudication(1, 2400.0, 1500.0, T1)
        assert len(etat.adjudications()) == 1
