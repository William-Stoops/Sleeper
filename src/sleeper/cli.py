"""Interface en ligne de commande.

Trois commandes seulement :

* `collecter`      — le run quotidien ;
* `valider-config` — controle de la configuration, sans toucher au reseau ;
* `schema`         — (re)publication du JSON Schema de sortie.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import structlog
import typer
from rich.console import Console
from rich.table import Table

from sleeper import __version__
from sleeper.api.client import ClientDomaine
from sleeper.api.session import SessionNavigateur
from sleeper.config import Configuration, charger_configuration
from sleeper.domain.models import DocumentSortie
from sleeper.errors import ProtectionAntiRobotError, SleeperError
from sleeper.logging_setup import configurer
from sleeper.output import document as doc_sortie
from sleeper.output.digest import rediger
from sleeper.output.sink import Sink, SinkFichier, nom_horodate
from sleeper.pipeline import Collecteur
from sleeper.state.store import EtatSleeper

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Collecteur des ventes de vehicules des Encheres du Domaine.",
)
console = Console()
_LOG = structlog.get_logger(__name__)

CheminConfig = Annotated[
    Path, typer.Option("--config", "-c", help="Fichier de configuration TOML.")
]
DEFAUT_CONFIG = Path("config/default.toml")

#: Codes de sortie distincts, pour qu'une tache planifiee sache quoi alerter.
CODE_ERREUR_METIER = 1
CODE_ANTI_ROBOT = 3


def _charger(chemin: Path) -> Configuration:
    """Charge la configuration ou sort proprement avec un message lisible."""
    try:
        config = charger_configuration(chemin)
    except SleeperError as exc:
        console.print(f"[bold red]Configuration invalide[/]\n{exc}")
        raise typer.Exit(CODE_ERREUR_METIER) from exc
    configurer(config.journalisation)
    return config


@app.command()
def collecter(
    config_path: CheminConfig = DEFAUT_CONFIG,
    session_cache: Annotated[
        Path, typer.Option("--session", help="Cache de session navigateur.")
    ] = Path("var/etat/session.json"),
) -> None:
    """Balaye les ventes en cours et a venir, et produit le JSON et le digest."""
    config = _charger(config_path)
    _LOG.info("run.demarrage", version=__version__, config=str(config_path))

    session = SessionNavigateur(config.reseau, session_cache)
    try:
        with (
            EtatSleeper(config.etat.base) as etat,
            ClientDomaine(config.reseau, session) as client,
        ):
            resultat = Collecteur(config, client, etat).executer()
    except ProtectionAntiRobotError as exc:
        console.print(f"[bold yellow]Arret volontaire[/] : {exc}")
        _LOG.error("run.anti_robot", message=str(exc))
        raise typer.Exit(CODE_ANTI_ROBOT) from exc
    except SleeperError as exc:
        console.print(f"[bold red]Run interrompu[/] : {exc}")
        _LOG.error("run.echec", type=type(exc).__name__, message=str(exc))
        raise typer.Exit(CODE_ERREUR_METIER) from exc

    _publier(config, resultat)
    _resumer(resultat)
    if any(lot.incomplet for lot in resultat.lots):
        raise typer.Exit(CODE_ERREUR_METIER)


def _publier(config: Configuration, resultat: DocumentSortie) -> None:
    """Valide puis depose le document et son digest."""
    try:
        doc_sortie.valider(resultat)
    except SleeperError as exc:
        console.print(f"[bold red]Sortie non conforme[/] : {exc}")
        raise typer.Exit(CODE_ERREUR_METIER) from exc

    sink: Sink = SinkFichier(config.sortie.repertoire)
    nom = nom_horodate("sleeper", resultat.run.horodatage.isoformat(), "json")
    chemin = sink.deposer(nom, doc_sortie.serialiser(resultat))
    lien = sink.pointer_vers_courant(nom, config.sortie.nom_lien_courant)
    _LOG.info("sortie.ecrite", fichier=chemin, lien=lien)

    if config.sortie.digest:
        nom_md = nom_horodate("sleeper", resultat.run.horodatage.isoformat(), "md")
        sink.deposer(nom_md, rediger(resultat).encode("utf-8"))
        sink.pointer_vers_courant(nom_md, config.sortie.nom_digest)


def _resumer(resultat: DocumentSortie) -> None:
    """Affiche le bilan du run dans le terminal."""
    run = resultat.run
    table = Table(title="Run Sleeper", show_header=False)
    table.add_row("Ventes balayées", str(run.ventes_scannees))
    table.add_row("Lots vus", str(run.lots_vus))
    table.add_row("Lots retenus", f"[bold green]{run.lots_retenus}[/]")
    table.add_row("Lots écartés", str(run.lots_ecartes))
    table.add_row("Nouveaux", str(sum(lot.nouveau_depuis_dernier_run for lot in resultat.lots)))
    table.add_row("Enchères en mouvement", str(sum(lot.enchere_a_bouge for lot in resultat.lots)))
    table.add_row(
        "Réservés aux pros",
        str(sum(lot.reserve_aux_professionnels is True for lot in resultat.lots)),
    )
    incomplets = sum(lot.incomplet for lot in resultat.lots)
    table.add_row("Incomplets", f"[bold red]{incomplets}[/]" if incomplets else "0")
    table.add_row("Erreurs", f"[bold red]{len(run.erreurs)}[/]" if run.erreurs else "0")
    table.add_row("Durée", f"{run.duree_secondes:.1f} s")
    console.print(table)
    for erreur in run.erreurs:
        console.print(f"  [red]•[/] {erreur.etape} / {erreur.cible} : {erreur.message}")


@app.command("valider-config")
def valider_config(config_path: CheminConfig = DEFAUT_CONFIG) -> None:
    """Controle la configuration sans emettre la moindre requete."""
    config = _charger(config_path)
    perimetre = config.perimetre_domaine()
    moteur = config.moteur_exclusions()
    table = Table(title=f"Configuration : {config_path}", show_header=False)
    table.add_row("Départements", str(len(perimetre.departements)))
    table.add_row("Pays étrangers", ", ".join(sorted(perimetre.pays_etrangers)) or "aucun")
    table.add_row("Règles d'exclusion", str(len(moteur.regles)))
    table.add_row("Cadence", f"{config.reseau.delai_entre_requetes_s} s entre requêtes")
    table.add_row("Concurrence", str(config.reseau.concurrence_max))
    table.add_row("Sortie", str(config.sortie.repertoire))
    table.add_row("État", str(config.etat.base))
    console.print(table)
    console.print("[bold green]Configuration valide.[/]")


@app.command()
def schema() -> None:
    """(Re)publie le JSON Schema du document de sortie."""
    chemin = doc_sortie.publier_schema()
    console.print(f"Schéma {doc_sortie.VERSION_SCHEMA} publié : [bold]{chemin}[/]")


if __name__ == "__main__":  # pragma: no cover
    app()
