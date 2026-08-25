"""Normalisation et extraction sur du texte libre francais.

Les exemples proviennent des descriptions reelles capturees en fixtures : les
agents du Domaine ecrivent chacun a leur maniere, fautes de frappe comprises.
"""

from __future__ import annotations

import pytest

from sleeper.domain import texte


class TestNormaliser:
    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("Réservé aux PROFESSIONNELS", "reserve aux professionnels"),
            ("Véhicule non-roulant.", "vehicule non roulant"),
            ("SANS   CARTE\tGRISE", "sans carte grise"),
            ("Épave — vendu pour pièces", "epave vendu pour pieces"),
            ("moteur H.S.", "moteur h s"),
            ("", ""),
        ],
    )
    def test_supprime_accents_casse_et_ponctuation(self, brut: str, attendu: str) -> None:
        assert texte.normaliser(brut) == attendu

    def test_est_idempotente(self) -> None:
        une_fois = texte.normaliser("Clé absente, C.G. non fournie")
        assert texte.normaliser(une_fois) == une_fois


class TestDepuisHtml:
    def test_degage_les_balises_et_les_entites(self) -> None:
        html = "<p><strong>Lot r&eacute;serv&eacute;</strong></p>\r\n<p>DACIA&nbsp;DUSTER</p>"
        assert texte.depuis_html(html) == "Lot réservé DACIA DUSTER"

    def test_supporte_une_source_vide(self) -> None:
        assert texte.depuis_html("") == ""
        assert texte.depuis_html(None) == ""


class TestContientExpression:
    def test_tolere_accents_casse_et_espaces_multiples(self) -> None:
        assert texte.contient("Véhicule NON   ROULANT", "non roulant")

    def test_exige_des_mots_entiers(self) -> None:
        # « clef » ne doit pas declencher sur « clefs de bridage » vs « sans cle »
        assert not texte.contient("chargeur de batterie", "charge")

    def test_ignore_les_traits_dunion(self) -> None:
        assert texte.contient("vehicule non-roulant", "non roulant")


class TestExtractions:
    DESCRIPTION = (
        "Lot réservé aux professionnels du secteur automobile Utilitaire RENAULT Kangoo, "
        "imm DA 617 PX, Gazole, n° série VF1FC1EAF39868928, "
        "1 ère mise en circulation 03/02/2009 , 06 cv, 02 places, 15500 km. "
        "Dernier CT en date du 03/12/2025"
    )

    def test_extrait_le_vin(self) -> None:
        assert texte.extraire_vin(self.DESCRIPTION) == "VF1FC1EAF39868928"

    def test_ignore_un_vin_de_longueur_invalide(self) -> None:
        assert texte.extraire_vin("n° série ABC123") is None

    def test_extrait_la_puissance_fiscale(self) -> None:
        assert texte.extraire_puissance_fiscale(self.DESCRIPTION) == 6

    def test_extrait_le_kilometrage(self) -> None:
        assert texte.extraire_kilometrage(self.DESCRIPTION) == 15500

    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("120 000 km", 120000),
            ("kilométrage : 87.500 kms", 87500),
            ("232000KM au compteur", 232000),
            ("pas de kilometrage", None),
        ],
    )
    def test_variantes_de_kilometrage(self, brut: str, attendu: int | None) -> None:
        assert texte.extraire_kilometrage(brut) == attendu

    def test_extrait_la_date_de_controle_technique(self) -> None:
        assert texte.extraire_controle_technique(self.DESCRIPTION) == "2025-12-03"

    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("CT OK 05/2027", "2027-05"),
            ("contrôle technique du 12-03-2026", "2026-03-12"),
            ("CT à refaire", None),
        ],
    )
    def test_variantes_de_controle_technique(self, brut: str, attendu: str | None) -> None:
        assert texte.extraire_controle_technique(brut) == attendu

    def test_extrait_les_dates_de_visite(self) -> None:
        source = "Visites sur place uniquement le Mercredi 29/07/2026 de 08h00 à 11h00"
        assert texte.extraire_dates_visite(source) == "Mercredi 29/07/2026 de 08h00 à 11h00"

    def test_absence_de_visite_renvoie_none(self) -> None:
        assert texte.extraire_dates_visite("Enlèvement à la charge de l'acquéreur") is None

    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [("Crit'Air 2", "2"), ("vignette critair 3", "3"), ("aucune mention", None)],
    )
    def test_extrait_le_crit_air(self, brut: str, attendu: str | None) -> None:
        assert texte.extraire_crit_air(brut) == attendu


class TestEtatDeclare:
    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("Très bon état général, 90000 km", "Très bon état général"),
            ("Véhicule en bon état", "bon état"),
            ("Réparations à prévoir. Visites sur place", "Réparations à prévoir"),
            ("état d'usage", "état d'usage"),
            ("DACIA DUSTER, Gazole, 06 cv", None),
        ],
    )
    def test_rend_la_mention_telle_quelle(self, brut: str, attendu: str | None) -> None:
        assert texte.extraire_etat_declare(brut) == attendu
