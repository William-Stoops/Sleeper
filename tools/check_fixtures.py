"""Reject any personal or banking data in the versioned fixtures.

The API payloads contain, verbatim, the IBAN of the State's account as well as
the name, email and phone number of public servants. None of that serves a
buying decision: it is stripped at capture time, and this check makes sure a
fresh capture never brings it back.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final

ROOT: Final = Path("tests/fixtures")

PATTERNS: Final = {
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[0-9A-Z]{10,30}\b"),
    "courriel": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    "téléphone": re.compile(r"\b0[1-9](?:[ .\-]?\d{2}){4}\b"),
}


def main() -> int:
    """Scan the fixtures and report anything that leaked."""
    leaks: list[str] = []
    for file in sorted(ROOT.rglob("*.json")):
        content = file.read_text(encoding="utf-8")
        for name, pattern in PATTERNS.items():
            leaks.extend(f"{file}: {name} => {found}" for found in set(pattern.findall(content)))
    if leaks:
        print("Données personnelles détectées dans les fixtures :", file=sys.stderr)
        for leak in leaks:
            print(f"  - {leak}", file=sys.stderr)
        print("Les expurger avant de versionner.", file=sys.stderr)
        return 1
    print(f"Fixtures propres ({len(list(ROOT.rglob('*.json')))} fichiers).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
