"""Geographic scope, based on the lot's COLLECTION point.

The seat of the sale carries no operational meaning: a sale run by the
Saint-Maurice directorate may have its lots collected anywhere in France.
Only `dropoff_location` counts.

A lot outside the scope is never dropped: it is flagged. Deciding whether to
make the drive belongs to the operator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

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


@dataclass(frozen=True, slots=True)
class Perimeter:
    """Allow-list of French departments and neighbouring countries."""

    departments: frozenset[str]
    foreign_countries: frozenset[str] = frozenset()

    def contains(self, postcode: str | None, location: str | None) -> bool:
        """Whether the collection point falls inside the buying scope."""
        department = department_from_postcode(postcode)
        if department is not None:
            return department in self.departments
        country = country_from_location(location)
        return country is not None and country in self.foreign_countries
