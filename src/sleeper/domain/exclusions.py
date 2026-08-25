"""Business exclusion rules.

Two sources of truth, in this order:

1. the listing's structured attributes (`vehicle_has_a_key`, `vhu_declared`…),
   which are reliable;
2. the free-text description, which is not — it is typed by hand by staff of
   different regional directorates, and carries typos recorded in production
   ("porfessionnels").

Each rule therefore holds triggering phrases AND counter-phrases that cancel
it. That choice is deliberately explicit rather than heuristic: "sans choc
apparent" must not reject a sound lot, and the list has to stay readable,
testable and extensible without guessing what a parser is up to.

Rule codes stay in French: they are part of the output contract
(`ecartes[].motif`) and of the configuration the operator edits daily.
Recognised wordings are documented in docs/regles-metier.md.

**There is deliberately no rule about knocks.** On this seam, nearly every
description mentions one — "coups, chocs, rayures et frottements d'usage" is
boilerplate — and excluding on it threw away the best file of the run of
2026-08-25. Body damage is graded in `domain/damage.py`, where it feeds the
repair budget and the score without ever excluding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from sleeper.domain import text
from sleeper.domain.codes import OUT_OF_SCOPE_KINDS

#: Model year below which a vehicle is a collector's item, not stock in trade.
CLASSIC_CAR_YEAR: Final = 1990


@dataclass(frozen=True, slots=True)
class LotSignals:
    """Everything a rule is allowed to look at in order to decide.

    Deliberately poor: a rule sees neither prices, nor scope, nor the state of
    the sale. It judges the goods and nothing else.
    """

    description: str
    mileage: int | None
    has_key: bool | None
    registration_certificate: bool | None
    kind: str | None
    first_registration_year: int | None
    declared_end_of_life: bool | None
    re_registrable: bool | None
    non_compliant: bool | None
    #: `True` when the listing carries at least one vehicle attribute (kind,
    #: make, model). `None` when the listing could not be read: no conclusion.
    has_vehicle_attributes: bool | None = None


@dataclass(frozen=True, slots=True)
class Rule:
    """A named exclusion rule: testable and extensible."""

    code: str
    label: str
    phrases: tuple[str, ...] = ()
    counter_phrases: tuple[str, ...] = ()

    def matches(self, signals: LotSignals) -> bool:
        """Apply the rule. The structured verdict comes before the text."""
        if self._structured_verdict(signals) is True:
            return True
        if any(text.contains(signals.description, c) for c in self.counter_phrases):
            return False
        return any(text.contains(signals.description, p) for p in self.phrases)

    def _structured_verdict(self, signals: LotSignals) -> bool | None:
        """Verdict from the reliable attributes. `None` = the rule has none."""
        return _STRUCTURED_VERDICTS.get(self.code, _no_verdict)(signals)


def _no_verdict(_: LotSignals) -> bool | None:
    return None


def _not_a_vehicle(signals: LotSignals) -> bool | None:
    """A "Véhicules" sale also sells furniture, consumer electronics, jewellery.

    Those lots carry no vehicle attribute. Rejecting them here gives them an
    accurate reason instead of letting them fall on "kilométrage inconnu",
    which would be true but misleading.
    """
    if signals.has_vehicle_attributes is None:
        return None
    return not signals.has_vehicle_attributes


def _mileage_missing(signals: LotSignals) -> bool | None:
    """A zero odometer is not a mileage: it is an unfilled field."""
    if signals.mileage:
        return False
    return None if text.extract_mileage(signals.description) else True


def _no_key(signals: LotSignals) -> bool | None:
    return None if signals.has_key is None else not signals.has_key


def _no_registration_certificate(signals: LotSignals) -> bool | None:
    if signals.registration_certificate is None:
        return None
    return not signals.registration_certificate


def _not_roadworthy(signals: LotSignals) -> bool | None:
    if signals.re_registrable is False:
        return True
    return None


def _end_of_life(signals: LotSignals) -> bool | None:
    return True if signals.declared_end_of_life else None


def _out_of_scope_kind(signals: LotSignals) -> bool | None:
    """Compare on the J.1 code alone.

    Observed in production: the attribute carries compound values such as
    "VASP - DERIV_VP", and inconsistent case ("vp"). Only the leading token is
    the registration-document code; the rest is a local refinement.
    """
    if not signals.kind:
        return None
    code = signals.kind.strip().upper().split()[0].split("-")[0].strip()
    return True if code in OUT_OF_SCOPE_KINDS else None


def _classic_car(signals: LotSignals) -> bool | None:
    year = signals.first_registration_year
    if year is None:
        return None
    return year < CLASSIC_CAR_YEAR


_STRUCTURED_VERDICTS: Final = {
    "hors_categorie_vehicule": _not_a_vehicle,
    "kilometrage_inconnu": _mileage_missing,
    "sans_cle": _no_key,
    "sans_certificat_immatriculation": _no_registration_certificate,
    "non_roulant": _not_roadworthy,
    "epave_ou_pieces": _end_of_life,
    "genre_hors_cible": _out_of_scope_kind,
    "collection_avant_1990": _classic_car,
}


#: Order matters: it is the order rules are evaluated in, and therefore what
#: makes the verdict reproducible for a lot carrying several defects.
DEFAULT_RULES: Final[tuple[Rule, ...]] = (
    Rule(
        code="hors_categorie_vehicule",
        label="Lot sans attribut véhicule (mobilier, high-tech, bijoux…)",
    ),
    Rule(
        code="genre_hors_cible",
        label="Genre de véhicule hors cible (deux-roues, quadricycle, agricole, remorque)",
        phrases=(
            "moto",
            "motocyclette",
            "scooter",
            "cyclomoteur",
            "quad",
            "quadricycle",
            "remorque",
            "semi remorque",
            "caravane",
            "tracteur agricole",
            "engin agricole",
            "moissonneuse",
            "tondeuse autoportee",
            "sans permis",
            "voiturette",
        ),
        counter_phrases=("porte moto", "remorque non comprise"),
    ),
    Rule(
        code="collection_avant_1990",
        label="Véhicule de collection antérieur à 1990",
        phrases=("vehicule de collection", "carte grise de collection"),
    ),
    Rule(
        code="sans_cle",
        label="Véhicule sans clé",
        phrases=(
            "sans cle",
            "sans cles",
            "sans clef",
            "sans clefs",
            "cle absente",
            "cles absentes",
            "clef absente",
            "absence de cle",
            "absence de cles",
            "absence de clef",
            "pas de cle",
            "pas de cles",
            "pas de clef",
            "aucune cle",
            "cle manquante",
            "cles manquantes",
        ),
        counter_phrases=("avec cle", "avec cles", "avec clef", "presence de cle"),
    ),
    Rule(
        code="sans_certificat_immatriculation",
        label="Absence de certificat d'immatriculation",
        phrases=(
            "sans carte grise",
            "sans cg",
            "cg absente",
            "carte grise absente",
            "absence de carte grise",
            "absence de certificat d immatriculation",
            "sans certificat d immatriculation",
            "pas de carte grise",
            "pas de cg",
            "carte grise manquante",
            "cg non fournie",
            "carte grise non fournie",
            "vehicule non immatricule",
        ),
        counter_phrases=("avec cg", "avec carte grise", "carte grise fournie"),
    ),
    Rule(
        code="epave_ou_pieces",
        label="Épave ou vente pour pièces",
        phrases=(
            "epave",
            "pour pieces",
            "pieces detachees",
            "vehicule hors d usage",
            "vhu",
            "destruction obligatoire",
            "a detruire",
            "cession pour destruction",
        ),
        counter_phrases=("pieces jointes", "pieces du dossier"),
    ),
    Rule(
        code="non_roulant",
        label="Véhicule non roulant",
        phrases=(
            "non roulant",
            "ne roule pas",
            "ne demarre pas",
            "vehicule immobilise",
            "etat non roulant",
            "hors etat de rouler",
            "ne circule plus",
        ),
        # A counter-phrase must never be a fragment of its own trigger:
        # "roulant" alone would cancel "non roulant".
        counter_phrases=(
            "vehicule roulant",
            "en etat de rouler",
            "demarre correctement",
            "demarre et roule",
        ),
    ),
    Rule(
        code="moteur_hors_service",
        label="Moteur hors service",
        phrases=(
            "moteur hors service",
            "moteur hs",
            "moteur casse",
            "moteur a refaire",
            "moteur serre",
            "moteur bloque",
            "joint de culasse hs",
            "boite hs",
        ),
        counter_phrases=("moteur en bon etat", "moteur revise"),
    ),
    Rule(
        code="gage_ou_opposition",
        label="Gage ou opposition",
        phrases=(
            "gage",
            "gagee",
            "vehicule gage",
            "opposition",
            "saisie conservatoire",
            "situation administrative bloquee",
        ),
        counter_phrases=("sans gage", "non gage", "aucune opposition", "sans opposition"),
    ),
    Rule(
        code="kilometrage_inconnu",
        label="Kilométrage inconnu, non renseigné ou absent",
        phrases=(
            "kilometrage inconnu",
            "kilometrage non renseigne",
            "km inconnu",
            "compteur non fonctionnel",
            "compteur hs",
            "compteur bloque",
            "kilometrage non garanti",
            "compteur non fiable",
        ),
    ),
)


class ExclusionEngine:
    """Apply rules in order and return the first reason that fires."""

    def __init__(self, rules: Sequence[Rule]) -> None:
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[Rule, ...]:
        return self._rules

    def reason(self, signals: LotSignals) -> str | None:
        """Code of the exclusion reason, or `None` when the lot is kept."""
        for rule in self._rules:
            if rule.matches(signals):
                return rule.code
        return None

    def label(self, code: str) -> str:
        """Human-readable label of a reason, for reporting."""
        for rule in self._rules:
            if rule.code == code:
                return rule.label
        raise KeyError(code)

    @classmethod
    def with_extra_phrases(
        cls, rules: Sequence[Rule], extras: Mapping[str, Iterable[str]]
    ) -> ExclusionEngine:
        """Enrich the rules with wordings met in production.

        An unknown key is an error: a typo in the configuration must not turn
        into a silently inert rule.
        """
        known = {r.code for r in rules}
        if unknown := set(extras) - known:
            raise KeyError(f"règle(s) d'exclusion inconnue(s) : {', '.join(sorted(unknown))}")
        enriched = [replace(r, phrases=r.phrases + tuple(extras.get(r.code, ()))) for r in rules]
        return cls(enriched)
