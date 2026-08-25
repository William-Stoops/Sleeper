"""End-of-run integrity checks.

Correctif 5: in sale 467, lots 192177 and 271498 carry the same serial number
`VF7VAYHVKKZ078443` with different mileages. Either the source has a typo or
an assignment is wrong — and nothing said a word.

These checks never fail the run. They feed `run.erreurs`, because the operator
must be able to see them and decide.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from sleeper.domain.integrity import Anomaly, check_integrity

RUN_DAY = dt.date(2026, 8, 25)


def lot(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "1",
        "vin": "VF1FL000765414484",
        "mileage": 33887,
        "first_registration_year": 2021,
        "starting_price": 800.0,
        "current_bid": None,
    }
    base.update(overrides)
    return base


def codes(anomalies: list[Anomaly]) -> set[str]:
    return {a.code for a in anomalies}


class TestCleanRun:
    def test_a_sound_lot_raises_nothing(self) -> None:
        assert check_integrity([lot()], run_day=RUN_DAY) == []


class TestDuplicateVin:
    def test_the_real_duplicate_is_reported_with_both_lots(self) -> None:
        anomalies = check_integrity(
            [
                lot(id="192177", vin="VF7VAYHVKKZ078443", mileage=294364),
                lot(id="271498", vin="VF7VAYHVKKZ078443", mileage=273545),
            ],
            run_day=RUN_DAY,
        )
        duplicates = [a for a in anomalies if a.code == "vin_double"]
        assert len(duplicates) == 1
        assert duplicates[0].lot_ids == ("192177", "271498")
        assert duplicates[0].value == "VF7VAYHVKKZ078443"

    def test_an_empty_vin_is_not_a_duplicate(self) -> None:
        anomalies = check_integrity([lot(id="1", vin=""), lot(id="2", vin="")], run_day=RUN_DAY)
        assert "vin_double" not in codes(anomalies)


class TestVinFormat:
    @pytest.mark.parametrize("vin", ["VF1FL00076541448", "VF1FL0007654144840", "VF1FL0007654I448"])
    def test_a_malformed_vin_is_reported(self, vin: str) -> None:
        assert "vin_malforme" in codes(check_integrity([lot(vin=vin)], run_day=RUN_DAY))

    def test_a_well_formed_vin_passes(self) -> None:
        assert "vin_malforme" not in codes(
            check_integrity([lot(vin="WF0FXXTTRFMU20040")], run_day=RUN_DAY)
        )

    def test_an_absent_vin_is_not_malformed(self) -> None:
        assert "vin_malforme" not in codes(check_integrity([lot(vin="")], run_day=RUN_DAY))


class TestMileageCoherence:
    def test_an_implausibly_high_yearly_mileage_is_reported(self) -> None:
        anomalies = check_integrity(
            [lot(mileage=852481, first_registration_year=2021)], run_day=RUN_DAY
        )
        assert "kilometrage_incoherent" in codes(anomalies)

    def test_a_truck_at_high_total_mileage_over_many_years_passes(self) -> None:
        """Le Magnum de 1998 à 852 481 km du run réel : 30 000 km/an, normal."""
        anomalies = check_integrity(
            [lot(mileage=852481, first_registration_year=1998)], run_day=RUN_DAY
        )
        assert "kilometrage_incoherent" not in codes(anomalies)

    def test_an_implausibly_low_yearly_mileage_is_reported(self) -> None:
        anomalies = check_integrity(
            [lot(mileage=1200, first_registration_year=2005)], run_day=RUN_DAY
        )
        assert "kilometrage_incoherent" in codes(anomalies)

    def test_a_normal_yearly_mileage_passes(self) -> None:
        anomalies = check_integrity(
            [lot(mileage=120000, first_registration_year=2016)], run_day=RUN_DAY
        )
        assert "kilometrage_incoherent" not in codes(anomalies)


class TestRegistrationDate:
    def test_a_future_registration_is_reported(self) -> None:
        anomalies = check_integrity([lot(first_registration_year=2030)], run_day=RUN_DAY)
        assert "mise_en_circulation_invalide" in codes(anomalies)

    def test_a_registration_before_1950_is_reported(self) -> None:
        anomalies = check_integrity([lot(first_registration_year=1930)], run_day=RUN_DAY)
        assert "mise_en_circulation_invalide" in codes(anomalies)


class TestPrices:
    @pytest.mark.parametrize("price", [0.0, -100.0, 600000.0])
    def test_an_implausible_starting_price_is_reported(self, price: float) -> None:
        anomalies = check_integrity([lot(starting_price=price)], run_day=RUN_DAY)
        assert "mise_a_prix_invalide" in codes(anomalies)

    def test_a_bid_below_the_starting_price_is_reported(self) -> None:
        anomalies = check_integrity(
            [lot(starting_price=1500.0, current_bid=900.0)], run_day=RUN_DAY
        )
        assert "enchere_inferieure_mise_a_prix" in codes(anomalies)

    def test_a_bid_at_the_starting_price_passes(self) -> None:
        anomalies = check_integrity(
            [lot(starting_price=1500.0, current_bid=1500.0)], run_day=RUN_DAY
        )
        assert anomalies == []


class TestAnomalyShape:
    def test_every_anomaly_carries_its_lot_and_its_faulty_value(self) -> None:
        anomalies = check_integrity([lot(id="42", starting_price=-5.0)], run_day=RUN_DAY)
        assert anomalies[0].lot_ids == ("42",)
        assert anomalies[0].value == "-5.0"
        assert anomalies[0].message
