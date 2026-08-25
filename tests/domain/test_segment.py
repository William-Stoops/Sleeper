"""Vehicle segment, and the registrable-vehicle predicate.

Correctif 6: five engines — a Broyeur DURATECH, a Cribleur Ménart, a
Chargeur télescopique — came out of the run rejected for `sans_cle`. They are
not vehicles without a key; they are machines that should never have reached
a condition filter. The category test asked "does the listing carry a make?",
and a Broyeur carries one.

The test is now "is this a registrable road vehicle?" — a J.1 code, a plate,
or a VIN. That predicate keeps the IVECO road tractor, which is a real
vehicle, and drops the machines.
"""

from __future__ import annotations

import pytest

from sleeper.domain.segment import classify_segment, is_registrable


class TestRegistrablePredicate:
    @pytest.mark.parametrize(
        ("kind", "plate", "vin"),
        [
            ("VP", "", ""),
            ("", "DY-868-KA", ""),
            ("", "", "VF1FL000765414484"),
            ("CTTE", "AB-123-CD", "VF1FL000765414484"),
        ],
    )
    def test_any_registration_evidence_is_enough(self, kind: str, plate: str, vin: str) -> None:
        assert is_registrable(kind=kind, plate=plate, vin=vin) is True

    def test_nothing_at_all_is_not_registrable(self) -> None:
        assert is_registrable(kind="", plate="", vin="") is False

    def test_the_iveco_road_tractor_is_registrable(self) -> None:
        # Lot 306095, écarté à tort pour sans_cle dans le run du 25/08.
        assert is_registrable(kind="TRR", plate="", vin="WJME2NSH004321234") is True


class TestSegment:
    @pytest.mark.parametrize("kind", ["VP", "vp", " VP "])
    def test_a_passenger_car_is_vl(self, kind: str) -> None:
        assert classify_segment(kind=kind, plate="AB-123-CD", vin="", title="RENAULT CLIO") == "vl"

    @pytest.mark.parametrize("kind", ["CTTE", "VASP - DERIV_VP"])
    def test_a_van_is_vu(self, kind: str) -> None:
        assert classify_segment(kind=kind, plate="AB-123-CD", vin="", title="FORD Transit") == "vu"

    @pytest.mark.parametrize("kind", ["CAM", "TRR", "TCP", "REM", "SREM"])
    def test_heavy_kinds_are_pl(self, kind: str) -> None:
        assert classify_segment(kind=kind, plate="AB-123-CD", vin="", title="IVECO") == "pl"

    @pytest.mark.parametrize(
        "title",
        ["Broyeur DURATECH", "Cribleur Rotatif Ménart TR1535", "Chargeur telescopique"],
    )
    def test_a_machine_without_registration_is_an_engin(self, title: str) -> None:
        assert classify_segment(kind="", plate="", vin="", title=title) == "engin"

    def test_the_iveco_road_tractor_is_pl_not_an_engin(self) -> None:
        segment = classify_segment(
            kind="TRR", plate="", vin="WJME2NSH004321234", title="Tracteur routier IVECO MH440E"
        )
        assert segment == "pl"

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Autocar MERCEDES Intouro", "pl"),
            ("Camion benne RENAULT", "pl"),
            ("Ambulance RENAULT Master", "vu"),
            ("Utilitaire PEUGEOT Partner", "vu"),
            ("RENAULT CLIO", "vl"),
        ],
    )
    def test_an_unknown_kind_falls_back_on_the_title(self, title: str, expected: str) -> None:
        # 71 lots du run réel n'ont pas de code J.1 mais portent une plaque.
        assert classify_segment(kind="", plate="AB-123-CD", vin="", title=title) == expected

    def test_a_registrable_vehicle_of_unknown_shape_defaults_to_vl(self) -> None:
        assert classify_segment(kind="", plate="AB-123-CD", vin="", title="???") == "vl"
