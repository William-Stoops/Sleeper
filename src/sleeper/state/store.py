"""Etat persistant sur SQLite.

Trois roles :

* distinguer les lots reellement nouveaux des lots deja vus ;
* suivre l'historique des encheres, lot par lot, sans bruit ;
* eviter de retelecharger une fiche inchangee.

Et un quatrieme, differe : constituer la serie historique qui permettra de
savoir a quel pourcentage de la mise a prix les lots partent reellement.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from sleeper.state.migrations import MIGRATIONS

_UPSERT_LOT = """
    INSERT INTO lot (id, vente_id, url, titre, reserve_aux_professionnels,
                     mise_a_prix, code_postal, departement,
                     vue_la_premiere_fois, vue_la_derniere_fois)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        vente_id = excluded.vente_id,
        url = excluded.url,
        titre = excluded.titre,
        reserve_aux_professionnels = excluded.reserve_aux_professionnels,
        mise_a_prix = excluded.mise_a_prix,
        code_postal = excluded.code_postal,
        departement = excluded.departement,
        vue_la_derniere_fois = excluded.vue_la_derniere_fois
"""


@dataclass(frozen=True, slots=True)
class ObservationLot:
    """Ce que l'etat sait dire d'un lot au moment ou on le revoit."""

    nouveau: bool
    enchere_a_bouge: bool
    enchere_precedente: float | None


class EtatSleeper:
    """Acces a la base d'etat. A utiliser comme gestionnaire de contexte."""

    def __init__(self, chemin: Path) -> None:
        self._chemin = chemin
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._cnx = sqlite3.connect(chemin, isolation_level=None)
        self._cnx.row_factory = sqlite3.Row
        self._cnx.execute("PRAGMA journal_mode = WAL")
        self._cnx.execute("PRAGMA foreign_keys = ON")
        self._migrer()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        type_exc: type[BaseException] | None,
        valeur: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.fermer()

    def fermer(self) -> None:
        self._cnx.close()

    # ------------------------------------------------------------------ schema

    def _migrer(self) -> None:
        self._cnx.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version INTEGER PRIMARY KEY, applique_le TEXT NOT NULL)"
        )
        courante = self.version_schema()
        for version, sql in MIGRATIONS:
            if version <= courante:
                continue
            with self._cnx:
                self._cnx.executescript(sql)
                self._cnx.execute(
                    "INSERT INTO schema_version (version, applique_le) VALUES (?, datetime('now'))",
                    (version,),
                )

    def version_schema(self) -> int:
        """Derniere migration appliquee. Zero sur une base neuve."""
        with closing(self._cnx.execute("SELECT MAX(version) AS v FROM schema_version")) as curseur:
            return int(curseur.fetchone()["v"] or 0)

    # ------------------------------------------------------------------- ventes

    def enregistrer_vente(
        self,
        *,
        vente_id: int,
        intitule: str,
        direction_regionale: str,
        statut: int,
        nb_lots: int,
        date_ouverture: datetime | None,
        date_cloture: datetime | None,
        horodatage: datetime,
    ) -> None:
        """Enregistre ou rafraichit une vente vue pendant ce run."""
        vu = horodatage.isoformat()
        with self._cnx:
            self._cnx.execute(
                """
                INSERT INTO vente (id, intitule, direction_regionale, statut, nb_lots,
                                   date_ouverture, date_cloture,
                                   vue_la_premiere_fois, vue_la_derniere_fois)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    intitule = excluded.intitule,
                    direction_regionale = excluded.direction_regionale,
                    statut = excluded.statut,
                    nb_lots = excluded.nb_lots,
                    date_ouverture = excluded.date_ouverture,
                    date_cloture = excluded.date_cloture,
                    vue_la_derniere_fois = excluded.vue_la_derniere_fois,
                    cloturee_le = NULL
                """,
                (
                    vente_id,
                    intitule,
                    direction_regionale,
                    statut,
                    nb_lots,
                    _iso(date_ouverture),
                    _iso(date_cloture),
                    vu,
                    vu,
                ),
            )

    def cloturer_ventes_absentes(self, vues: Iterable[int], horodatage: datetime) -> None:
        """Marque comme cloturees les ventes connues qui ne sont plus publiees.

        Un run qui n'a vu AUCUNE vente ne cloture rien. Le site publie en
        permanence des ventes ouvertes : un scan vide signale bien plus
        surement une panne amont qu'un catalogue reellement vide, et il ne doit
        pas se traduire par une cloture en masse de l'historique.
        """
        identifiants = tuple(vues)
        if not identifiants:
            return
        trous = ",".join("?" * len(identifiants))
        with self._cnx:
            self._cnx.execute(
                # `trous` n'est qu'une suite de « ? » derivee du nombre
                # d'identifiants : aucune donnee n'est interpolee ici.
                f"UPDATE vente SET cloturee_le = ? "
                f"WHERE cloturee_le IS NULL AND id NOT IN ({trous})",
                (horodatage.isoformat(), *identifiants),
            )

    def ventes_cloturees(self) -> list[int]:
        """Identifiants des ventes constatees cloturees."""
        with closing(
            self._cnx.execute("SELECT id FROM vente WHERE cloturee_le IS NOT NULL ORDER BY id")
        ) as curseur:
            return [int(ligne["id"]) for ligne in curseur]

    # ---------------------------------------------------------------------- lots

    def observer_lot(
        self,
        *,
        lot_id: int,
        vente_id: int,
        url: str,
        titre: str,
        reserve_aux_professionnels: bool | None,
        mise_a_prix: float | None,
        enchere_en_cours: float | None,
        code_postal: str,
        departement: str,
        horodatage: datetime,
    ) -> ObservationLot:
        """Consigne un lot et dit ce qui a change depuis la derniere fois."""
        vu = horodatage.isoformat()
        with closing(self._cnx.execute("SELECT id FROM lot WHERE id = ?", (lot_id,))) as curseur:
            nouveau = curseur.fetchone() is None

        precedente = self.derniere_enchere(lot_id)
        a_bouge = enchere_en_cours is not None and enchere_en_cours != precedente

        with self._cnx:
            self._cnx.execute(
                _UPSERT_LOT,
                (
                    lot_id,
                    vente_id,
                    url,
                    titre,
                    _booleen(reserve_aux_professionnels),
                    mise_a_prix,
                    code_postal,
                    departement,
                    vu,
                    vu,
                ),
            )
            # Une ligne d'historique n'est ecrite QUE si le montant a change :
            # c'est ce qui garantit qu'un run sans changement amont ne laisse
            # aucune trace et ne declenche aucune fausse alerte.
            if a_bouge:
                self._cnx.execute(
                    "INSERT OR REPLACE INTO enchere (lot_id, horodatage, montant) VALUES (?, ?, ?)",
                    (lot_id, vu, enchere_en_cours),
                )

        return ObservationLot(
            nouveau=nouveau, enchere_a_bouge=a_bouge, enchere_precedente=precedente
        )

    def derniere_enchere(self, lot_id: int) -> float | None:
        """Dernier montant d'enchere consigne pour ce lot."""
        with closing(
            self._cnx.execute(
                "SELECT montant FROM enchere WHERE lot_id = ? ORDER BY horodatage DESC LIMIT 1",
                (lot_id,),
            )
        ) as curseur:
            ligne = curseur.fetchone()
        return None if ligne is None or ligne["montant"] is None else float(ligne["montant"])

    def historique_encheres(self, lot_id: int) -> list[tuple[str, float]]:
        """Suite des montants constates, du plus ancien au plus recent."""
        with closing(
            self._cnx.execute(
                "SELECT horodatage, montant FROM enchere WHERE lot_id = ? ORDER BY horodatage",
                (lot_id,),
            )
        ) as curseur:
            return [(str(x["horodatage"]), float(x["montant"])) for x in curseur]

    def lots_connus(self, vente_id: int) -> set[int]:
        """Identifiants des lots deja enregistres pour une vente."""
        with closing(
            self._cnx.execute("SELECT id FROM lot WHERE vente_id = ?", (vente_id,))
        ) as curseur:
            return {int(ligne["id"]) for ligne in curseur}

    # ------------------------------------------------------------- adjudications

    def enregistrer_adjudication(
        self, lot_id: int, montant: float, mise_a_prix: float | None, horodatage: datetime
    ) -> None:
        """Consigne un prix d'adjudication devenu visible."""
        with self._cnx:
            self._cnx.execute(
                "INSERT INTO adjudication (lot_id, montant, mise_a_prix, constate_le) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(lot_id) DO UPDATE SET "
                "montant = excluded.montant, mise_a_prix = excluded.mise_a_prix",
                (lot_id, montant, mise_a_prix, horodatage.isoformat()),
            )

    def adjudications(self) -> list[tuple[int, float, float | None]]:
        """Adjudications connues : (lot, montant, mise a prix)."""
        with closing(
            self._cnx.execute(
                "SELECT lot_id, montant, mise_a_prix FROM adjudication ORDER BY lot_id"
            )
        ) as curseur:
            return [
                (
                    int(x["lot_id"]),
                    float(x["montant"]),
                    None if x["mise_a_prix"] is None else float(x["mise_a_prix"]),
                )
                for x in curseur
            ]

    # ---------------------------------------------------------------- cache fiche

    def fiche_en_cache(self, lot_id: int, empreinte: str) -> dict[str, Any] | None:
        """Fiche memorisee, si et seulement si son empreinte correspond."""
        with closing(
            self._cnx.execute(
                "SELECT empreinte, charge_utile FROM fiche_cache WHERE lot_id = ?", (lot_id,)
            )
        ) as curseur:
            ligne = curseur.fetchone()
        if ligne is None or ligne["empreinte"] != empreinte:
            return None
        charge: dict[str, Any] = json.loads(ligne["charge_utile"])
        return charge

    def memoriser_fiche(
        self, lot_id: int, empreinte: str, charge: Mapping[str, Any], horodatage: datetime
    ) -> None:
        """Memorise une fiche detaillee pour eviter de la retelecharger."""
        with self._cnx:
            self._cnx.execute(
                "INSERT INTO fiche_cache (lot_id, empreinte, charge_utile, mis_a_jour_le) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(lot_id) DO UPDATE SET "
                "empreinte = excluded.empreinte, charge_utile = excluded.charge_utile, "
                "mis_a_jour_le = excluded.mis_a_jour_le",
                (
                    lot_id,
                    empreinte,
                    json.dumps(dict(charge), ensure_ascii=False),
                    horodatage.isoformat(),
                ),
            )


def _iso(instant: datetime | None) -> str | None:
    return None if instant is None else instant.isoformat()


def _booleen(valeur: bool | None) -> int | None:
    return None if valeur is None else int(valeur)
