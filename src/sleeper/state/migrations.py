"""Migrations du schema d'etat.

Chaque migration est un couple (version, instructions SQL) applique une seule
fois, dans l'ordre, sous transaction. On n'edite jamais une migration deja
publiee : on en ajoute une.

L'historique des encheres a une valeur propre au-dela du run quotidien — il
doit permettre, dans six mois, de repondre a « a quel pourcentage de la mise
a prix les lots du Domaine partent-ils reellement ? ». Le schema est concu
pour cette question autant que pour la detection des nouveautes.
"""

from __future__ import annotations

from typing import Final

MIGRATIONS: Final[tuple[tuple[int, str], ...]] = (
    (
        1,
        """
        CREATE TABLE vente (
            id                   INTEGER PRIMARY KEY,
            intitule             TEXT    NOT NULL,
            direction_regionale  TEXT    NOT NULL,
            statut               INTEGER NOT NULL,
            nb_lots              INTEGER NOT NULL,
            date_ouverture       TEXT,
            date_cloture         TEXT,
            vue_la_premiere_fois TEXT    NOT NULL,
            vue_la_derniere_fois TEXT    NOT NULL,
            cloturee_le          TEXT
        );

        CREATE TABLE lot (
            id                         INTEGER PRIMARY KEY,
            vente_id                   INTEGER NOT NULL,
            url                        TEXT    NOT NULL,
            titre                      TEXT    NOT NULL,
            reserve_aux_professionnels INTEGER,
            mise_a_prix                REAL,
            code_postal                TEXT    NOT NULL DEFAULT '',
            departement                TEXT    NOT NULL DEFAULT '',
            vue_la_premiere_fois       TEXT    NOT NULL,
            vue_la_derniere_fois       TEXT    NOT NULL
        );
        CREATE INDEX idx_lot_vente ON lot (vente_id);
        CREATE INDEX idx_lot_departement ON lot (departement);

        -- Une ligne par CHANGEMENT d'enchere, pas une par execution : c'est
        -- ce qui rend deux runs identiques silencieux.
        CREATE TABLE enchere (
            lot_id     INTEGER NOT NULL,
            horodatage TEXT    NOT NULL,
            montant    REAL,
            PRIMARY KEY (lot_id, horodatage)
        );
        CREATE INDEX idx_enchere_lot ON enchere (lot_id, horodatage);

        CREATE TABLE adjudication (
            lot_id      INTEGER PRIMARY KEY,
            montant     REAL NOT NULL,
            mise_a_prix REAL,
            constate_le TEXT NOT NULL
        );

        -- Cache des fiches detaillees : les attributs vehicule ne changent
        -- pas, inutile de retelecharger une fiche inchangee.
        CREATE TABLE fiche_cache (
            lot_id        INTEGER PRIMARY KEY,
            empreinte     TEXT NOT NULL,
            charge_utile  TEXT NOT NULL,
            mis_a_jour_le TEXT NOT NULL
        );
        """,
    ),
)
