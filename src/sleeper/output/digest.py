"""Markdown digest: what gets read in the morning, in thirty seconds.

Four questions, in order of interest: what is new, where bids have moved,
which lots are trade-only, and what went wrong during the run.

The rendered text is French: it is read by the operator.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sleeper.domain.models import Lot, OutputDocument, RejectedLot, Run, RunError

#: Beyond this, the digest stops being readable at a glance; the JSON remains
#: the complete source.
SECTION_LIMIT = 40


def _euros(amount: float | None) -> str:
    return "—" if amount is None else f"{amount:,.0f} €".replace(",", " ")


def _access(lot: Lot) -> str:
    if lot.trade_only is True:
        return "**PRO**"
    if lot.trade_only is False:
        return "tous publics"
    return "⚠️ inconnu"


def _row(lot: Lot) -> str:
    place = f"{lot.department or '??'} {lot.collection_place}".strip()
    outside = {"hors": " · *hors périmètre*", "inconnu": " · **périmètre ?**"}.get(lot.scope, "")
    mileage = "—" if lot.mileage is None else f"{lot.mileage:,} km".replace(",", " ")
    return (
        f"| [{lot.title or lot.id}]({lot.url}) | {_access(lot)} | {mileage} | "
        f"{_euros(lot.starting_price)} | {_euros(lot.current_bid)} | {place}{outside} |"
    )


def _table(lots: Sequence[Lot]) -> list[str]:
    header = [
        "| Lot | Accès | Km | Mise à prix | Enchère | Retrait |",
        "|---|---|---|---|---|---|",
    ]
    body = [_row(lot) for lot in lots[:SECTION_LIMIT]]
    if len(lots) > SECTION_LIMIT:
        body.append(f"| … et {len(lots) - SECTION_LIMIT} autres | | | | | |")
    return header + body


def _section(title: str, lots: Sequence[Lot], empty: str) -> list[str]:
    lines = [f"## {title} ({len(lots)})", ""]
    lines.extend(_table(lots) if lots else [f"_{empty}_"])
    lines.append("")
    return lines


def _incomplete(lots: Iterable[Lot]) -> list[Lot]:
    return [lot for lot in lots if lot.is_incomplete]


def _scope_unknown(lots: Iterable[Lot]) -> list[Lot]:
    return [lot for lot in lots if lot.scope_unknown]


def _header(run: Run, incomplete: Sequence[Lot]) -> list[str]:
    """Title, counters, and the incompleteness warning when there is one."""
    lines = [
        f"# Enchères du Domaine — {run.timestamp:%d/%m/%Y %H:%M}",
        "",
        f"{run.sales_scanned} vente(s) balayée(s) · {run.lots_seen} lot(s) vu(s) · "
        f"**{run.lots_kept} retenu(s)** · {run.lots_rejected} écarté(s) · "
        f"{run.lots_scope_unknown} périmètre inconnu · {run.duration_seconds:.0f} s",
        "",
    ]
    if incomplete:
        lines += [
            f"> ⚠️ **{len(incomplete)} lot(s) incomplet(s)** : la mention "
            "« réservé aux professionnels » n'a pas pu être lue. Ces lots ne sont "
            "pas exploitables en l'état — voir `champs_manquants` dans le JSON.",
            "",
        ]
    return lines


def _rejected(rejected: Sequence[RejectedLot]) -> list[str]:
    """Breakdown of rejected lots by reason."""
    lines = [f"## Écartés ({len(rejected)})", ""]
    if not rejected:
        return [*lines, "_aucun lot écarté_", ""]
    counts: dict[str, int] = {}
    for lot in rejected:
        counts[lot.reason] = counts.get(lot.reason, 0) + 1
    lines += ["| Motif | Lots |", "|---|---|"]
    lines += [
        f"| {reason} | {count} |" for reason, count in sorted(counts.items(), key=lambda x: -x[1])
    ]
    return [*lines, ""]


def _errors(errors: Sequence[RunError]) -> list[str]:
    """Run anomalies, shown as they are."""
    lines = [f"## Erreurs du run ({len(errors)})", ""]
    if not errors:
        return [*lines, "_run sans erreur_", ""]
    lines += ["| Étape | Cible | Type | Message |", "|---|---|---|---|"]
    lines += [f"| {e.step} | {e.target} | {e.kind} | {e.message} |" for e in errors]
    return [*lines, ""]


def render(document: OutputDocument) -> str:
    """Compose the Markdown digest of a run."""
    lots = document.lots
    new = [lot for lot in lots if lot.new_since_last_run]
    moved = [lot for lot in lots if lot.bid_moved]
    trade_only = [lot for lot in lots if lot.trade_only is True]
    incomplete = _incomplete(lots)

    unknown_scope = _scope_unknown(lots)

    lines = _header(document.run, incomplete)
    lines += _section("Nouveaux lots", new, "aucun nouveau lot depuis le dernier run")
    lines += _section("Enchères qui ont bougé", moved, "aucun mouvement d'enchère")
    lines += _section(
        "Réservés aux professionnels", trade_only, "aucun lot réservé aux professionnels"
    )

    # A lot whose collection point could not be read is neither in nor out of
    # scope. Burying it would repeat the very failure this section exists to
    # prevent: sale 567 vanished from a whole scan that way.
    if unknown_scope:
        lines += _section("Périmètre indéterminé — à vérifier", unknown_scope, "")

    # Incomplete lots get their own table: counting them in the banner is not
    # enough, they must be individually reachable.
    if incomplete:
        lines += _section("Lots incomplets — à vérifier à la main", incomplete, "")

    lines += _rejected(document.rejected)
    lines += _errors(document.run.errors)
    return "\n".join(lines)
