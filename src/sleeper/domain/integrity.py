"""End-of-run integrity checks.

In sale 467 of the run of 2026-08-25, lots 192177 and 271498 carried the same
serial number `VF7VAYHVKKZ078443` with 294 364 and 273 545 km. Either the
source has a typo or an assignment is wrong. Nothing said a word.

These checks **never fail the run**. A collection that found lots is worth
delivering even when some of them look odd; what is not acceptable is
delivering them silently. Every anomaly carries its code, the lots concerned,
and the offending value, and lands in `run.erreurs`.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

#: A VIN is 17 characters and never uses I, O or Q — they read as 1 and 0.
_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

#: Plausibility bounds. Outside them, the figure is worth a human's eye.
_MAX_KM_PER_YEAR: Final = 60_000
_MIN_KM_PER_YEAR: Final = 500
_EARLIEST_REGISTRATION_YEAR: Final = 1950
_MAX_STARTING_PRICE: Final = 500_000.0


@dataclass(frozen=True, slots=True)
class Anomaly:
    """One integrity finding: what, on which lots, and the offending value."""

    code: str
    lot_ids: tuple[str, ...]
    value: str
    message: str


def check_integrity(lots: Sequence[Mapping[str, Any]], run_day: dt.date) -> list[Anomaly]:
    """Run every check over the whole run. Order is stable, so runs compare."""
    anomalies: list[Anomaly] = []
    anomalies.extend(_duplicate_vins(lots))
    for lot in lots:
        anomalies.extend(_check_lot(lot, run_day))
    return anomalies


def _duplicate_vins(lots: Sequence[Mapping[str, Any]]) -> list[Anomaly]:
    """The same serial number on two lots. Sorted, so the report is stable."""
    by_vin: dict[str, list[str]] = defaultdict(list)
    for lot in lots:
        if vin := str(lot.get("vin") or ""):
            by_vin[vin].append(str(lot["id"]))
    return [
        Anomaly(
            code="vin_double",
            lot_ids=tuple(sorted(ids)),
            value=vin,
            message=f"numéro de série porté par {len(ids)} lots distincts",
        )
        for vin, ids in sorted(by_vin.items())
        if len(ids) > 1
    ]


def _check_lot(lot: Mapping[str, Any], run_day: dt.date) -> list[Anomaly]:
    """Every per-lot check, in a fixed order."""
    lot_id = (str(lot["id"]),)
    found: list[Anomaly] = []

    vin = str(lot.get("vin") or "")
    if vin and not _VIN.match(vin):
        found.append(
            Anomaly(
                "vin_malforme",
                lot_id,
                vin,
                "un numéro de série fait 17 caractères, sans I, O ni Q",
            )
        )

    year = lot.get("first_registration_year")
    if year is not None and not (_EARLIEST_REGISTRATION_YEAR <= year <= run_day.year):
        found.append(
            Anomaly(
                "mise_en_circulation_invalide",
                lot_id,
                str(year),
                f"année hors de l'intervalle {_EARLIEST_REGISTRATION_YEAR}-{run_day.year}",
            )
        )
    elif (per_year := _mileage_per_year(lot, run_day)) is not None and not (
        _MIN_KM_PER_YEAR <= per_year <= _MAX_KM_PER_YEAR
    ):
        found.append(
            Anomaly(
                "kilometrage_incoherent",
                lot_id,
                f"{per_year} km/an",
                f"hors de l'intervalle {_MIN_KM_PER_YEAR}-{_MAX_KM_PER_YEAR} km/an",
            )
        )

    price = lot.get("starting_price")
    if price is not None and not (0 < price <= _MAX_STARTING_PRICE):
        found.append(Anomaly("mise_a_prix_invalide", lot_id, str(price), "mise à prix implausible"))

    bid = lot.get("current_bid")
    if bid is not None and price is not None and bid < price:
        found.append(
            Anomaly(
                "enchere_inferieure_mise_a_prix",
                lot_id,
                f"{bid} < {price}",
                "enchère en cours inférieure à la mise à prix",
            )
        )
    return found


def _mileage_per_year(lot: Mapping[str, Any], run_day: dt.date) -> int | None:
    """Yearly mileage, or `None` when either figure is missing."""
    mileage = lot.get("mileage")
    year = lot.get("first_registration_year")
    if not mileage or year is None:
        return None
    age = max(run_day.year - int(year), 1)
    return round(float(mileage) / age)
