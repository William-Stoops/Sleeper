"""Perimetre geographique, base sur le lieu de RETRAIT du lot.

Le siege de la vente n'a aucune valeur operationnelle : une vente pilotee par
la direction de Saint-Maurice peut retirer ses lots dans toute la France. Seul
`dropoff_location` compte.

Un lot hors perimetre n'est jamais supprime : il est marque. La decision de
faire la route appartient a l'operateur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from sleeper.domain.texte import normaliser

_CHIFFRES = re.compile(r"\d+")

#: Seuil reel de partition de la Corse : Corse-du-Sud sous 20200, Haute-Corse au-dela.
_SEUIL_CORSE: Final = 20200
_LONGUEUR_CP_FR: Final = 5

#: Collectivites dont le code departement tient sur trois chiffres.
_PREFIXES_TROIS_CHIFFRES: Final = frozenset({"97", "98"})

#: Mentions par lesquelles un lieu de retrait etranger se signale dans les fiches.
#: La source ne porte pas de champ « pays » : le pays n'apparait que dans le
#: libelle du lieu, en toutes lettres.
_MENTIONS_PAYS: Final = {
    "BE": ("belgique", "belgium", "bruxelles", "anvers", "liege", "mons", "charleroi"),
    "LU": ("luxembourg", "grand duche"),
    "DE": ("allemagne", "germany"),
    "ES": ("espagne", "spain", "madrid"),
    "IT": ("italie", "italy"),
    "NL": ("pays bas", "netherlands", "amsterdam"),
    "CH": ("suisse", "switzerland"),
}


def departement_depuis_code_postal(code_postal: str | None) -> str | None:
    """Deduit le code departement d'un code postal francais.

    Renvoie `None` quand le code n'est pas un code postal francais exploitable
    — ce qui inclut les codes etrangers a quatre chiffres, traites ailleurs.
    """
    if not code_postal:
        return None
    chiffres = "".join(_CHIFFRES.findall(code_postal))
    if len(chiffres) != _LONGUEUR_CP_FR:
        return None
    if chiffres[:2] in _PREFIXES_TROIS_CHIFFRES:
        return chiffres[:3]
    if chiffres.startswith("20"):
        return "2A" if int(chiffres) < _SEUIL_CORSE else "2B"
    return chiffres[:2]


def pays_depuis_lieu(lieu: str | None) -> str | None:
    """Devine le pays a partir du libelle du lieu de retrait.

    Heuristique assumee : la source ne publie pas de code pays. On ne l'utilise
    que pour rattraper les lots etrangers, jamais pour ecarter un lot francais.
    """
    aplati = normaliser(lieu)
    if not aplati:
        return None
    for code, mentions in _MENTIONS_PAYS.items():
        if any(re.search(rf"\b{re.escape(m)}\b", aplati) for m in mentions):
            return code
    return None


@dataclass(frozen=True, slots=True)
class Perimetre:
    """Liste blanche de departements francais et de pays limitrophes."""

    departements: frozenset[str]
    pays_etrangers: frozenset[str] = frozenset()

    def contient(self, code_postal: str | None, lieu: str | None) -> bool:
        """Indique si le lieu de retrait tombe dans le perimetre d'achat."""
        departement = departement_depuis_code_postal(code_postal)
        if departement is not None:
            return departement in self.departements
        pays = pays_depuis_lieu(lieu)
        return pays is not None and pays in self.pays_etrangers
