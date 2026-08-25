"""Business exclusion rules.

Every rule is covered by real wordings. Domaine staff write freely, so the
variants are tested — and so are the neighbouring turns of phrase that must
NOT fire.

Rule codes stay French: they are part of the output contract and of the
configuration the operator edits.
"""

from __future__ import annotations

import pytest

from sleeper.domain.exclusions import DEFAULT_RULES, ExclusionEngine, LotSignals


def signals(
    description: str = "",
    *,
    mileage: int | None = None,
    has_key: bool | None = None,
    registration_certificate: bool | None = None,
    kind: str | None = None,
    first_registration_year: int | None = None,
    declared_end_of_life: bool | None = None,
    re_registrable: bool | None = None,
    non_compliant: bool | None = None,
    has_vehicle_attributes: bool | None = None,
) -> LotSignals:
    """Build a minimal lot signal, everything else being unknown."""
    return LotSignals(
        description=description,
        mileage=mileage,
        has_key=has_key,
        registration_certificate=registration_certificate,
        kind=kind,
        first_registration_year=first_registration_year,
        declared_end_of_life=declared_end_of_life,
        re_registrable=re_registrable,
        non_compliant=non_compliant,
        has_vehicle_attributes=has_vehicle_attributes,
    )


@pytest.fixture
def engine() -> ExclusionEngine:
    return ExclusionEngine(DEFAULT_RULES)


class TestUnknownMileage:
    @pytest.mark.parametrize(
        "description",
        [
            "DACIA DUSTER, Gazole, 06 cv, 05 places.",
            "kilométrage non renseigné",
            "compteur non fonctionnel, km inconnu",
        ],
    )
    def test_rejects_when_no_mileage_is_readable(
        self, engine: ExclusionEngine, description: str
    ) -> None:
        assert engine.reason(signals(description)) == "kilometrage_inconnu"

    def test_keeps_when_the_structured_attribute_carries_it(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("DACIA DUSTER", mileage=110430)) is None

    def test_keeps_when_the_text_carries_it(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("RENAULT Kangoo, 15500 km.")) is None

    def test_a_zero_odometer_is_not_a_mileage(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("DACIA DUSTER", mileage=0)) == "kilometrage_inconnu"


class TestNoKey:
    @pytest.mark.parametrize(
        "description",
        [
            "véhicule sans clé",
            "clé absente",
            "absence de clés",
            "pas de clef",
            "110000 km, sans clés",
        ],
    )
    def test_variants(self, engine: ExclusionEngine, description: str) -> None:
        assert engine.reason(signals(description, mileage=1)) == "sans_cle"

    def test_the_structured_attribute_wins(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("120000 km", has_key=False)) == "sans_cle"

    def test_a_positive_mention_does_not_fire(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("Avec CG et clé, 120000 km", has_key=True)) is None


class TestNoRegistrationCertificate:
    @pytest.mark.parametrize(
        "description",
        [
            "véhicule sans carte grise",
            "CG absente",
            "absence de certificat d'immatriculation",
            "vendu sans certificat d'immatriculation",
            "pas de carte grise",
        ],
    )
    def test_variants(self, engine: ExclusionEngine, description: str) -> None:
        assert (
            engine.reason(signals(f"{description}, 90000 km")) == "sans_certificat_immatriculation"
        )

    def test_the_structured_attribute_wins(self, engine: ExclusionEngine) -> None:
        assert (
            engine.reason(signals("90000 km", registration_certificate=False))
            == "sans_certificat_immatriculation"
        )

    def test_a_positive_mention_does_not_fire(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("Avec CG et clé, 90000 km")) is None


class TestNotRoadworthy:
    @pytest.mark.parametrize(
        "description",
        ["véhicule non roulant", "véhicule non-roulant", "ne roule pas", "état non roulant"],
    )
    def test_variants(self, engine: ExclusionEngine, description: str) -> None:
        assert engine.reason(signals(f"{description}, 90000 km")) == "non_roulant"

    def test_a_roadworthy_vehicle_does_not_fire(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("véhicule roulant, 90000 km")) is None

    def test_not_re_registrable_fires(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("90000 km", re_registrable=False)) == "non_roulant"


class TestEndOfLife:
    @pytest.mark.parametrize(
        "description",
        ["épave", "vendu pour pièces", "vendu pour pieces détachées", "véhicule hors d'usage"],
    )
    def test_variants(self, engine: ExclusionEngine, description: str) -> None:
        assert engine.reason(signals(f"{description}, 90000 km")) == "epave_ou_pieces"

    def test_declared_end_of_life_fires(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("90000 km", declared_end_of_life=True)) == "epave_ou_pieces"


class TestCrashDamage:
    @pytest.mark.parametrize(
        "description",
        ["véhicule accidenté", "choc avant", "dégâts de carrosserie", "carrosserie endommagée"],
    )
    def test_variants(self, engine: ExclusionEngine, description: str) -> None:
        assert engine.reason(signals(f"{description}, 90000 km")) == "choc_ou_accident"

    @pytest.mark.parametrize(
        "description", ["sans choc apparent", "aucun dégât de carrosserie", "non accidenté"]
    )
    def test_negative_wordings_do_not_fire(self, engine: ExclusionEngine, description: str) -> None:
        assert engine.reason(signals(f"{description}, 90000 km")) is None


class TestDeadEngine:
    @pytest.mark.parametrize(
        "description", ["moteur hors service", "moteur HS", "moteur cassé", "moteur à refaire"]
    )
    def test_variants(self, engine: ExclusionEngine, description: str) -> None:
        assert engine.reason(signals(f"{description}, 90000 km")) == "moteur_hors_service"


class TestLienOrSeizure:
    @pytest.mark.parametrize(
        "description", ["véhicule gagé", "gage en cours", "opposition sur le véhicule"]
    )
    def test_variants(self, engine: ExclusionEngine, description: str) -> None:
        assert engine.reason(signals(f"{description}, 90000 km")) == "gage_ou_opposition"


class TestOutOfScopeKind:
    @pytest.mark.parametrize("kind", ["MTL", "MTT1", "QM", "REM", "TRA"])
    def test_registration_document_kind(self, engine: ExclusionEngine, kind: str) -> None:
        assert engine.reason(signals("90000 km", kind=kind)) == "genre_hors_cible"

    @pytest.mark.parametrize(
        "description",
        [
            "moto YAMAHA",
            "scooter PIAGGIO",
            "quad",
            "remorque plateau",
            "tracteur agricole",
            "voiture sans permis AIXAM",
        ],
    )
    def test_textual_detection(self, engine: ExclusionEngine, description: str) -> None:
        assert engine.reason(signals(f"{description}, 90000 km")) == "genre_hors_cible"

    def test_a_van_stays_in_scope(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("Utilitaire RENAULT Kangoo, 15500 km", kind="CTTE")) is None

    @pytest.mark.parametrize("kind", ["vp", "VP", " vp "])
    def test_case_and_spacing_do_not_matter(self, engine: ExclusionEngine, kind: str) -> None:
        # Relevé en production : le genre arrive en minuscules sur certains lots.
        assert engine.reason(signals("90000 km", kind=kind, mileage=1)) is None

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            ("VASP - DERIV_VP", None),
            ("MTL - GROS CUBE", "genre_hors_cible"),
            ("REM-PLATEAU", "genre_hors_cible"),
        ],
    )
    def test_compound_values_are_read_on_their_j1_code(
        self, engine: ExclusionEngine, kind: str, expected: str | None
    ) -> None:
        """Relevé en production : « VASP - DERIV_VP ». Seul le premier jeton
        est le code de la carte grise ; sans cela un deux-roues libellé
        « MTL - … » passerait à travers."""
        assert engine.reason(signals("90000 km", kind=kind, mileage=1)) == expected


class TestClassicCar:
    def test_before_1990_is_rejected(self, engine: ExclusionEngine) -> None:
        assert (
            engine.reason(signals("90000 km", first_registration_year=1972))
            == "collection_avant_1990"
        )

    def test_1990_is_kept(self, engine: ExclusionEngine) -> None:
        assert engine.reason(signals("90000 km", first_registration_year=1990)) is None


class TestNotAVehicle:
    def test_a_lot_without_vehicle_attributes_gets_the_right_reason(
        self, engine: ExclusionEngine
    ) -> None:
        # A "Véhicules" sale also sells furniture and consumer electronics.
        sofa = signals("Canapé d'angle en cuir", has_vehicle_attributes=False)
        assert engine.reason(sofa) == "hors_categorie_vehicule"

    def test_a_vehicle_passes_the_rule(self, engine: ExclusionEngine) -> None:
        car = signals("DACIA DUSTER", mileage=110430, has_vehicle_attributes=True)
        assert engine.reason(car) is None

    def test_an_unreadable_listing_allows_no_conclusion(self, engine: ExclusionEngine) -> None:
        # Listing missing: we do not pretend to know whether it is a vehicle.
        # The lot falls through to the other rules, here the mileage one.
        unknown = signals("Lot 42", has_vehicle_attributes=None)
        assert engine.reason(unknown) == "kilometrage_inconnu"

    def test_the_rule_runs_before_the_mileage_one(self, engine: ExclusionEngine) -> None:
        sofa = signals("Canapé d'angle", has_vehicle_attributes=False)
        assert engine.reason(sofa) != "kilometrage_inconnu"


class TestOrderAndExtensibility:
    def test_the_first_matching_reason_wins_and_is_deterministic(
        self, engine: ExclusionEngine
    ) -> None:
        # A lot with several defects must always return the same reason.
        several = signals("épave sans clé, moteur HS", mileage=1)
        assert engine.reason(several) == engine.reason(several) == "sans_cle"

    def test_a_phrase_added_by_configuration_is_taken_into_account(self) -> None:
        extended = ExclusionEngine.with_extra_phrases(
            DEFAULT_RULES, {"moteur_hors_service": ("bloc moteur fendu",)}
        )
        assert extended.reason(signals("bloc moteur fendu, 90000 km")) == "moteur_hors_service"

    def test_a_disabled_rule_no_longer_fires(self) -> None:
        without_mileage = ExclusionEngine(
            tuple(r for r in DEFAULT_RULES if r.code != "kilometrage_inconnu")
        )
        assert without_mileage.reason(signals("DACIA DUSTER sans kilométrage")) is None

    def test_an_extra_phrase_on_an_unknown_rule_is_an_error(self) -> None:
        with pytest.raises(KeyError, match="regle_fantome"):
            ExclusionEngine.with_extra_phrases(DEFAULT_RULES, {"regle_fantome": ("peu importe",)})

    def test_the_label_of_an_unknown_reason_is_an_error(self, engine: ExclusionEngine) -> None:
        with pytest.raises(KeyError):
            engine.label("regle_fantome")
