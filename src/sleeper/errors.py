"""Hierarchie d'erreurs de Sleeper.

Principe directeur du projet : un scraper qui se degrade en silence est pire
qu'un scraper absent. Chaque mode de defaillance a donc son type, et aucun
n'est rattrape en produisant une valeur par defaut.
"""

from __future__ import annotations


class SleeperError(Exception):
    """Racine de toutes les erreurs du projet."""


class ConfigurationError(SleeperError):
    """Configuration absente, malformee ou incoherente. Echec au demarrage."""


class ReseauError(SleeperError):
    """Echec de transport apres epuisement des tentatives."""


class ProtectionAntiRobotError(SleeperError):
    """Le site presente un challenge anti-robot (CAPTCHA, WAF).

    Cette erreur est terminale par conception : Sleeper ne resout aucun
    challenge. Elle remonte jusqu'a l'operateur, qui espace les executions.
    """


class SchemaAmontError(SleeperError):
    """La reponse de l'API ne respecte plus la forme attendue.

    Levee quand un champ structurant disparait. C'est le garde-fou contre la
    degradation silencieuse : mieux vaut un run en echec qu'un run vide.
    """

    def __init__(self, chemin: str, detail: str) -> None:
        super().__init__(f"schema amont casse en '{chemin}' : {detail}")
        self.chemin = chemin
        self.detail = detail


class SessionError(SleeperError):
    """Impossible d'obtenir ou de renouveler une session navigateur valide."""


class SortieError(SleeperError):
    """Le document de sortie ne respecte pas son propre schema JSON."""
