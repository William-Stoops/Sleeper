"""Filtre geographique : le lieu de RETRAIT, jamais le siege de la vente."""

from __future__ import annotations

import pytest

from sleeper.domain.perimetre import Perimetre, departement_depuis_code_postal


class TestDepartementDepuisCodePostal:
    @pytest.mark.parametrize(
        ("code_postal", "attendu"),
        [
            ("59000", "59"),
            ("62100", "62"),
            ("75015", "75"),
            ("01000", "01"),
        ],
    )
    def test_metropole(self, code_postal: str, attendu: str) -> None:
        assert departement_depuis_code_postal(code_postal) == attendu

    @pytest.mark.parametrize(
        ("code_postal", "attendu"),
        [("20000", "2A"), ("20090", "2A"), ("20200", "2B"), ("20600", "2B")],
    )
    def test_corse_est_scindee_sur_le_seuil_reel(self, code_postal: str, attendu: str) -> None:
        assert departement_depuis_code_postal(code_postal) == attendu

    @pytest.mark.parametrize(
        ("code_postal", "attendu"),
        [("97470", "974"), ("97100", "971"), ("97600", "976"), ("98800", "988")],
    )
    def test_outre_mer_tient_sur_trois_chiffres(self, code_postal: str, attendu: str) -> None:
        assert departement_depuis_code_postal(code_postal) == attendu

    @pytest.mark.parametrize("code_postal", ["", "  ", "abcde", "123", "1234567", None])
    def test_code_illisible_renvoie_none(self, code_postal: str | None) -> None:
        assert departement_depuis_code_postal(code_postal) is None

    def test_tolere_les_espaces_de_saisie(self) -> None:
        assert departement_depuis_code_postal(" 59 000 ") == "59"


class TestPerimetre:
    @pytest.fixture
    def perimetre(self) -> Perimetre:
        return Perimetre(
            departements=frozenset({"59", "62", "80", "02"}),
            pays_etrangers=frozenset({"BE", "LU"}),
        )

    def test_departement_liste_est_dans_le_perimetre(self, perimetre: Perimetre) -> None:
        assert perimetre.contient(code_postal="59260", lieu="LILLE") is True

    def test_departement_hors_liste_est_hors_perimetre(self, perimetre: Perimetre) -> None:
        assert perimetre.contient(code_postal="97470", lieu="SAINT-BENOIT") is False

    def test_mention_pays_etranger_ramene_dans_le_perimetre(self, perimetre: Perimetre) -> None:
        assert perimetre.contient(code_postal="1000", lieu="BRUXELLES (BELGIQUE)") is True
        assert perimetre.contient(code_postal="1855", lieu="Luxembourg") is True

    def test_pays_etranger_non_retenu_reste_dehors(self, perimetre: Perimetre) -> None:
        assert perimetre.contient(code_postal="28001", lieu="MADRID (ESPAGNE)") is False

    def test_code_postal_illisible_est_hors_perimetre_et_non_une_erreur(
        self, perimetre: Perimetre
    ) -> None:
        # Un lot sans lieu exploitable est conserve mais marque hors perimetre :
        # c'est l'operateur qui tranchera, pas l'outil.
        assert perimetre.contient(code_postal=None, lieu=None) is False
