"""Destinations de sortie.

Le contrat est volontairement minimal — deposer un contenu nomme, et faire
pointer un nom stable vers le dernier depot — pour qu'une destination
distante (depot Git, stockage objet) puisse etre ajoutee plus tard sans
toucher au reste de la chaine.

Seule la destination « fichier local » est implementee aujourd'hui.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Sink(Protocol):
    """Destination des artefacts produits par un run."""

    def deposer(self, nom: str, contenu: bytes) -> str:
        """Depose un contenu et rend son emplacement, lisible par un humain."""
        ...

    def pointer_vers_courant(self, nom_cible: str, nom_lien: str) -> str:
        """Fait pointer un nom stable vers le dernier artefact depose."""
        ...


class SinkFichier:
    """Ecrit dans un repertoire local, avec un raccourci vers le dernier run."""

    def __init__(self, repertoire: Path) -> None:
        self._repertoire = repertoire
        repertoire.mkdir(parents=True, exist_ok=True)

    @property
    def repertoire(self) -> Path:
        return self._repertoire

    def deposer(self, nom: str, contenu: bytes) -> str:
        """Ecrit le contenu de maniere atomique : jamais de fichier a moitie ecrit."""
        cible = self._repertoire / nom
        provisoire = cible.with_name(f".{nom}.partiel")
        provisoire.write_bytes(contenu)
        provisoire.replace(cible)
        return str(cible)

    def pointer_vers_courant(self, nom_cible: str, nom_lien: str) -> str:
        """Cree `latest.json` : lien symbolique si possible, copie sinon.

        Windows refuse les liens symboliques sans privilege particulier ; on
        retombe alors sur une copie, qui rend le meme service.
        """
        lien = self._repertoire / nom_lien
        cible = self._repertoire / nom_cible
        lien.unlink(missing_ok=True)
        try:
            lien.symlink_to(nom_cible)
        except (OSError, NotImplementedError):
            lien.write_bytes(cible.read_bytes())
        return str(lien)


def nom_horodate(prefixe: str, instant: str, extension: str) -> str:
    """Compose un nom de fichier portable a partir d'un horodatage ISO."""
    sur = instant.replace(":", "-").replace("+", "_")
    return f"{prefixe}-{sur}.{extension}"
