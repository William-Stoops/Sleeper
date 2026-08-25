"""Reference tables: resale quotes and repair allowances.

**These values are a starting point, not a truth.** Every quote row is
stamped `amorce_a_calibrer`: they come from an estimate of the French market,
not from comparables verified one by one. Calibrating this table is the main
debt of the project, and the scoring is only ever as good as it.

The repair patterns, by contrast, are taken from the real descriptions of the
run of 2026-08-25 — they were read off the seam, not invented.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from sleeper.errors import ConfigurationError

#: How bad a repair is, beyond its price. `signal` costs nothing and only
#: tells the score that something is unknown.
Severity = Literal["redhibitoire", "lourd", "moyen", "leger", "signal"]

#: The quote is clamped to this band around its reference, so that extreme
#: mileages cannot extrapolate into absurdity.
_MIN_RATIO: Final = 0.25
_MAX_RATIO: Final = 1.75

_QUOTE_COLUMNS: Final = frozenset(
    {
        "marque",
        "modele",
        "carburant",
        "annee_min",
        "annee_max",
        "km_reference",
        "cote_reference_eur",
        "decote_par_10k_km_pct",
        "source",
    }
)
_REPAIR_COLUMNS: Final = frozenset({"motif", "pattern", "cout_eur", "gravite"})


def _key(value: str) -> str:
    """Comparison form of a make, model or fuel: upper case, no stray spaces."""
    return " ".join((value or "").strip().upper().split())


@dataclass(frozen=True, slots=True)
class QuoteRow:
    """One line of the resale table."""

    make: str
    model: str
    fuel: str
    year_min: int
    year_max: int
    reference_km: int
    reference_eur: float
    decay_per_10k_km_pct: float
    source: str

    def covers(self, make: str, model: str, fuel: str, year: int | None) -> bool:
        """Whether this row is the one for that vehicle."""
        return (
            self.make == _key(make)
            and self.model == _key(model)
            and self.fuel == _key(fuel)
            and year is not None
            and self.year_min <= year <= self.year_max
        )

    def at(self, mileage: int) -> float:
        """Quote at a given mileage, clamped to the plausibility band."""
        drift = self.decay_per_10k_km_pct / 100 * (mileage - self.reference_km) / 10_000
        ratio = min(max(1 - drift, _MIN_RATIO), _MAX_RATIO)
        return self.reference_eur * ratio


class QuoteTable:
    """Resale quotes, resolved on make, model, fuel and year."""

    def __init__(self, rows: list[QuoteRow]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def rows(self) -> list[QuoteRow]:
        return list(self._rows)

    @classmethod
    def load(cls, path: Path) -> QuoteTable:
        """Read the table, failing loudly on anything malformed."""
        return cls(
            [
                QuoteRow(
                    make=_key(row["marque"]),
                    model=_key(row["modele"]),
                    fuel=_key(row["carburant"]),
                    year_min=int(row["annee_min"]),
                    year_max=int(row["annee_max"]),
                    reference_km=int(row["km_reference"]),
                    reference_eur=float(row["cote_reference_eur"]),
                    decay_per_10k_km_pct=float(row["decote_par_10k_km_pct"]),
                    source=row["source"],
                )
                for row in _read_csv(path, _QUOTE_COLUMNS, "cotes")
            ]
        )

    def find(self, make: str, model: str, fuel: str, year: int | None) -> QuoteRow | None:
        """The row covering that vehicle, if the table knows it."""
        return next((r for r in self._rows if r.covers(make, model, fuel, year)), None)

    def quote(
        self, make: str, model: str, fuel: str, year: int | None, mileage: int | None
    ) -> float | None:
        """Resale quote, or `None` when the table does not know the vehicle.

        A lot without a quote is **not** dropped: it goes into a separate
        queue, because an unknown model going for 500 € is exactly the profile
        this project is looking for.
        """
        if mileage is None:
            return None
        row = self.find(make, model, fuel, year)
        return None if row is None else row.at(mileage)


@dataclass(frozen=True, slots=True)
class RepairMatch:
    """A repair allowance that a description triggered, with its evidence."""

    code: str
    cost_eur: float
    severity: Severity
    evidence: str


@dataclass(frozen=True, slots=True)
class RepairRow:
    """One line of the repair table."""

    code: str
    pattern: re.Pattern[str]
    cost_eur: float
    severity: Severity


class RepairTable:
    """Repair allowances, triggered by wording found in the description."""

    def __init__(self, rows: list[RepairRow]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def rows(self) -> list[RepairRow]:
        return list(self._rows)

    @classmethod
    def load(cls, path: Path) -> RepairTable:
        """Read the table, failing loudly on a malformed pattern."""
        rows = []
        for row in _read_csv(path, _REPAIR_COLUMNS, "reparations"):
            try:
                pattern = re.compile(row["pattern"], re.IGNORECASE)
            except re.error as exc:
                raise ConfigurationError(
                    f"motif de reparation invalide dans {path}, ligne « {row['motif']} » : {exc}"
                ) from exc
            severity = _severity(row["gravite"], path, row["motif"])
            rows.append(
                RepairRow(
                    code=row["motif"],
                    pattern=pattern,
                    cost_eur=float(row["cout_eur"]),
                    severity=severity,
                )
            )
        return cls(rows)

    def match(self, description: str | None) -> list[RepairMatch]:
        """Every allowance the description triggers, in table order.

        Table order, not match order: two runs over the same text must produce
        the same list, or the score would not be reproducible.
        """
        text = description or ""
        found: list[RepairMatch] = []
        for row in self._rows:
            hit = row.pattern.search(text)
            if hit is None:
                continue
            found.append(
                RepairMatch(
                    code=row.code,
                    cost_eur=row.cost_eur,
                    severity=row.severity,
                    evidence=" ".join(hit.group(0).split()),
                )
            )
        return found


#: Every severity the table may declare. Narrowing goes through here so the
#: type checker knows the value is one of them.
_SEVERITIES: Final[frozenset[str]] = frozenset(
    {"redhibitoire", "lourd", "moyen", "leger", "signal"}
)


def _severity(value: str, path: Path, code: str) -> Severity:
    """Read a severity, refusing anything the score would not know what to do with."""
    if value not in _SEVERITIES:
        raise ConfigurationError(f"gravité inconnue dans {path}, ligne « {code} » : {value}")
    return cast(Severity, value)


def _read_csv(path: Path, expected: frozenset[str], label: str) -> list[dict[str, str]]:
    """Read a reference table, refusing anything that is not the right shape."""
    if not path.is_file():
        raise ConfigurationError(f"table {label} introuvable : {path}")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            if missing := expected - columns:
                raise ConfigurationError(
                    f"table {label} malformée dans {path} : "
                    f"colonne(s) manquante(s) {', '.join(sorted(missing))}"
                )
            return list(reader)
    except OSError as exc:
        raise ConfigurationError(f"lecture impossible de {path} : {exc}") from exc
