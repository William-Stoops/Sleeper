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
        assert result.margin_eur == pytest.approx(
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
        assert result.repairs_eur == 0
        assert result.score is not None
        assert result.score < 0.4

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
