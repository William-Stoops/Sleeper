"""Geographic scope, based on the lot's COLLECTION point.

The seat of the sale carries no operational meaning: a sale run by the
Saint-Maurice directorate may have its lots collected anywhere in France.
Only `dropoff_location` counts.

A lot outside the scope is never dropped: it is flagged. Deciding whether to
make the drive belongs to the operator.

**A missing place is not an out-of-scope place.** The status therefore has
three values, not two. Sale 567 — "spéciale véhicule d'exception" — vanished
from a whole scan because an empty text field collapsed a boolean to false.
That is precisely the silent degradation this project forbids: an unreadable
location yields "inconnu", which is always collected and always surfaced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

from sleeper.domain.text import normalize

_DIGITS = re.compile(r"\d+")

#: Actual split point for Corsica: Corse-du-Sud below 20200, Haute-Corse above.
_CORSICA_SPLIT: Final = 20200
_FR_POSTCODE_LENGTH: Final = 5

#: Overseas collectivities whose department code needs three digits.
_THREE_DIGIT_PREFIXES: Final = frozenset({"97", "98"})

#: Wordings by which a foreign collection point announces itself in listings.
#: The source carries no country field: the country only ever appears spelled
#: out inside the location label.
_COUNTRY_MARKERS: Final = {
    "BE": ("belgique", "belgium", "bruxelles", "anvers", "liege", "mons", "charleroi"),
    "LU": ("luxembourg", "grand duche"),
    "DE": ("allemagne", "germany"),
    "ES": ("espagne", "spain", "madrid"),
    "IT": ("italie", "italy"),
    "NL": ("pays bas", "netherlands", "amsterdam"),
    "CH": ("suisse", "switzerland"),
}


def department_from_postcode(postcode: str | None) -> str | None:
    """Derive the department code from a French postcode.

    Returns `None` when the code is not a usable French postcode — which
    includes four-digit foreign codes, handled elsewhere.
    """
    if not postcode:
        return None
    digits = "".join(_DIGITS.findall(postcode))
    if len(digits) != _FR_POSTCODE_LENGTH:
        return None
    if digits[:2] in _THREE_DIGIT_PREFIXES:
        return digits[:3]
    if digits.startswith("20"):
        return "2A" if int(digits) < _CORSICA_SPLIT else "2B"
    return digits[:2]


def country_from_location(location: str | None) -> str | None:
    """Guess the country from the collection-point label.

    An acknowledged heuristic: the source publishes no country code. It is
    used only to catch foreign lots, never to reject a French one.
    """
    flattened = normalize(location)
    if not flattened:
        return None
    for code, markers in _COUNTRY_MARKERS.items():
        if any(re.search(rf"\b{re.escape(m)}\b", flattened) for m in markers):
            return code
    return None


#: Where a lot stands relative to the buying scope. Three values, never two:
#: "inconnu" must never be confused with "hors".
ScopeStatus = Literal["dans", "hors", "inconnu"]


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    """A lot's scope once the fallback to its sale has been applied."""

    status: ScopeStatus
    postcode: str
    location: str
    #: True when the place comes from the sale because the lot had none.
    inherited: bool


@dataclass(frozen=True, slots=True)
class Perimeter:
    """Allow-list of French departments and neighbouring countries."""

    departments: frozenset[str]
    foreign_countries: frozenset[str] = frozenset()

    def status(self, postcode: str | None, location: str | None) -> ScopeStatus:
        """Where a collection point stands: inside, outside, or unreadable.

        An unreadable place is "inconnu", never "hors": we do not turn a
        missing field into a decision.
        """
        department = department_from_postcode(postcode)
        if department is not None:
            return "dans" if department in self.departments else "hors"
        country = country_from_location(location)
        if country is None:
            return "inconnu"
        return "dans" if country in self.foreign_countries else "hors"

    def resolve(
        self,
        postcode: str | None,
        location: str | None,
        sale_postcode: str | None,
        sale_location: str | None,
    ) -> ResolvedScope:
        """Resolve a lot's scope, falling back to its sale's place.

        The fallback only fires when the lot itself says nothing. A lot with a
        readable place keeps it, even when that puts it outside a sale that is
        inside — the real case of the Limoges lots in the Clermont-Ferrand
        sale 517.
        """
        own = self.status(postcode, location)
        if own != "inconnu":
            return ResolvedScope(own, postcode or "", location or "", inherited=False)

        inherited = self.status(sale_postcode, sale_location)
        if inherited == "inconnu":
            return ResolvedScope("inconnu", postcode or "", location or "", inherited=False)
        return ResolvedScope(inherited, sale_postcode or "", sale_location or "", inherited=True)
