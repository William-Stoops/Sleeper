"""Command-line interface.

Three commands only:

* `collecter`      — the daily run;
* `valider-config` — checks the configuration, without touching the network;
* `schema`         — (re)publishes the output JSON Schema.

Command names and every string shown to the operator are French: this is the
user interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import structlog
import typer
from rich.console import Console
from rich.table import Table

from sleeper import __version__
from sleeper.api.client import DomaineClient
from sleeper.api.transport import BrowserTransport
from sleeper.config import Configuration, load_configuration
from sleeper.domain.models import OutputDocument, RunError
from sleeper.errors import AntiBotChallengeError, SleeperError
from sleeper.logging_setup import configure
from sleeper.output import document as output_document
from sleeper.output.digest import render
from sleeper.output.drive import DriveSink, build_client
from sleeper.output.sink import FileSink, Sink, timestamped_name
from sleeper.pipeline import Collector
from sleeper.state.store import SleeperState

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Collecteur des ventes de véhicules des Enchères du Domaine.",
)
console = Console()
_LOG = structlog.get_logger(__name__)

ConfigPath = Annotated[Path, typer.Option("--config", "-c", help="Fichier de configuration TOML.")]
DEFAULT_CONFIG = Path("config/default.toml")

#: Distinct exit codes, so a scheduled task knows what to alert on.
EXIT_BUSINESS_ERROR = 1
EXIT_ANTI_BOT = 3


def _load(path: Path) -> Configuration:
    """Load the configuration, or exit cleanly with a readable message."""
    try:
        config = load_configuration(path)
    except SleeperError as exc:
        console.print(f"[bold red]Configuration invalide[/]\n{exc}")
        raise typer.Exit(EXIT_BUSINESS_ERROR) from exc
    configure(config.logging)
    return config


@app.command()
def collecter(
    config_path: ConfigPath = DEFAULT_CONFIG,
    session_cache: Annotated[
        Path, typer.Option("--session", help="Cache de session navigateur.")
    ] = Path("var/etat/session.json"),
) -> None:
    """Balaye les ventes en cours et à venir, et produit le JSON et le digest."""
    config = _load(config_path)
    _LOG.info("run.starting", version=__version__, config=str(config_path))

    try:
        with (
            SleeperState(config.state.database) as state,
            BrowserTransport(config.network, session_cache) as transport,
        ):
            gateway = DomaineClient(config.network, transport)
            result = Collector(config, gateway, state).run()
    except AntiBotChallengeError as exc:
        console.print(f"[bold yellow]Arrêt volontaire[/] : {exc}")
        _LOG.error("run.anti_bot", message=str(exc))
        raise typer.Exit(EXIT_ANTI_BOT) from exc
    except SleeperError as exc:
        console.print(f"[bold red]Run interrompu[/] : {exc}")
        _LOG.error("run.failed", kind=type(exc).__name__, message=str(exc))
        raise typer.Exit(EXIT_BUSINESS_ERROR) from exc

    result = _publish(config, result)
    _summarise(result)
    if any(lot.is_incomplete for lot in result.lots):
        raise typer.Exit(EXIT_BUSINESS_ERROR)


def _publish(config: Configuration, result: OutputDocument) -> OutputDocument:
    """Validate, write locally, then try Drive.

    Local first, always: a collection that found lots is worth keeping even
    when the upload fails. A Drive failure is then folded back into the
    document and the local file is rewritten, so the error is where the
    operator will look for it.
    """
    try:
        output_document.validate(result)
    except SleeperError as exc:
        console.print(f"[bold red]Sortie non conforme[/] : {exc}")
        raise typer.Exit(EXIT_BUSINESS_ERROR) from exc

    local = FileSink(config.output.directory)
    _write(local, config, result)

    if not config.output.drive.enabled:
        return result

    try:
        _upload_to_drive(config, result)
    except Exception as exc:
        console.print(f"[bold yellow]Dépôt sur Drive échoué[/] : {exc}")
        _LOG.error("drive.failed", kind=type(exc).__name__, message=str(exc))
        failed = result.model_copy(
            update={
                "run": result.run.model_copy(
                    update={
                        "errors": [
                            *result.run.errors,
                            RunError(
                                step="drive",
                                target=config.output.drive.folder_id,
                                kind=type(exc).__name__,
                                message=(
                                    f"dépôt sur Drive échoué : {exc}. Le fichier local "
                                    "est écrit et reste la source."
                                ),
                            ),
                        ]
                    }
                )
            }
        )
        _write(local, config, failed)
        return failed
    return result


def _write(sink: Sink, config: Configuration, result: OutputDocument) -> None:
    """Write the document and its digest to a destination."""
    name = timestamped_name("sleeper", result.run.timestamp, "json")
    path = sink.put(name, output_document.serialize(result))
    link = sink.point_at_latest(name, config.output.current_link_name)
    _LOG.info("output.written", file=path, link=link)

    if config.output.digest:
        digest_name = timestamped_name("sleeper", result.run.timestamp, "md")
        sink.put(digest_name, render(result).encode("utf-8"))
        sink.point_at_latest(digest_name, config.output.digest_name)


def _upload_to_drive(config: Configuration, result: OutputDocument) -> None:
    """Deposit the run on Drive: one timestamped file, one stable name."""
    drive = DriveSink(
        build_client(config.output.drive.credentials_path), config.output.drive.folder_id
    )
    payload = output_document.serialize(result)
    drive.put(timestamped_name("sleeper", result.run.timestamp, "json"), payload)
    drive.put(config.output.current_link_name, payload)
    if config.output.digest:
        digest = render(result).encode("utf-8")
        drive.put(timestamped_name("sleeper", result.run.timestamp, "md"), digest)
        drive.put(config.output.digest_name, digest)


def _summarise(result: OutputDocument) -> None:
    """Print the run summary in the terminal."""
    run = result.run
    table = Table(title="Run Sleeper", show_header=False)
    table.add_row("Ventes balayées", str(run.sales_scanned))
    table.add_row("Lots vus", str(run.lots_seen))
    table.add_row("Lots retenus", f"[bold green]{run.lots_kept}[/]")
    table.add_row("Lots écartés", str(run.lots_rejected))
    table.add_row("Nouveaux", str(sum(lot.new_since_last_run for lot in result.lots)))
    table.add_row("Enchères en mouvement", str(sum(lot.bid_moved for lot in result.lots)))
    table.add_row("Réservés aux pros", str(sum(lot.trade_only is True for lot in result.lots)))
    incomplete = sum(lot.is_incomplete for lot in result.lots)
    table.add_row("Incomplets", f"[bold red]{incomplete}[/]" if incomplete else "0")
    table.add_row("Erreurs", f"[bold red]{len(run.errors)}[/]" if run.errors else "0")
    table.add_row("Durée", f"{run.duration_seconds:.1f} s")
    console.print(table)
    for error in run.errors:
        console.print(f"  [red]•[/] {error.step} / {error.target} : {error.message}")


@app.command("valider-config")
def validate_config(config_path: ConfigPath = DEFAULT_CONFIG) -> None:
    """Contrôle la configuration sans émettre la moindre requête."""
    config = _load(config_path)
    perimeter = config.perimeter()
    engine = config.exclusion_engine()
    table = Table(title=f"Configuration : {config_path}", show_header=False)
    table.add_row("Départements", str(len(perimeter.departments)))
    table.add_row("Pays étrangers", ", ".join(sorted(perimeter.foreign_countries)) or "aucun")
    table.add_row("Règles d'exclusion", str(len(engine.rules)))
    table.add_row("Cadence", f"{config.network.delay_between_requests_s} s entre requêtes")
    table.add_row("Sortie", str(config.output.directory))
    table.add_row("État", str(config.state.database))
    console.print(table)
    console.print("[bold green]Configuration valide.[/]")


@app.command()
def schema() -> None:
    """(Re)publie le JSON Schema du document de sortie."""
    path = output_document.publish_schema()
    console.print(f"Schéma {output_document.SCHEMA_VERSION} publié : [bold]{path}[/]")


if __name__ == "__main__":  # pragma: no cover
    app()
