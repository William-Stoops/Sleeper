"""Tables de correspondance de l'API Magento du Domaine.

Ces valeurs sont des constantes du protocole amont, relevees pendant la phase
de decouverte (voir docs/api.md). Elles ne sont pas configurables : ce ne sont
pas des reglages metier mais la grammaire de la source.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final


class StatutVente(IntEnum):
    """`auction_auto_status` : cycle de vie d'une vente."""

    A_VENIR = 2
    EN_COURS = 3
    CLOTUREE = 4

    @classmethod
    def ouvertes(cls) -> tuple[StatutVente, ...]:
        """Statuts qu'un run quotidien doit balayer."""
        return (cls.A_VENIR, cls.EN_COURS)


class Ternaire(StrEnum):
    """Reponse d'un attribut booleen du Domaine, qui admet un troisieme etat."""

    OUI = "Oui"
    NON = "Non"
    INDETERMINE = "N/A"


#: `professional_only` arrive en `str` sur une vente et en `int` sur un lot.
#: L'incoherence est amont ; elle est absorbee ici, une fois pour toutes.
VRAI_API: Final = frozenset({1, "1", "Oui", "oui"})  # 1 == True en Python
FAUX_API: Final = frozenset({0, "0", "Non", "non"})  # 0 == False en Python

#: Genres de carte grise (attribut `kind`), rubrique J.1 du certificat.
GENRE_VOITURE: Final = "VP"
GENRE_CAMIONNETTE: Final = "CTTE"

#: Genres a ignorer d'office : deux-roues, quadricycles, agricole, remorques.
#: `QM` couvre le quadricycle a moteur, c'est-a-dire la voiture sans permis.
GENRES_HORS_CIBLE: Final = frozenset(
    {
        "CL",
        "CM",
        "MTL",
        "MTT1",
        "MTT2",
        "MTT3",
        "MTT4",  # deux-roues
        "QM",
        "QLEM",
        "QLOM",  # quadricycles / sans permis
        "TRA",
        "MAGA",
        "MIAR",
        "MAAG",  # agricole
        "REM",
        "REMORQUE",
        "RESP",
        "SREM",  # remorques
    }
)

#: Codes attributs porteurs de donnees personnelles ou bancaires.
#: Ils ne sont jamais recopies dans la sortie ni dans les fixtures.
ATTRIBUTS_SENSIBLES: Final = frozenset(
    {"biciban", "contact_dropoff_location_id", "bid_winner_user", "id_remitting_entity"}
)


def vers_booleen(valeur: object) -> bool | None:
    """Normalise un booleen de l'API. Renvoie `None` si la source est muette.

    `None` signifie « absent de la source », jamais « on n'a pas su lire » :
    une valeur inconnue leve, elle ne se tait pas.
    """
    if valeur is None or valeur == "":
        return None
    if valeur in VRAI_API:
        return True
    if valeur in FAUX_API:
        return False
    if isinstance(valeur, str) and valeur.strip().upper() in {"N/A", "NA", "-"}:
        return None
    raise ValueError(f"booleen amont non reconnu : {valeur!r}")
