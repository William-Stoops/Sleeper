"""Journalisation structuree.

Le format `json` est celui de la tache planifiee : chaque evenement est une
ligne exploitable. Le format `console` sert au diagnostic humain.

Les logs portent un compteur de ce qui a ete vu, retenu, ecarte et pourquoi :
c'est le seul moyen de constater qu'un run « reussi » n'a en fait rien
collecte.

`configurer` est idempotente et re-entrante : chaque appel reinstalle le
handler sur le flux d'erreur COURANT. Sans cela, un processus qui reconfigure
la journalisation continuerait d'ecrire sur un flux devenu invalide.
"""

from __future__ import annotations

import logging
import sys

import structlog

from sleeper.config import Journalisation


def configurer(journalisation: Journalisation) -> None:
    """Installe la configuration structlog du processus."""
    niveau = getattr(logging, journalisation.niveau)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=niveau, force=True)

    rendu: structlog.typing.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if journalisation.format == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            rendu,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(niveau),
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Sans cela, un logger capture au premier appel continuerait d'ecrire
        # sur le flux de la configuration precedente.
        cache_logger_on_first_use=False,
    )
