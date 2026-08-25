"""Check the reference tables load and still say what they claim.

The scoring is never better than these two files, so a malformed pattern or a
truncated table must break the build rather than quietly change every rank.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from sleeper.scoring.tables import QuoteTable, RepairTable

#: Below this, the quote table has plainly been truncated.
_MIN_QUOTES: Final = 50
_EXPECTED_REPAIRS: Final = 20


def main() -> int:
    """Load both tables and assert the properties the project relies on."""
    quotes = QuoteTable.load(Path("config/cotes.csv"))
    repairs = RepairTable.load(Path("config/reparations.csv"))

    problems: list[str] = []
    if len(quotes) < _MIN_QUOTES:
        problems.append(f"table de cotes trop courte : {len(quotes)} lignes")
    if len(repairs) != _EXPECTED_REPAIRS:
        problems.append(
            f"table de réparations : {len(repairs)} forfaits, {_EXPECTED_REPAIRS} attendus"
        )
    if sources := {row.source for row in quotes.rows} - {"amorce_a_calibrer"}:
        problems.append(
            f"cotes non estampillées comme amorce : {', '.join(sorted(sources))}. "
            "Une valeur vérifiée est une bonne nouvelle — mettre à jour ce contrôle."
        )
    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"Tables valides : {len(quotes)} cotes, {len(repairs)} forfaits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
