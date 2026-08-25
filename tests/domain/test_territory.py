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


class TestPerimeter:
    @pytest.fixture
    def perimeter(self) -> Perimeter:
        return Perimeter(
            departments=frozenset({"59", "62", "80", "02"}),
            foreign_countries=frozenset({"BE", "LU"}),
        )

    def test_a_listed_department_is_in_scope(self, perimeter: Perimeter) -> None:
        assert perimeter.contains(postcode="59260", location="LILLE") is True

    def test_an_unlisted_department_is_out_of_scope(self, perimeter: Perimeter) -> None:
        assert perimeter.contains(postcode="97470", location="SAINT-BENOIT") is False

    def test_a_retained_foreign_country_comes_back_in_scope(self, perimeter: Perimeter) -> None:
        assert perimeter.contains(postcode="1000", location="BRUXELLES (BELGIQUE)") is True
        assert perimeter.contains(postcode="1855", location="Luxembourg") is True

    def test_an_unretained_foreign_country_stays_out(self, perimeter: Perimeter) -> None:
        assert perimeter.contains(postcode="28001", location="MADRID (ESPAGNE)") is False

    def test_an_unreadable_postcode_is_out_of_scope_not_an_error(
        self, perimeter: Perimeter
    ) -> None:
        # A lot with no usable location is kept but flagged out of scope: the
        # operator decides, not the tool.
        assert perimeter.contains(postcode=None, location=None) is False
