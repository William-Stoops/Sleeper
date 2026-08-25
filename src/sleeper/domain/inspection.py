"""Roadworthiness test ("contrôle technique") parsing.

The v1 field mixed three kinds of value in one string — "absent", "présent",
and an ISO date — and "absent" was ambiguous: was there no test, or did the
listing simply not mention one? On this seam that difference decides the
resale, so it gets its own type.

Four states are distinguished, and the two that matter most are the ones a
boolean cannot express: *not mentioned* and *mentioned but undated*.

**The expiry trap.** "CT favorable du 10/07/2026 (périmé)" is a favourable
test that is no longer valid. The verdict and the validity are two different
questions, and a mention of expiry settles the second one whatever the first
says.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from sleeper.domain.text import normalize

#: Verdict of the test, in the official wording of the report.
InspectionResult = Literal[
    "favorable",
    "favorable_defaillances_mineures",
    "defavorable_contre_visite",
    "inconnu",
]

#: A passenger-car test is valid for two years.
_VALIDITY = dt.timedelta(days=730)

_DATE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")

#: The test is mentioned at all — with or without a date or a verdict.
_MENTIONED: Final = re.compile(r"\b(?:ct|controle technique|contre visite)\b")

#: Wordings that settle the validity regardless of the verdict.
_EXPIRED: Final = re.compile(r"\b(?:perime|perimee|non valide|plus valide|expire|expiree)\b")

#: Ordered from most specific to least: the first match decides the verdict.
_VERDICTS: Final[tuple[tuple[InspectionResult, re.Pattern[str]], ...]] = (
    (
        "defavorable_contre_visite",
        re.compile(r"\bdefavorable\b|\bcontre visite\b|\bdefaillances? majeures?\b"),
    ),
    ("favorable_defaillances_mineures", re.compile(r"\bfavorable\b[^.]{0,60}\bmineures?\b")),
    ("favorable", re.compile(r"\bfavorable\b")),
)


class Inspection(BaseModel):
    """What a listing says about the vehicle's roadworthiness test."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    #: The listing says something about a test — even just that there is none.
    mentionne: bool = False
    # The field is named `date` because the contract is: it therefore shadows
    # the type inside this class body, hence the aliased datetime import.
    date: dt.date | None = None
    resultat: InspectionResult = "inconnu"
    #: `None` when the date is unknown: we do not guess a validity.
    valide_a_la_date_du_run: bool | None = Field(default=None)


def _first_date(description: str) -> dt.date | None:
    """First date written in the description, read as day/month/year."""
    found = _DATE.search(description)
    if not found:
        return None
    day, month, year = (int(g) for g in found.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def read_inspection(
    description: str | None, structured: bool | None, run_day: dt.date
) -> Inspection:
    """Read the roadworthiness test from a listing.

    `structured` is the source's own boolean attribute: `True` when the
    listing declares a test, `False` when it declares none, `None` when it
    says nothing at all.
    """
    flattened = normalize(description)
    mentioned = structured is not None or bool(_MENTIONED.search(flattened))
    if not mentioned:
        return Inspection()

    tested_on = _first_date(description or "")
    verdict: InspectionResult = "inconnu"
    for result, pattern in _VERDICTS:
        if pattern.search(flattened):
            verdict = result
            break

    if _EXPIRED.search(flattened):
        valid: bool | None = False
    elif tested_on is None:
        valid = None
    else:
        valid = run_day - tested_on <= _VALIDITY

    return Inspection(
        mentionne=True, date=tested_on, resultat=verdict, valide_a_la_date_du_run=valid
    )
