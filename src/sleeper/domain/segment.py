"""Vehicle segment, and the registrable-vehicle predicate.

Five machines — a Broyeur DURATECH, a Cribleur Ménart, a Chargeur
télescopique — came out of the run of 2026-08-25 rejected for `sans_cle`.
They are not vehicles without a key; they are machines that should never have
reached a condition filter. The category test asked "does the listing carry a
make?", and a Broyeur carries one.

The test asked here is **"is this a registrable road vehicle?"** — a J.1
code, a plate, or a serial number. That predicate keeps the IVECO road
tractor, which is a real vehicle, and drops the machines.

Segment is then a **commercial** distinction, not a filter: which segments a
dealer works is a line of configuration. A heavy truck stays in the output
with its segment stated; it simply does not compete for the expensive
analysis.
"""

from __future__ import annotations

import re
from typing import Final, Literal

from sleeper.domain.text import normalize

#: What kind of vehicle this is, commercially.
Segment = Literal["vl", "vu", "pl", "engin"]

#: J.1 codes, grouped by segment. Read on the leading token: the attribute
#: carries compound values such as "VASP - DERIV_VP".
_KINDS: Final[dict[str, Segment]] = {
    "VP": "vl",
    "CTTE": "vu",
    "VASP": "vu",
    "CAM": "pl",
    "TRR": "pl",
    "TCP": "pl",
    "REM": "pl",
    "RESP": "pl",
    "SREM": "pl",
}

#: A French plate, current or pre-2009 format.
_PLATE: Final = re.compile(
    r"\b[A-Z]{2}[- ]?\d{3}[- ]?[A-Z]{2}\b"  # AB-123-CD
    r"|\b\d{1,4}[- ]?[A-Z]{2,3}[- ]?\d{2,3}\b"  # 1234 AB 56
)

#: Fallback on the title when no J.1 code is published — 71 lots of the real
#: run are in that case. Ordered: the first family that matches decides.
_TITLE_SEGMENTS: Final[tuple[tuple[Segment, re.Pattern[str]], ...]] = (
    (
        "pl",
        re.compile(
            r"\b(?:autocar|autobus|bus|camion|benne|tracteur routier|semi remorque"
            r"|remorque|porteur|poids lourd|citerne|grue)\b"
        ),
    ),
    (
        "vu",
        re.compile(
            r"\b(?:utilitaire|fourgon|fourgonnette|ambulance|vsl|corbillard|plateau"
            r"|frigorifique)\b"
        ),
    ),
)


def is_registrable(kind: str, plate: str, vin: str) -> bool:
    """Whether the listing shows this is a road-registrable vehicle.

    Any one of the three is enough: a J.1 code, a plate, or a serial number.
    A machine has none of them; a road tractor has at least one.
    """
    return bool(_j1_code(kind) or _PLATE.search((plate or "").upper()) or (vin or "").strip())


def classify_segment(kind: str, plate: str, vin: str, title: str) -> Segment:
    """Place a lot in a commercial segment.

    Anything that is not registrable is an `engin`. Among vehicles, the J.1
    code decides; failing that, the wording of the title; failing that, `vl`,
    which is the most common case and the least costly default — a light car
    wrongly kept costs an analysis, a heavy truck wrongly dropped costs a lot.
    """
    if not is_registrable(kind, plate, vin):
        return "engin"
    if (code := _j1_code(kind)) and code in _KINDS:
        return _KINDS[code]
    flattened = normalize(title)
    for segment, pattern in _TITLE_SEGMENTS:
        if pattern.search(flattened):
            return segment
    return "vl"


def _j1_code(kind: str) -> str:
    """Leading token of the `kind` attribute, which is the J.1 code itself."""
    cleaned = (kind or "").strip().upper()
    if not cleaned:
        return ""
    return cleaned.split()[0].split("-")[0].strip()
