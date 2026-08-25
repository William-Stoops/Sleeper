"""Refuse toute donnee personnelle ou bancaire dans les fixtures versionnees.

Les charges utiles de l'API contiennent, telles quelles, l'IBAN du compte de
l'Etat, ainsi que le nom, le courriel et le telephone d'agents publics. Ces
informations ne servent a aucune decision d'achat : elles sont expurgees a la
capture, et ce controle garantit qu'aucune ne revient par une nouvelle
capture.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final

RACINE: Final = Path("tests/fixtures")

MOTIFS: Final = {
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[0-9A-Z]{10,30}\b"),
    "courriel": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    "telephone": re.compile(r"\b0[1-9](?:[ .\-]?\d{2}){4}\b"),
}


def main() -> int:
    fuites: list[str] = []
    for fichier in sorted(RACINE.rglob("*.json")):
        contenu = fichier.read_text(encoding="utf-8")
        for nom, motif in MOTIFS.items():
            for trouve in set(motif.findall(contenu)):
                fuites.append(f"{fichier}: {nom} => {trouve}")
    if fuites:
        print("Donnees personnelles detectees dans les fixtures :", file=sys.stderr)
        for fuite in fuites:
            print(f"  - {fuite}", file=sys.stderr)
        print("Les expurger avant de versionner.", file=sys.stderr)
        return 1
    print(f"Fixtures propres ({len(list(RACINE.rglob('*.json')))} fichiers).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
