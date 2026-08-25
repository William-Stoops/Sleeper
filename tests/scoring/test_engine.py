"""The scoring engine.

**This is a sort, not a valuation.** It is coarse, fast, entirely
deterministic, explainable line by line, and above all conservative: better to
surface a mediocre lot than to bury a good one. It decides no purchase — only
who gets the expensive analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from sleeper.config import ScoringConfig
from sleeper.domain.damage import BodyDamage
from sleeper.domain.segment import Segment
from sleeper.domain.territory import ScopeStatus
from sleeper.scoring.engine import ScoreInput, ScoringEngine
from sleeper.scoring.tables import QuoteTable, RepairTable


@pytest.fixture
def engine() -> ScoringEngine:
    return ScoringEngine(
        quotes=QuoteTable.load(Path("config/cotes.csv")),
        repairs=RepairTable.load(Path("config/reparations.csv")),
        settings=ScoringConfig(),
        active_segments=frozenset({"vl", "vu"}),
    )


def candidate(**overrides: object) -> ScoreInput:
    """The Ford Transit 329644, the best file of the run, unless overridden."""
    base: dict[str, object] = {
        "lot_id": "329644",
        "make": "FORD",
        "model": "TRANSIT",
        "fuel": "Gazole",
        "gearbox": "Boîte manuelle",
        "year": 2021,
        "mileage": 27798,
        "mileage_per_year": 5560,
        "starting_price": 800.0,
        "buyer_fee_pct": 14.4,
        "description": "Utilitaire FORD Transit, choc AR, multiples chocs sur carrosserie.",
        "trade_only": True,
        "body_damage": "cosmetique",
        "scope": "dans",
        "segment": "vu",
        "recent_favourable_inspection": False,
    }
    base.update(overrides)
    return ScoreInput(
        lot_id=str(base["lot_id"]),
        make=str(base["make"]),
        model=str(base["model"]),
        fuel=str(base["fuel"]),
        gearbox=str(base["gearbox"]),
        year=cast("int | None", base["year"]),
        mileage=cast("int | None", base["mileage"]),
        mileage_per_year=cast("int | None", base["mileage_per_year"]),
        starting_price=cast("float | None", base["starting_price"]),
        buyer_fee_pct=cast("float | None", base["buyer_fee_pct"]),
        description=str(base["description"]),
        trade_only=cast("bool | None", base["trade_only"]),
        body_damage=cast("BodyDamage", base["body_damage"]),
        scope=cast("ScopeStatus", base["scope"]),
        segment=cast("Segment", base["segment"]),
        recent_favourable_inspection=bool(base["recent_favourable_inspection"]),
    )


class TestTheFormula:
    def test_the_quote_the_cost_and_the_margin_are_computed(self, engine: ScoringEngine) -> None:
        result = engine.score(candidate())
        assert result.quote_eur is not None
        # 800 € majorés de 14,4 % de frais.
        assert result.acquisition_cost_eur == pytest.approx(800 * 1.144)
        assert result.margin_at_start_eur == pytest.approx(
            result.quote_eur - result.acquisition_cost_eur - result.repairs_eur
        )

    def test_a_cheap_lot_against_a_high_quote_scores_well(self, engine: ScoringEngine) -> None:
        score = engine.score(candidate()).score
        assert score is not None and score > 0.8

    def test_a_lot_priced_above_its_quote_scores_negatively(self, engine: ScoringEngine) -> None:
        score = engine.score(candidate(starting_price=40000.0)).score
        assert score is not None and score < 0

    def test_a_lot_without_a_quote_has_no_score(self, engine: ScoringEngine) -> None:
        result = engine.score(candidate(make="FERRARI", model="F40"))
        assert result.quote_eur is None
        assert result.score is None


class TestCoefficients:
    def test_trade_only_lifts_the_score(self, engine: ScoringEngine) -> None:
        with_it = engine.score(candidate(trade_only=True)).score
        without = engine.score(candidate(trade_only=False)).score
        assert with_it is not None and without is not None
        assert with_it > without

    def test_structural_damage_weighs_the_score_down(self, engine: ScoringEngine) -> None:
        sound = engine.score(candidate(body_damage="cosmetique")).score
        broken = engine.score(candidate(body_damage="structurel")).score
        assert sound is not None and broken is not None
        assert broken < sound

    def test_low_yearly_mileage_lifts_the_score(self, engine: ScoringEngine) -> None:
        low = engine.score(candidate(mileage_per_year=5000)).score
        high = engine.score(candidate(mileage_per_year=30000)).score
        assert low is not None and high is not None
        assert low > high

    def test_an_out_of_scope_lot_scores_exactly_zero(self, engine: ScoringEngine) -> None:
        assert engine.score(candidate(scope="hors")).score == 0.0

    def test_an_unknown_scope_is_neutral(self, engine: ScoringEngine) -> None:
        unknown = engine.score(candidate(scope="inconnu")).score
        inside = engine.score(candidate(scope="dans")).score
        assert unknown == inside

    def test_an_inactive_segment_leaves_the_ranking_without_being_dropped(
        self, engine: ScoringEngine
    ) -> None:
        heavy = engine.score(candidate(segment="pl"))
        assert heavy.score == 0.0
        assert any(rule.regle == "segment_inactif" for rule in heavy.explanation)


class TestRepairAllowances:
    def test_a_dead_engine_is_costed_and_crushes_the_score(self, engine: ScoringEngine) -> None:
        result = engine.score(candidate(description="moteur HS, à revoir"))
        baseline = engine.score(candidate()).score
        assert result.repairs_eur == 3500
        assert result.score is not None and baseline is not None
        assert result.score < baseline

    def test_the_leased_traction_battery_crushes_the_score(self, engine: ScoringEngine) -> None:
        """Le piège de la Zoé : coût zéro, mais rédhibitoire."""
        result = engine.score(
            candidate(
                description=(
                    "La batterie reste la propriété de Renault et est soumise à un "
                    "contrat de location obligatoire avec DIAC Location."
                )
            )
        )
        baseline = engine.score(candidate()).score
        assert result.repairs_eur == 0
        assert result.score is not None and baseline is not None
        # Le score est en euros : ce qui compte est l'effondrement relatif au
        # même lot sans le piège, pas un seuil absolu qui dépendrait de la cote.
        assert result.score < baseline * 0.4

    def test_repairs_are_capped_at_a_share_of_the_quote(self, engine: ScoringEngine) -> None:
        ruined = engine.score(
            candidate(
                mileage=250000,
                description=(
                    "moteur HS, corrosion châssis, boîte de vitesses HS, turbo HS, "
                    "injecteurs HS, kit de distribution, 4 pneus"
                ),
            )
        )
        assert ruined.quote_eur is not None
        assert ruined.repairs_eur <= ruined.quote_eur * 0.6
        assert ruined.beyond_economic_repair is True


class TestExplanation:
    def test_every_rule_that_fired_is_named_with_its_evidence(self, engine: ScoringEngine) -> None:
        result = engine.score(candidate(description="moteur HS. Vétusté générale."))
        codes = {rule.regle for rule in result.explanation}
        assert "reserve_aux_professionnels" in codes
        assert "moteur_hs" in codes
        engine_rule = next(r for r in result.explanation if r.regle == "moteur_hs")
        assert engine_rule.cout_eur == 3500
        assert "moteur HS" in engine_rule.extrait_declencheur

    def test_a_coefficient_rule_carries_its_coefficient(self, engine: ScoringEngine) -> None:
        rule = next(
            r
            for r in engine.score(candidate()).explanation
            if r.regle == "reserve_aux_professionnels"
        )
        assert rule.coefficient == pytest.approx(1.20)

    def test_the_explanation_is_ordered_by_weight(self, engine: ScoringEngine) -> None:
        """Je dois comprendre en dix secondes pourquoi un lot est troisième."""
        result = engine.score(candidate(description="moteur HS", body_damage="structurel"))
        weights = [r.coefficient for r in result.explanation if r.coefficient is not None]
        assert weights == sorted(weights)


class TestDeterminism:
    def test_two_runs_give_identical_scores(self, engine: ScoringEngine) -> None:
        first = engine.score(candidate())
        second = engine.score(candidate())
        assert first.score == second.score
        assert [r.regle for r in first.explanation] == [r.regle for r in second.explanation]


class TestProhibitiveFaults:
    """La seconde porte du classement ne doit pas laisser entrer les pièges."""

    def test_a_prohibitive_allowance_is_reported_on_the_result(self, engine: ScoringEngine) -> None:
        result = engine.score(candidate(description="moteur HS"))
        assert result.prohibitive_fault is True

    def test_a_sound_lot_carries_no_prohibitive_fault(self, engine: ScoringEngine) -> None:
        assert engine.score(candidate()).prohibitive_fault is False

    def test_it_is_reported_even_without_a_quote(self, engine: ScoringEngine) -> None:
        """Le cas de la Zoé : la table ignore le modèle, le piège demeure."""
        result = engine.score(
            candidate(
                make="RENAULT",
                model="ZOE",
                description=(
                    "La batterie reste la propriété de Renault et est soumise à un "
                    "contrat de location obligatoire avec DIAC Location."
                ),
            )
        )
        assert result.quote_eur is None
        assert result.score is None
        assert result.prohibitive_fault is True


class TestScoreIsInEuros:
    """Le score compte des euros, plus une part de la cote.

    Un ratio classait la voiture bon marché en tête : réaliser 80 % d'une cote
    de 3 000 € est facile, 80 % d'une cote de 30 000 € ne l'est pas. Le run du
    25 août plaçait au rang 25 un Kangoo à 2 919 € de marge devant des
    utilitaires bien plus rentables.
    """

    def test_the_score_is_the_margin_times_the_coefficients(self, engine: ScoringEngine) -> None:
        result = engine.score(candidate())
        assert result.margin_at_start_eur is not None and result.score is not None
        coefficient = 1.0
        for rule in result.explanation:
            if rule.coefficient is not None:
                coefficient *= rule.coefficient
        assert result.score == pytest.approx(result.margin_at_start_eur * coefficient)

    def test_a_big_margin_outranks_a_high_percentage(self, engine: ScoringEngine) -> None:
        """Le défaut exact du classement précédent, en un test."""
        settings = ScoringConfig(minimum_margin_eur=0, minimum_margin_ratio=0)
        engine = ScoringEngine(
            quotes=QuoteTable.load(Path("config/cotes.csv")),
            repairs=RepairTable.load(Path("config/reparations.csv")),
            settings=settings,
            active_segments=frozenset({"vl", "vu"}),
        )
        gros = engine.score(candidate(description="Utilitaire."))
        petit = engine.score(
            candidate(
                lot_id="kangoo",
                make="RENAULT",
                model="KANGOO",
                year=2015,
                mileage=150000,
                mileage_per_year=15000,
                description="Utilitaire.",
            )
        )
        assert gros.score is not None and petit.score is not None
        assert gros.margin_at_start_eur is not None and petit.margin_at_start_eur is not None
        assert gros.margin_at_start_eur > petit.margin_at_start_eur
        assert gros.score > petit.score


class TestMarginFloor:
    """Le plancher est une porte, pas un coefficient."""

    def _engine(self, **overrides: float) -> ScoringEngine:
        return ScoringEngine(
            quotes=QuoteTable.load(Path("config/cotes.csv")),
            repairs=RepairTable.load(Path("config/reparations.csv")),
            settings=ScoringConfig(**overrides),
            active_segments=frozenset({"vl", "vu"}),
        )

    def test_a_comfortable_margin_clears_it(self, engine: ScoringEngine) -> None:
        assert engine.score(candidate()).below_margin_floor is False

    def test_a_thin_margin_is_gated(self) -> None:
        """Le Kangoo du rang 25 : 2 919 € de marge, sous les 3 500 € du plancher."""
        engine = self._engine(minimum_margin_eur=3500.0, minimum_margin_ratio=0.20)
        result = engine.score(candidate(starting_price=19000.0))
        assert result.below_margin_floor is True

    def test_the_gate_says_why_and_by_how_much(self) -> None:
        engine = self._engine(minimum_margin_eur=3500.0, minimum_margin_ratio=0.20)
        result = engine.score(candidate(starting_price=19000.0))
        motif = next(r for r in result.explanation if r.regle == "marge_sous_le_plancher")
        assert motif.cout_eur is not None and motif.cout_eur > 0
        assert "plancher" in motif.extrait_declencheur

    def test_the_higher_of_the_two_terms_wins(self) -> None:
        """Sur une cote élevée, c'est la part qui mord, pas la somme fixe."""
        souple = self._engine(minimum_margin_eur=3500.0, minimum_margin_ratio=0.0)
        stricte = self._engine(minimum_margin_eur=3500.0, minimum_margin_ratio=0.40)
        # Cote 21 932 € : 40 % font 8 773 €, bien au-dessus des 3 500 € fixes.
        lot = candidate(starting_price=12000.0)
        assert souple.score(lot).below_margin_floor is False
        assert stricte.score(lot).below_margin_floor is True

    def test_a_gated_lot_keeps_its_figures(self) -> None:
        """Il quitte le classement, il ne disparaît pas : le motif est lisible."""
        engine = self._engine(minimum_margin_eur=3500.0, minimum_margin_ratio=0.20)
        result = engine.score(candidate(starting_price=19000.0))
        assert result.quote_eur is not None
        assert result.margin_at_start_eur is not None
        assert result.score is not None


class TestGearboxCost:
    """Un forfait unique mentait dans les deux sens."""

    BOITE_HS = "Boîte de vitesses HS, véhicule non roulant."

    def _cost(self, engine: ScoringEngine, gearbox: str) -> float:
        result = engine.score(candidate(description=self.BOITE_HS, gearbox=gearbox))
        return next(r for r in result.explanation if r.regle == "boite_hs").cout_eur or 0.0

    def test_a_manual_costs_less(self, engine: ScoringEngine) -> None:
        assert self._cost(engine, "Boîte manuelle") == 3000.0

    def test_a_modern_automatic_costs_more(self, engine: ScoringEngine) -> None:
        """EAT8, Aisin : quatre à sept mille euros posée."""
        assert self._cost(engine, "Boîte automatique") == 5500.0

    def test_an_unreadable_gearbox_keeps_the_table_figure(self, engine: ScoringEngine) -> None:
        """Trente et une fiches sur trois cent quarante-huit ne le disent pas."""
        assert self._cost(engine, "") == 5000.0

    def test_the_wording_is_matched_loosely(self, engine: ScoringEngine) -> None:
        """« BVA », « automatique », accents ou non : la fiche n'est pas normée."""
        assert self._cost(engine, "boite automatique 8 rapports") == 5500.0

    def test_other_allowances_are_untouched(self, engine: ScoringEngine) -> None:
        result = engine.score(
            candidate(description="pare-brise fissuré", gearbox="Boîte automatique")
        )
        pare_brise = next(r for r in result.explanation if r.regle == "pare_brise")
        assert pare_brise.cout_eur == 400


class TestUnknownConditionIsDegressive:
    """L'inconnu coûte ce que vous avez mis sur la table."""

    INCONNU = "Etat mécanique non connu. Vendu en l'état."

    def _coefficient(self, engine: ScoringEngine, price: float | None) -> float:
        result = engine.score(candidate(description=self.INCONNU, starting_price=price))
        rule = next(r for r in result.explanation if r.regle == "etat_meca_inconnu")
        assert rule.coefficient is not None
        return rule.coefficient

    def test_the_unknown_is_cheap_on_a_wreck(self, engine: ScoringEngine) -> None:
        assert self._coefficient(engine, 300.0) == pytest.approx(0.95)

    def test_it_is_expensive_on_a_people_carrier(self, engine: ScoringEngine) -> None:
        """Le SEAT Alhambra du rang 25 : mise à prix 4 000 €."""
        assert self._coefficient(engine, 4000.0) == pytest.approx(0.60)

    def test_it_slides_between_the_two(self, engine: ScoringEngine) -> None:
        milieu = self._coefficient(engine, 2150.0)
        assert 0.60 < milieu < 0.95
        assert milieu == pytest.approx(0.775, abs=0.01)

    def test_it_stays_flat_beyond_the_bounds(self, engine: ScoringEngine) -> None:
        assert self._coefficient(engine, 50.0) == pytest.approx(0.95)
        assert self._coefficient(engine, 20000.0) == pytest.approx(0.60)

    def test_an_unreadable_price_falls_back_on_the_flat_severity(
        self, engine: ScoringEngine
    ) -> None:
        """Sans mise à prix, la dégressivité n'a rien sur quoi s'appuyer."""
        assert self._coefficient(engine, None) == pytest.approx(0.85)

    def test_the_dearer_lot_is_punished_harder(self, engine: ScoringEngine) -> None:
        cher = engine.score(candidate(description=self.INCONNU, starting_price=4000.0))
        modeste = engine.score(candidate(description=self.INCONNU, starting_price=300.0))
        assert cher.score is not None and modeste.score is not None
        assert cher.margin_at_start_eur is not None and modeste.margin_at_start_eur is not None
        # Le lot cher a une marge plus faible ET un coefficient plus dur : les
        # deux effets vont dans le même sens, ce qui est le but.
        assert cher.score < modeste.score
