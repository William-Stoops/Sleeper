"""Digest Markdown : ce qu'on lit le matin, en trente secondes.

Quatre questions, dans cet ordre d'interet : qu'est-ce qui est nouveau, sur
quoi les encheres ont bouge, quels lots sont reserves aux professionnels, et
qu'est-ce qui a mal tourne pendant le run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sleeper.domain.models import DocumentSortie, ErreurRun, Lot, LotEcarte, Run

#: Au-dela, le digest cesse d'etre lisible d'un coup d'oeil ; le JSON reste
#: la source complete.
LIMITE_PAR_SECTION = 40


def _euros(montant: float | None) -> str:
    return "—" if montant is None else f"{montant:,.0f} €".replace(",", " ")


def _mention_pro(lot: Lot) -> str:
    if lot.reserve_aux_professionnels is True:
        return "**PRO**"
    if lot.reserve_aux_professionnels is False:
        return "tous publics"
    return "⚠️ inconnu"


def _ligne(lot: Lot) -> str:
    lieu = f"{lot.departement or '??'} {lot.lieu_retrait}".strip()
    hors = " · *hors périmètre*" if lot.hors_perimetre else ""
    km = "—" if lot.kilometrage is None else f"{lot.kilometrage:,} km".replace(",", " ")
    return (
        f"| [{lot.titre or lot.id}]({lot.url}) | {_mention_pro(lot)} | {km} | "
        f"{_euros(lot.mise_a_prix)} | {_euros(lot.enchere_en_cours)} | {lieu}{hors} |"
    )


def _tableau(lots: Sequence[Lot]) -> list[str]:
    entete = [
        "| Lot | Accès | Km | Mise à prix | Enchère | Retrait |",
        "|---|---|---|---|---|---|",
    ]
    corps = [_ligne(lot) for lot in lots[:LIMITE_PAR_SECTION]]
    if len(lots) > LIMITE_PAR_SECTION:
        corps.append(f"| … et {len(lots) - LIMITE_PAR_SECTION} autres | | | | | |")
    return entete + corps


def _section(titre: str, lots: Sequence[Lot], vide: str) -> list[str]:
    lignes = [f"## {titre} ({len(lots)})", ""]
    lignes.extend(_tableau(lots) if lots else [f"_{vide}_"])
    lignes.append("")
    return lignes


def _incomplets(lots: Iterable[Lot]) -> list[Lot]:
    return [lot for lot in lots if lot.incomplet]


def _entete(run: Run, incomplets: Sequence[Lot]) -> list[str]:
    """Titre, compteurs, et avertissement d'incompletude s'il y a lieu."""
    lignes = [
        f"# Enchères du Domaine — {run.horodatage:%d/%m/%Y %H:%M}",
        "",
        f"{run.ventes_scannees} vente(s) balayée(s) · {run.lots_vus} lot(s) vu(s) · "
        f"**{run.lots_retenus} retenu(s)** · {run.lots_ecartes} écarté(s) · "
        f"{run.duree_secondes:.0f} s",
        "",
    ]
    if incomplets:
        lignes += [
            f"> ⚠️ **{len(incomplets)} lot(s) incomplet(s)** : la mention "
            "« réservé aux professionnels » n'a pas pu être lue. Ces lots ne sont "
            "pas exploitables en l'état — voir `champs_manquants` dans le JSON.",
            "",
        ]
    return lignes


def _ecartes(ecartes: Sequence[LotEcarte]) -> list[str]:
    """Repartition des lots ecartes par motif."""
    lignes = [f"## Écartés ({len(ecartes)})", ""]
    if not ecartes:
        return [*lignes, "_aucun lot écarté_", ""]
    compte: dict[str, int] = {}
    for ecarte in ecartes:
        compte[ecarte.motif] = compte.get(ecarte.motif, 0) + 1
    lignes += ["| Motif | Lots |", "|---|---|"]
    lignes += [
        f"| {motif} | {nombre} |" for motif, nombre in sorted(compte.items(), key=lambda x: -x[1])
    ]
    return [*lignes, ""]


def _erreurs(erreurs: Sequence[ErreurRun]) -> list[str]:
    """Anomalies du run, affichees telles quelles."""
    lignes = [f"## Erreurs du run ({len(erreurs)})", ""]
    if not erreurs:
        return [*lignes, "_run sans erreur_", ""]
    lignes += ["| Étape | Cible | Type | Message |", "|---|---|---|---|"]
    lignes += [f"| {e.etape} | {e.cible} | {e.type} | {e.message} |" for e in erreurs]
    return [*lignes, ""]


def rediger(document: DocumentSortie) -> str:
    """Compose le digest Markdown d'un run."""
    lots = document.lots
    nouveaux = [lot for lot in lots if lot.nouveau_depuis_dernier_run]
    bouges = [lot for lot in lots if lot.enchere_a_bouge]
    pros = [lot for lot in lots if lot.reserve_aux_professionnels is True]
    incomplets = _incomplets(lots)

    lignes = _entete(document.run, incomplets)
    lignes += _section("Nouveaux lots", nouveaux, "aucun nouveau lot depuis le dernier run")
    lignes += _section("Enchères qui ont bougé", bouges, "aucun mouvement d'enchère")
    lignes += _section("Réservés aux professionnels", pros, "aucun lot réservé aux professionnels")

    # Les lots incomplets ont leur propre tableau : les compter dans le bandeau
    # ne suffit pas, il faut pouvoir aller les regarder un par un.
    if incomplets:
        lignes += _section("Lots incomplets — à vérifier à la main", incomplets, "")

    lignes += _ecartes(document.ecartes)
    lignes += _erreurs(document.run.erreurs)
    return "\n".join(lignes)
