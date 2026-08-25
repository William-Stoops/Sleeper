"""Reference tables: resale quotes and repair allowances.

These values are a **starting point, not a truth**. Every row is stamped
`amorce_a_calibrer`, and calibrating them is the project's main debt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sleeper.errors import ConfigurationError
from sleeper.scoring.tables import QuoteTable, RepairTable

QUOTES = Path("config/cotes.csv")
REPAIRS = Path("config/reparations.csv")


class TestQuoteTable:
    @pytest.fixture
    def table(self) -> QuoteTable:
        return QuoteTable.load(QUOTES)

    def test_the_shipped_table_loads(self, table: QuoteTable) -> None:
        assert len(table) > 50

    def test_every_row_is_marked_as_a_starting_point(self, table: QuoteTable) -> None:
        assert {row.source for row in table.rows} == {"amorce_a_calibrer"}

    def test_a_row_resolves_on_make_model_fuel_and_year(self, table: QuoteTable) -> None:
        row = table.find(make="FORD", model="TRANSIT", fuel="Gazole", year=2021)
        assert row is not None
        assert row.reference_eur == 20000
        assert row.reference_km == 60000

    def test_the_year_must_fall_inside_the_range(self, table: QuoteTable) -> None:
        assert table.find(make="FORD", model="TRANSIT", fuel="Gazole", year=2016) is not None
        assert table.find(make="FORD", model="TRANSIT", fuel="Gazole", year=2005) is None

    def test_resolution_ignores_case_and_spacing(self, table: QuoteTable) -> None:
        assert table.find(make=" ford ", model="transit", fuel="gazole", year=2021) is not None

    def test_an_unknown_model_resolves_to_nothing(self, table: QuoteTable) -> None:
        assert table.find(make="FERRARI", model="F40", fuel="Essence", year=1990) is None

    def test_a_malformed_table_fails_at_load(self, tmp_path: Path) -> None:
        bad = tmp_path / "cotes.csv"
        bad.write_text("marque,modele\nFORD,TRANSIT\n", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="cotes"):
            QuoteTable.load(bad)

    def test_a_missing_table_fails_with_its_path(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="introuvable"):
            QuoteTable.load(tmp_path / "absente.csv")


class TestQuoteComputation:
    @pytest.fixture
    def table(self) -> QuoteTable:
        return QuoteTable.load(QUOTES)

    def test_at_the_reference_mileage_the_quote_is_the_reference(self, table: QuoteTable) -> None:
        assert table.quote(
            make="FORD", model="TRANSIT", fuel="Gazole", year=2021, mileage=60000
        ) == pytest.approx(20000)

    def test_below_the_reference_the_quote_rises(self, table: QuoteTable) -> None:
        # Le Ford Transit 329644 : 27 798 km contre 60 000 de référence.
        quote = table.quote(make="FORD", model="TRANSIT", fuel="Gazole", year=2021, mileage=27798)
        assert quote is not None
        assert quote > 20000

    def test_above_the_reference_the_quote_falls(self, table: QuoteTable) -> None:
        quote = table.quote(make="FORD", model="TRANSIT", fuel="Gazole", year=2021, mileage=150000)
        assert quote is not None
        assert quote < 20000

    def test_the_quote_is_bounded_below_at_a_quarter(self, table: QuoteTable) -> None:
        quote = table.quote(
            make="FORD", model="TRANSIT", fuel="Gazole", year=2021, mileage=2_000_000
        )
        assert quote == pytest.approx(20000 * 0.25)

    def test_the_quote_is_bounded_above_at_one_and_three_quarters(self, table: QuoteTable) -> None:
        # La Twingo décote de 5 % pour 10 000 km sur une référence à 150 000 :
        # à zéro kilomètre l'extrapolation atteint la borne.
        quote = table.quote(make="RENAULT", model="TWINGO", fuel="Essence", year=2010, mileage=0)
        assert quote == pytest.approx(2800 * 1.75)

    def test_a_moderate_decay_does_not_reach_the_upper_bound(self, table: QuoteTable) -> None:
        # 3 % sur 60 000 km ne monte qu'à 1,18 : la borne ne sert qu'aux
        # extrapolations vraiment absurdes.
        quote = table.quote(make="FORD", model="TRANSIT", fuel="Gazole", year=2021, mileage=0)
        assert quote == pytest.approx(20000 * 1.18)

    def test_a_cult_model_barely_decays_with_mileage(self, table: QuoteTable) -> None:
        """Le Defender est volontairement à 1,5 % : c'est le châssis qui compte."""
        at_reference = table.quote(
            make="LAND ROVER", model="DEFENDER", fuel="Gazole", year=2010, mileage=200000
        )
        far_beyond = table.quote(
            make="LAND ROVER", model="DEFENDER", fuel="Gazole", year=2010, mileage=300000
        )
        assert at_reference is not None and far_beyond is not None
        assert far_beyond / at_reference > 0.8

    def test_an_unknown_model_has_no_quote(self, table: QuoteTable) -> None:
        assert (
            table.quote(make="FERRARI", model="F40", fuel="Essence", year=1990, mileage=10000)
            is None
        )

    def test_an_unknown_mileage_has_no_quote(self, table: QuoteTable) -> None:
        assert (
            table.quote(make="FORD", model="TRANSIT", fuel="Gazole", year=2021, mileage=None)
            is None
        )


class TestRepairTable:
    @pytest.fixture
    def table(self) -> RepairTable:
        return RepairTable.load(REPAIRS)

    def test_the_shipped_table_loads(self, table: RepairTable) -> None:
        assert len(table) == 20

    def test_it_finds_a_dead_engine(self, table: RepairTable) -> None:
        found = table.match("moteur HS, 120000 km")
        assert [f.code for f in found] == ["moteur_hs"]
        assert found[0].cost_eur == 3500
        assert found[0].severity == "redhibitoire"
        assert "moteur HS" in found[0].evidence

    def test_it_quotes_the_fragment_that_fired(self, table: RepairTable) -> None:
        found = table.match("Prévoir kit embrayage et distribution à prévoir.")
        assert {f.code for f in found} == {"embrayage", "distribution"}
        assert all(f.evidence for f in found)

    def test_a_leased_traction_battery_costs_nothing_and_kills(self, table: RepairTable) -> None:
        """Le piège de la Zoé : la batterie appartient à Renault."""
        found = table.match(
            "Ce véhicule est vendu sans la propriété de la batterie. La batterie reste "
            "la propriété de Renault et est soumise à un contrat de location obligatoire "
            "avec DIAC Location."
        )
        battery = next(f for f in found if f.code == "batterie_traction_location")
        assert battery.cost_eur == 0
        assert battery.severity == "redhibitoire"

    def test_an_unknown_mechanical_state_is_only_a_signal(self, table: RepairTable) -> None:
        found = table.match("État mécanique non connu.")
        assert [f.code for f in found] == ["etat_meca_inconnu"]
        assert found[0].cost_eur == 0
        assert found[0].severity == "signal"

    def test_a_clean_description_triggers_nothing(self, table: RepairTable) -> None:
        assert table.match("DACIA DUSTER, Gazole, 110430 km, très bon état général") == []

    def test_the_order_is_stable(self, table: RepairTable) -> None:
        description = "moteur HS, 4 pneus, batterie HS"
        assert [f.code for f in table.match(description)] == [
            f.code for f in table.match(description)
        ]


class TestOrdinaryWordsTriggerNothing:
    """Le faux positif le plus coûteux du projet, et sa clôture.

    « RTI » n'était pas ancré : il se cachait dans « ce*rti*ficat », mot
    présent dans presque chaque annonce. 92 lots du run du 25 août étaient
    facturés 2 500 € de vitrage imaginaire et classés « lourd » ; cinq
    seulement l'étaient à raison.
    """

    @pytest.fixture
    def table(self) -> RepairTable:
        return RepairTable.load(REPAIRS)

    @pytest.mark.parametrize(
        "description",
        [
            "Véhicule roulant, avec clé, avec certificat d'immatriculation.",
            "Enlèvement avec certificat d'assurance en cours de validité.",
            "Certificat de cession fourni. Carte grise disponible.",
            "certificat d'immatriculation manquant",
        ],
    )
    def test_a_certificate_triggers_no_rule(self, table: RepairTable, description: str) -> None:
        assert table.match(description) == []

    def test_the_real_wording_still_fires(self, table: RepairTable) -> None:
        """Les cinq lots légitimes du run doivent rester détectés."""
        for wording in (
            "Le vitrage n'est pas réceptionné, retrait obligatoire",
            "Vitrages non conformes à remplacer intégralement",
            "faire obligatoirement une réception à titre isolé (RTI) à votre charge",
        ):
            assert [f.code for f in table.match(wording)] == ["vitrage_non_receptionne"], wording

    def test_rti_as_a_word_still_fires(self, table: RepairTable) -> None:
        assert [f.code for f in table.match("Passage en RTI obligatoire.")] == [
            "vitrage_non_receptionne"
        ]


class TestPatternAnchoring:
    """Un motif court non ancré est refusé au démarrage, pas découvert après."""

    def _table(self, tmp_path: Path, pattern: str) -> RepairTable:
        csv = tmp_path / "reparations.csv"
        csv.write_text(
            f'motif,pattern,cout_eur,gravite\nessai,"{pattern}",100,leger\n', encoding="utf-8"
        )
        return RepairTable.load(csv)

    @pytest.mark.parametrize("pattern", ["RTI", "moteur HS|BV", "ABS", "a|batterie HS"])
    def test_a_short_unanchored_alternative_is_refused(self, tmp_path: Path, pattern: str) -> None:
        with pytest.raises(ConfigurationError, match="trop court et non ancré"):
            self._table(tmp_path, pattern)

    @pytest.mark.parametrize(
        "pattern", [r"\bRTI\b", "moteur HS", r"embrayage.{0,10}HS|\bBV\b", "vitrages? non conforme"]
    )
    def test_an_anchored_or_long_alternative_passes(self, tmp_path: Path, pattern: str) -> None:
        assert len(self._table(tmp_path, pattern)) == 1

    def test_the_shipped_table_obeys_the_rule(self) -> None:
        """La règle vaut pour le fichier livré, pas seulement pour les fixtures."""
        assert len(RepairTable.load(REPAIRS)) == 20
