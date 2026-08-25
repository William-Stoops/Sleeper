"""Normalisation and extraction over the free text of Domaine listings.

Descriptions are typed by hand by staff of the regional directorates. They
vary in case, accents and punctuation, and contain typos ("porfessionnels"
was recorded verbatim in production). No business rule may therefore work on
the raw string: everything goes through `normalize` first.
"""

from __future__ import annotations

import html as html_module
import re
import unicodedata
from typing import Final

_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: A standard VIN is 17 characters, without I, O or Q. Older listings publish
#: shorter ones, so 11 to 17 is accepted: strict validation is not our job,
#: and losing the value would be worse.
_VIN = re.compile(
    r"(?:n\W{0,3}\s*(?:de\s+)?s[ée]rie|vin|num[ée]ro\s+(?:de\s+)?s[ée]rie)"
    r"\s*:?\s*([A-HJ-NPR-Z0-9]{11,17})\b",
    re.IGNORECASE,
)
_TAX_HORSEPOWER = re.compile(r"\b(\d{1,3})\s*(?:cv|c\.v\.|chevaux\s+fiscaux)\b", re.IGNORECASE)
_MILEAGE = re.compile(
    r"\b(\d{1,3}(?:[\s.\u00a0]\d{3})+|\d{3,7})\s*(?:km|kms|kilom[eè]tres?)\b", re.IGNORECASE
)
_CRIT_AIR = re.compile(r"crit\W{0,2}air\W{0,3}(\d)", re.IGNORECASE)

#: Viewing slot. Deliberately BOUNDED: the sentence following the date
#: regularly carries a civil servant's name and phone number, which have no
#: business being in a structured field.
_WEEKDAY = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
_DATE = (
    r"(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t"
    r"|septembre|octobre|novembre|d[ée]cembre)(?:\s+\d{4})?)"
)
_TIME = r"\d{1,2}\s*h(?:\s*\d{2})?"
_VIEWING = re.compile(
    rf"(?:visites?|journ[ée]es?\s+de\s+visite)[^.]{{0,80}}?"
    rf"({_WEEKDAY}\s+{_DATE}(?:\s*(?:de|entre)\s*{_TIME}\s*(?:[àa]|et)\s*{_TIME})?)",
    re.IGNORECASE,
)

_INSPECTION_FULL_DATE = re.compile(
    r"(?:ct|contr[oô]le\s+technique)[^.\d]{0,30}(\d{2})[/\-.](\d{2})[/\-.](\d{4})", re.IGNORECASE
)
_INSPECTION_MONTH_YEAR = re.compile(
    r"(?:ct|contr[oô]le\s+technique)[^.\d]{0,30}(\d{2})[/\-.](\d{4})", re.IGNORECASE
)

#: Condition wordings found in Domaine listings. The mention is returned
#: exactly as written: it is raw material for downstream analysis, not a
#: grade awarded by Sleeper.
_CONDITION = re.compile(
    r"((?:tr[eè]s\s+)?(?:bon|mauvais|excellent|moyen)\s+[ée]tat(?:\s+g[ée]n[ée]ral)?"
    r"|[ée]tat\s+d\W?usage"
    r"|r[ée]parations?\s+[àa]\s+pr[ée]voir"
    r"|entretien\s+[àa]\s+pr[ée]voir"
    r"|vendu\s+en\s+l\W?[ée]tat"
    r"|v[ée]hicule\s+vendu\s+en\s+l\W?[ée]tat)",
    re.IGNORECASE,
)

_MAX_MONTH: Final = 12

#: Plafond de plausibilité de la puissance fiscale. Les descriptions annoncent
#: souvent la puissance DIN AVANT la puissance fiscale (« 2.0l DCI 16v 120cv,
#: […] 07cv ») : sans ce plafond, on retient la mauvaise.
_MAX_TAX_HORSEPOWER: Final = 60


def from_html(source: str | None) -> str:
    """Reduce an HTML fragment to its text, entities and nbsp included."""
    if not source:
        return ""
    without_tags = _TAG.sub(" ", source)
    decoded = html_module.unescape(without_tags).replace("\u00a0", " ")
    return _WHITESPACE.sub(" ", decoded).strip()


def normalize(source: str | None) -> str:
    """Fold a string to its canonical form: lowercase, unaccented, unpunctuated.

    This is the only form business rules may work on. The operation is
    idempotent.
    """
    if not source:
        return ""
    decomposed = unicodedata.normalize("NFKD", source)
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", unaccented.lower()).strip()


def contains(source: str | None, phrase: str) -> bool:
    """Test for a phrase, on whole words, over the normalised form.

    Whole words keep "charge" from firing on "chargeur" — a real trap on
    listings that mention batteries and flatbed trucks.
    """
    needle = normalize(phrase)
    if not needle:
        return False
    pattern = r"\b" + r"\s+".join(re.escape(word) for word in needle.split()) + r"\b"
    return re.search(pattern, normalize(source)) is not None


def extract_vin(source: str | None) -> str | None:
    """Pick up the serial number announced in the description."""
    found = _VIN.search(source or "")
    return found.group(1).upper() if found else None


def extract_tax_horsepower(source: str | None) -> int | None:
    """Pick up the fiscal horsepower ("06 cv").

    Descriptions regularly quote the engine's DIN power BEFORE the fiscal one
    ("2.0l DCI 16v 120cv, […] 07cv"). Only a plausible fiscal value is kept:
    the French fiscal rating does not reach three digits.
    """
    for found in _TAX_HORSEPOWER.finditer(source or ""):
        value = int(found.group(1))
        if value <= _MAX_TAX_HORSEPOWER:
            return value
    return None


def extract_mileage(source: str | None) -> int | None:
    """Pick up a mileage, whatever thousands separator was used."""
    found = _MILEAGE.search(source or "")
    if not found:
        return None
    return int(re.sub(r"[\s.\u00a0]", "", found.group(1)))


def extract_crit_air(source: str | None) -> str | None:
    """Pick up the Crit'Air emissions sticker level."""
    found = _CRIT_AIR.search(source or "")
    return found.group(1) if found else None


def extract_inspection_date(source: str | None) -> str | None:
    """Pick up the date of the last roadworthiness test, in ISO form.

    Returns `YYYY-MM-DD` when the day is known, `YYYY-MM` otherwise, and
    `None` when the description does not date the test.
    """
    full = _INSPECTION_FULL_DATE.search(source or "")
    if full:
        day, month, year = full.groups()
        return f"{year}-{month}-{day}"
    partial = _INSPECTION_MONTH_YEAR.search(source or "")
    if partial:
        month, year = partial.groups()
        if 1 <= int(month) <= _MAX_MONTH:
            return f"{year}-{month}"
    return None


def extract_viewing_dates(source: str | None) -> str | None:
    """Pick up the viewing slot exactly as written, without rewording."""
    found = _VIEWING.search(source or "")
    if not found:
        return None
    return _WHITESPACE.sub(" ", found.group(1)).strip(" ,;")


def extract_declared_condition(source: str | None) -> str | None:
    """Pick up the condition mention exactly as written, without rewording."""
    found = _CONDITION.search(source or "")
    return _WHITESPACE.sub(" ", found.group(1)).strip() if found else None
