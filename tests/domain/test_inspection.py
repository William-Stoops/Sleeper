"""Roadworthiness test parsing.

Correctif 4: the field mixed three kinds of value — "absent", "présent", and
an ISO date — and "absent" was ambiguous: no test, or a listing that says
nothing? On this seam the difference decides the resale.

The wordings below are the official ones and appear verbatim in the listings.
"""

from __future__ import annotations

from datetime import date

import pytest

from sleeper.domain.inspection import read_inspection

RUN_DAY = date(2026, 8, 25)


class TestNoMention:
    @pytest.mark.parametrize(
        "description", ["DACIA DUSTER, Gazole, 06 cv, 05 places.", "", "120000 km"]
    )
    def test_a_silent_listing_is_not_a_missing_test(self, description: str) -> None:
        ct = read_inspection(description, structured=None, run_day=RUN_DAY)
        assert ct.mentionne is False
        assert ct.date is None
        assert ct.resultat == "inconnu"
        assert ct.valide_a_la_date_du_run is None

    def test_the_structured_attribute_alone_says_it_was_mentioned(self) -> None:
        ct = read_inspection("", structured=False, run_day=RUN_DAY)
        assert ct.mentionne is True
        assert ct.date is None
        assert ct.resultat == "inconnu"
        assert ct.valide_a_la_date_du_run is None


class TestOfficialWordings:
    def test_favourable_with_minor_defects(self) -> None:
        ct = read_inspection(
            "Contrôle technique favorable du 16/07/2026 avec défaillances mineures",
            structured=True,
            run_day=RUN_DAY,
        )
        assert ct.resultat == "favorable_defaillances_mineures"
        assert ct.date == date(2026, 7, 16)
        assert ct.valide_a_la_date_du_run is True

    def test_unfavourable_with_retest(self) -> None:
        ct = read_inspection(
            "Contrôle technique défavorable avec contre-visite du 29/07/2026",
            structured=True,
            run_day=RUN_DAY,
        )
        assert ct.resultat == "defavorable_contre_visite"
        assert ct.date == date(2026, 7, 29)

    def test_a_dated_test_without_a_verdict(self) -> None:
        ct = read_inspection(
            "Contrôle technique du 29/07/2026 consultable sur les documents en ligne",
            structured=True,
            run_day=RUN_DAY,
        )
        assert ct.mentionne is True
        assert ct.date == date(2026, 7, 29)
        assert ct.resultat == "inconnu"

    def test_major_unrepaired_defects_are_unfavourable(self) -> None:
        ct = read_inspection(
            "dernier CT du 09/02/2023 avec défaillances majeures non réparées",
            structured=True,
            run_day=RUN_DAY,
        )
        assert ct.resultat == "defavorable_contre_visite"
        assert ct.date == date(2023, 2, 9)

    def test_an_explicitly_invalid_test(self) -> None:
        ct = read_inspection(
            "Pour information, contrôle technique non valide du 03/06/2026",
            structured=True,
            run_day=RUN_DAY,
        )
        assert ct.date == date(2026, 6, 3)
        assert ct.valide_a_la_date_du_run is False

    def test_a_plain_favourable_test(self) -> None:
        ct = read_inspection(
            "Contrôle technique favorable du 02/07/2026", structured=True, run_day=RUN_DAY
        )
        assert ct.resultat == "favorable"
        assert ct.valide_a_la_date_du_run is True


class TestExpiryTrap:
    def test_expiry_overrides_a_favourable_verdict(self) -> None:
        """« CT favorable du 10/07/2026 (périmé) » — la péremption prime."""
        ct = read_inspection(
            "CT favorable du 10/07/2026 (périmé)", structured=True, run_day=RUN_DAY
        )
        assert ct.resultat == "favorable"
        assert ct.valide_a_la_date_du_run is False

    def test_an_old_test_has_lapsed_on_its_own(self) -> None:
        # Un contrôle technique de tourisme vaut deux ans.
        ct = read_inspection(
            "Contrôle technique favorable du 09/02/2023", structured=True, run_day=RUN_DAY
        )
        assert ct.valide_a_la_date_du_run is False

    def test_validity_is_unknown_without_a_date(self) -> None:
        ct = read_inspection(
            "Contrôle technique favorable, date non précisée", structured=True, run_day=RUN_DAY
        )
        assert ct.date is None
        assert ct.valide_a_la_date_du_run is None
