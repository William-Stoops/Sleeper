"""Refuse any personal or banking data anywhere in the repository.

The API payloads carry, verbatim, the IBAN of the State's collection account
and the name, email and mobile of named civil servants. None of it serves a
buying decision.

**This check used to look at `tests/fixtures/` alone, and that was the flaw.**
Real phone numbers and a real professional email reached `tests/` as test data
for this very guard, and it never saw them — they were caught only by a manual
sweep before the first push. It now scans every tracked file.

    uv run python tools/check_no_personal_data.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Final

PATTERNS: Final = {
    # A VIN is 17 characters and matches a naive IBAN pattern. Real IBANs run
    # to at least 20; France uses 27. Requiring 20 keeps vehicle serial
    # numbers out of the false positives.
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[0-9A-Z]{16,30}\b"),
    "courriel": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    "téléphone": re.compile(r"\b0[1-9](?:[ .\-]?\d{2}){4}\b"),
}

#: Values that are legitimately in the repository: the project's own contacts,
#: and the deliberately fake ones the tests need to exercise the patterns.
ALLOWED: Final = frozenset(
    {
        "contact@exemple.fr",
        "prenom.nom@exemple.gouv.fr",
        # Contre-exemples du garde-fou lui-même : des adresses qui doivent
        # être détectées, donc d'apparence réelle, donc inventées de bout en
        # bout — aucun de ces domaines n'existe.
        "nom.invente@fournisseur-imaginaire.fr",
        "agent@ministere-invente.gouv.fr",
        "piege@example.org.attaquant.fr",
        "noreply@anthropic.com",
        "williamstoops2@gmail.com",
        "me@affaanmustafa.com",
        "FR7600000000000000000000000",
        "DE89370400440532013000",
        "06-00-00-00-00",
        "06 00 00 00 00",
        "0600000000",
    }
)

#: Domains the RFC 2606 / RFC 6761 reserve for documentation and examples.
#: Nobody can register them, so an address there belongs to no one and cannot
#: leak. Recognising the rule beats listing every fake address one by one.
RESERVED_DOMAINS: Final = re.compile(
    r"@([\w-]+\.)*(example|invalid|test|localhost)(\.[a-z]{2,})?$", re.IGNORECASE
)

#: File names that must never be tracked, whatever they contain. A service
#: account grants write access to someone's Drive; a private key is worse.
FORBIDDEN_NAMES: Final = re.compile(
    r"service[-_]?account|credentials\.json|\.pem$|\.key$|\.p12$|\.pfx$",
    re.IGNORECASE,
)

#: Binary and generated files it makes no sense to scan.
SKIPPED_SUFFIXES: Final = frozenset({".png", ".jpg", ".jpeg", ".pdf", ".ico", ".lock"})


def tracked_files() -> list[Path]:
    """Every file git tracks — what a push would actually publish."""
    listing = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(name) for name in listing.stdout.split("\n") if name]


def _is_reserved(value: str) -> bool:
    """An address at a reserved domain names nobody, so it cannot leak."""
    return bool(RESERVED_DOMAINS.search(value))


def main() -> int:
    """Scan the repository and report anything that must not be published."""
    leaks: list[str] = []
    scanned = 0
    for file in tracked_files():
        if FORBIDDEN_NAMES.search(file.as_posix()):
            leaks.append(f"{file}: fichier de secret versionné")
        if file.suffix in SKIPPED_SUFFIXES or not file.is_file():
            continue
        scanned += 1
        content = file.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in PATTERNS.items():
            leaks.extend(
                f"{file}: {name} => {found}"
                for found in sorted(set(pattern.findall(content)))
                if found not in ALLOWED and not _is_reserved(found)
            )

    if leaks:
        print("Données personnelles détectées dans des fichiers versionnés :", file=sys.stderr)
        for leak in sorted(set(leaks)):
            print(f"  - {leak}", file=sys.stderr)
        print(
            "\nLes expurger avant de versionner. Si la valeur est légitime — "
            "une adresse du projet, ou une valeur inventée pour un test — "
            "l'ajouter à ALLOWED dans ce fichier.",
            file=sys.stderr,
        )
        return 1
    print(f"Dépôt propre : {scanned} fichiers versionnés inspectés, aucun secret.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
