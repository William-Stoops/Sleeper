"""Geographic filter: the COLLECTION point, never the seat of the sale."""

from __future__ import annotations

import pytest

from sleeper.domain.territory import Perimeter, department_from_postcode


class TestDepartmentFromPostcode:
    @pytest.mark.parametrize(
        ("postcode", "expected"),
        [("59000", "59"), ("62100", "62"), ("75015", "75"), ("01000", "01")],
    )
    def test_mainland(self, postcode: str, expected: str) -> None:
        assert department_from_postcode(postcode) == expected

    @pytest.mark.parametrize(
        ("postcode", "expected"),
        [("20000", "2A"), ("20090", "2A"), ("20200", "2B"), ("20600", "2B")],
    )
    def test_corsica_splits_on_the_real_threshold(self, postcode: str, expected: str) -> None:
        assert department_from_postcode(postcode) == expected

    @pytest.mark.parametrize(
        ("postcode", "expected"),
        [("97470", "974"), ("97100", "971"), ("97600", "976"), ("98800", "988")],
    )
    def test_overseas_needs_three_digits(self, postcode: str, expected: str) -> None:
        assert department_from_postcode(postcode) == expected

    @pytest.mark.parametrize("postcode", ["", "  ", "abcde", "123", "1234567", None])
    def test_an_unreadable_code_returns_none(self, postcode: str | None) -> None:
        assert department_from_postcode(postcode) is None

    def test_tolerates_typing_spaces(self) -> None:
        assert department_from_postcode(" 59 000 ") == "59"


class TestScopeStatus:
    """Correctif 1 : un lieu vide ne veut pas dire hors périmètre.

    La vente 567 « spéciale véhicule d'exception » s'était évaporée du scan
    parce qu'un champ texte vide faisait tomber un booléen à false.
    """

    @pytest.fixture
    def perimeter(self) -> Perimeter:
        return Perimeter(
            departments=frozenset({"59", "62", "27"}),
            foreign_countries=frozenset({"BE", "LU"}),
        )

    def test_a_listed_department_is_inside(self, perimeter: Perimeter) -> None:
        assert perimeter.status(postcode="59260", location="LILLE") == "dans"

    def test_an_unlisted_department_is_outside(self, perimeter: Perimeter) -> None:
        assert perimeter.status(postcode="97470", location="SAINT-BENOIT") == "hors"

    @pytest.mark.parametrize(
        ("postcode", "location"),
        [(None, None), ("", ""), ("   ", ""), ("abcde", ""), ("123", "")],
    )
    def test_an_unreadable_location_is_unknown_never_outside(
        self, perimeter: Perimeter, postcode: str | None, location: str
    ) -> None:
        assert perimeter.status(postcode=postcode, location=location) == "inconnu"

    def test_a_retained_foreign_country_is_inside(self, perimeter: Perimeter) -> None:
        assert perimeter.status(postcode="1000", location="BRUXELLES (BELGIQUE)") == "dans"

    def test_an_unretained_foreign_country_is_outside(self, perimeter: Perimeter) -> None:
        assert perimeter.status(postcode="28001", location="MADRID (ESPAGNE)") == "hors"

    def test_the_evreux_lot_of_the_transit_is_inside(self, perimeter: Perimeter) -> None:
        # Lot 329644, le meilleur dossier du run du 25/08.
        assert perimeter.status(postcode="27000", location="EVREUX") == "dans"


class TestScopeResolution:
    """Un lot sans lieu hérite de celui de sa vente, sans jamais être exclu."""

    @pytest.fixture
    def perimeter(self) -> Perimeter:
        return Perimeter(departments=frozenset({"59", "63"}))

    def test_a_lot_with_its_own_place_does_not_inherit(self, perimeter: Perimeter) -> None:
        resolved = perimeter.resolve(
            postcode="59000", location="LILLE", sale_postcode="63000", sale_location="CLERMONT"
        )
        assert resolved.status == "dans"
        assert resolved.inherited is False
        assert resolved.postcode == "59000"

    def test_a_lot_without_a_place_inherits_from_its_sale(self, perimeter: Perimeter) -> None:
        resolved = perimeter.resolve(
            postcode="", location="", sale_postcode="63000", sale_location="CLERMONT-FERRAND"
        )
        assert resolved.status == "dans"
        assert resolved.inherited is True
        assert (resolved.postcode, resolved.location) == ("63000", "CLERMONT-FERRAND")

    def test_both_empty_is_unknown(self, perimeter: Perimeter) -> None:
        # Cas réel de la vente 567 : ni la vente ni son lot n'ont de lieu.
        resolved = perimeter.resolve(postcode="", location="", sale_postcode="", sale_location="")
        assert resolved.status == "inconnu"
        assert resolved.inherited is False

    def test_a_lot_outside_stays_outside_even_when_its_sale_is_inside(
        self, perimeter: Perimeter
    ) -> None:
        # Cas réel : lots de Limoges (87) dans la vente 517 de Clermont-Ferrand.
        resolved = perimeter.resolve(
            postcode="87000", location="LIMOGES", sale_postcode="63000", sale_location="CLERMONT"
        )
        assert resolved.status == "hors"
        assert resolved.inherited is False
