"""The scoring engine.

**This is a sort, not a valuation.** It is coarse, fast, entirely
deterministic, explainable line by line, and above all conservative: better to
surface a mediocre lot than to bury a good one. It decides no purchase — only
who gets the expensive analysis.

Downstream, a proper appraisal of one lot costs five to ten minutes: finding
five real comparables, knowing the weak points of that exact engine, costing
the refurbishment, computing the bid ceiling. Twenty to thirty lots a day is
the realistic throughput. The collector produced 338. It eliminates what is
forbidden; it ranks nothing. This does the ranking.

Every rule that moves a score is recorded with the fragment of text that
fired it. A rank nobody can explain is a rank nobody can trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from sleeper.config import ScoringConfig
from sleeper.domain.damage import BodyDamage
from sleeper.domain.segment import Segment
from sleeper.domain.territory import ScopeStatus
from sleeper.scoring.tables import QuoteTable, RepairTable, Severity


class ScoreRule(BaseModel):
    """One rule that moved a lot's score, and the evidence that fired it."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    regle: str
    coefficient: float | None = None
    cout_eur: float | None = None
    extrait_declencheur: str = ""


@dataclass(frozen=True, slots=True)
class ScoreInput:
    """Everything the sort is allowed to look at."""

    lot_id: str
    make: str
    model: str
    fuel: str
    year: int | None
    mileage: int | None
    mileage_per_year: int | None
    starting_price: float | None
    buyer_fee_pct: float | None
    description: str
    trade_only: bool | None
    body_damage: BodyDamage
    scope: ScopeStatus
    segment: Segment
    recent_favourable_inspection: bool


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """A lot's sort result, with the reasoning that produced it."""

    quote_eur: float | None
    acquisition_cost_eur: float
    repairs_eur: float
    margin_eur: float | None
    score: float | None
    beyond_economic_repair: bool
    #: A prohibitive allowance fired — a leased traction battery, a dead
    #: engine, chassis corrosion. No price rescues those.
    prohibitive_fault: bool = False
    explanation: list[ScoreRule] = field(default_factory=list)


#: Coefficient applied per repair severity. `moyen` and `leger` weigh nothing
#: on the score: their cost already speaks through the margin.
_SEVERITY_FIELDS: dict[Severity, str] = {
    "redhibitoire": "severity_prohibitive",
    "lourd": "severity_heavy",
    "signal": "severity_signal",
}


class ScoringEngine:
    """Turns a lot into a rank, and says why."""

    def __init__(
        self,
        quotes: QuoteTable,
        repairs: RepairTable,
        settings: ScoringConfig,
        active_segments: frozenset[str],
    ) -> None:
        self._quotes = quotes
        self._repairs = repairs
        self._settings = settings
        self._active_segments = active_segments

    def score(self, lot: ScoreInput) -> ScoreResult:
        """Score one lot, recording every rule that moved it."""
        rules: list[ScoreRule] = []
        quote = self._quotes.quote(
            make=lot.make, model=lot.model, fuel=lot.fuel, year=lot.year, mileage=lot.mileage
        )
        fee_pct = lot.buyer_fee_pct or 0.0
        acquisition = (lot.starting_price or 0.0) * (1 + fee_pct / 100)

        repairs, beyond_repair, severities = self._repair_budget(lot, quote, rules)
        prohibitive = "redhibitoire" in severities
        if quote is None:
            # No quote, no ranking — but the lot is not lost: it goes into the
            # separate queue that catches the mis-catalogued cheap find.
            return ScoreResult(
                quote_eur=None,
                acquisition_cost_eur=acquisition,
                repairs_eur=repairs,
                margin_eur=None,
                score=None,
                beyond_economic_repair=beyond_repair,
                prohibitive_fault=prohibitive,
                explanation=rules,
            )

        margin = quote - acquisition - repairs
        base = margin / quote
        coefficient = self._coefficients(lot, beyond_repair, severities, rules)
        rules.sort(key=lambda r: (r.coefficient is None, r.coefficient or 0.0, r.regle))
        return ScoreResult(
            quote_eur=quote,
            acquisition_cost_eur=acquisition,
            repairs_eur=repairs,
            margin_eur=margin,
            score=base * coefficient,
            beyond_economic_repair=beyond_repair,
            prohibitive_fault=prohibitive,
            explanation=rules,
        )

    def _repair_budget(
        self, lot: ScoreInput, quote: float | None, rules: list[ScoreRule]
    ) -> tuple[float, bool, set[Severity]]:
        """Sum of the allowances the description triggers, capped on the quote."""
        matches = self._repairs.match(lot.description)
        for match in matches:
            rules.append(
                ScoreRule(
                    regle=match.code,
                    cout_eur=match.cost_eur,
                    coefficient=self._severity_coefficient(match.severity),
                    extrait_declencheur=match.evidence,
                )
            )
        severities = {m.severity for m in matches}
        total = sum(m.cost_eur for m in matches)
        if quote is None:
            return total, False, severities
        cap = quote * self._settings.repairs_cap_ratio
        if total > cap:
            return cap, True, severities
        return total, False, severities

    def _severity_coefficient(self, severity: Severity) -> float | None:
        """Coefficient a severity carries, when it carries one."""
        name = _SEVERITY_FIELDS.get(severity)
        return None if name is None else float(getattr(self._settings, name))

    def _coefficients(
        self,
        lot: ScoreInput,
        beyond_repair: bool,
        severities: set[Severity],
        rules: list[ScoreRule],
    ) -> float:
        """Product of every coefficient that applies, each one recorded."""
        settings = self._settings
        product = 1.0

        def apply(name: str, value: float, evidence: str = "") -> None:
            nonlocal product
            product *= value
            rules.append(ScoreRule(regle=name, coefficient=value, extrait_declencheur=evidence))

        if lot.trade_only:
            apply("reserve_aux_professionnels", settings.trade_only)
        if lot.recent_favourable_inspection:
            apply("ct_favorable_recent", settings.recent_favourable_inspection)
        if (
            lot.mileage_per_year is not None
            and lot.mileage_per_year < settings.low_yearly_mileage_threshold
        ):
            apply(
                "faible_km_par_an",
                settings.low_yearly_mileage,
                f"{lot.mileage_per_year} km/an",
            )
        if lot.body_damage == "structurel":
            apply("dommages_structurels", settings.structural_damage)
        if beyond_repair:
            apply("non_reparable_economiquement", settings.beyond_economic_repair)
        if lot.scope == "hors":
            apply("perimetre_hors", settings.out_of_scope)
        elif lot.scope == "inconnu":
            apply("perimetre_inconnu", settings.unknown_scope)
        if lot.segment not in self._active_segments:
            apply(
                "segment_inactif",
                settings.inactive_segment,
                f"segment « {lot.segment} » hors des segments travaillés",
            )

        # A severity weighs once, however many allowances of that severity
        # fired: three light faults must not compound into a verdict.
        for severity, name in _SEVERITY_FIELDS.items():
            if severity in severities:
                product *= float(getattr(settings, name))
        return product
