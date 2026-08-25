"""Normalisation and extraction over French free text.

The examples come from the real descriptions captured as fixtures: Domaine
staff each write their own way, typos included.
"""

from __future__ import annotations

import pytest

from sleeper.domain import text


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Réservé aux PROFESSIONNELS", "reserve aux professionnels"),
            ("Véhicule non-roulant.", "vehicule non roulant"),
            ("SANS   CARTE\tGRISE", "sans carte grise"),
            ("Épave — vendu pour pièces", "epave vendu pour pieces"),
            ("moteur H.S.", "moteur h s"),
            ("", ""),
        ],
    )
    def test_strips_accents_case_and_punctuation(self, raw: str, expected: str) -> None:
        assert text.normalize(raw) == expected

    def test_is_idempotent(self) -> None:
        once = text.normalize("Clé absente, C.G. non fournie")
        assert text.normalize(once) == once


class TestFromHtml:
    def test_removes_tags_and_entities(self) -> None:
        html = "<p><strong>Lot r&eacute;serv&eacute;</strong></p>\r\n<p>DACIA&nbsp;DUSTER</p>"
        assert text.from_html(html) == "Lot réservé DACIA DUSTER"

    def test_tolerates_an_empty_source(self) -> None:
        assert text.from_html("") == ""
        assert text.from_html(None) == ""


class TestContains:
    def test_tolerates_accents_case_and_extra_spaces(self) -> None:
        assert text.contains("Véhicule NON   ROULANT", "non roulant")

    def test_requires_whole_words(self) -> None:
        assert not text.contains("chargeur de batterie", "charge")

    def test_ignores_hyphens(self) -> None:
        assert text.contains("vehicule non-roulant", "non roulant")


class TestExtraction:
    DESCRIPTION = (
        "Lot réservé aux professionnels du secteur automobile Utilitaire RENAULT Kangoo, "
        "imm DA 617 PX, Gazole, n° série VF1FC1EAF39868928, "
        "1 ère mise en circulation 03/02/2009 , 06 cv, 02 places, 15500 km. "
        "Dernier CT en date du 03/12/2025"
    )

    def test_extracts_the_vin(self) -> None:
        assert text.extract_vin(self.DESCRIPTION) == "VF1FC1EAF39868928"

    def test_ignores_a_vin_of_invalid_length(self) -> None:
        assert text.extract_vin("n° série ABC123") is None

    def test_extracts_the_tax_horsepower(self) -> None:
        assert text.extract_tax_horsepower(self.DESCRIPTION) == 6

    def test_extracts_the_mileage(self) -> None:
        assert text.extract_mileage(self.DESCRIPTION) == 15500

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("120 000 km", 120000),
            ("kilométrage : 87.500 kms", 87500),
            ("232000KM au compteur", 232000),
            ("pas de kilometrage", None),
        ],
    )
    def test_mileage_variants(self, raw: str, expected: int | None) -> None:
        assert text.extract_mileage(raw) == expected

    def test_extracts_the_inspection_date(self) -> None:
        assert text.extract_inspection_date(self.DESCRIPTION) == "2025-12-03"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("CT OK 05/2027", "2027-05"),
            ("contrôle technique du 12-03-2026", "2026-03-12"),
            ("CT à refaire", None),
        ],
    )
    def test_inspection_date_variants(self, raw: str, expected: str | None) -> None:
        assert text.extract_inspection_date(raw) == expected

    def test_extracts_the_viewing_slot(self) -> None:
        source = "Visites sur place uniquement le Mercredi 29/07/2026 de 08h00 à 11h00"
        assert text.extract_viewing_dates(source) == "Mercredi 29/07/2026 de 08h00 à 11h00"

    def test_stops_before_the_staff_contact_details(self) -> None:
        """A public servant's name and phone number have no business here."""
        source = (
            "Visites sur place uniquement le Mercredi 29/07/2026 de 08h00 à 11h00 "
            "avec Mr DUPONT au 06-00-00-00-00 Enlèvement sur plateau"
        )
        extracted = text.extract_viewing_dates(source)
        assert extracted == "Mercredi 29/07/2026 de 08h00 à 11h00"
        assert "DUPONT" not in (extracted or "")

    def test_accepts_a_spelled_out_month(self) -> None:
        source = "Les visites se feront uniquement le jeudi 23 juillet 2026"
        assert text.extract_viewing_dates(source) == "jeudi 23 juillet 2026"

    def test_the_time_range_is_optional(self) -> None:
        assert text.extract_viewing_dates("Visite le lundi 04/08/2026") == "lundi 04/08/2026"

    def test_no_viewing_returns_none(self) -> None:
        assert text.extract_viewing_dates("Enlèvement à la charge de l'acquéreur") is None

    def test_a_viewing_without_a_date_returns_none(self) -> None:
        assert text.extract_viewing_dates("Visites sur rendez-vous") is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("Crit'Air 2", "2"), ("vignette critair 3", "3"), ("aucune mention", None)],
    )
    def test_extracts_the_crit_air_level(self, raw: str, expected: str | None) -> None:
        assert text.extract_crit_air(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Très bon état général, 90000 km", "Très bon état général"),
            ("Véhicule en bon état", "bon état"),
            ("Réparations à prévoir. Visites sur place", "Réparations à prévoir"),
            ("état d'usage", "état d'usage"),
            ("DACIA DUSTER, Gazole, 06 cv", None),
        ],
    )
    def test_returns_the_condition_mention_verbatim(self, raw: str, expected: str | None) -> None:
        assert text.extract_declared_condition(raw) == expected
