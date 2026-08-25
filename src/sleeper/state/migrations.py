"""State schema migrations.

Each migration is a (version, SQL) pair applied exactly once, in order, inside
a transaction. A published migration is never edited: another one is added.

Version 1 is the initial schema. It was rewritten once, before any real run,
to move table and column names to English; from the first production run
onwards the rule above applies without exception.

The bid history has value of its own beyond the daily run — in six months it
must answer "at what percentage of the starting price do Domaine lots actually
sell?". The schema is designed for that question as much as for detecting new
lots.
"""

from __future__ import annotations

from typing import Final

MIGRATIONS: Final[tuple[tuple[int, str], ...]] = (
    (
        1,
        """
        CREATE TABLE sale (
            id                    INTEGER PRIMARY KEY,
            title                 TEXT    NOT NULL,
            regional_directorate  TEXT    NOT NULL,
            status                INTEGER NOT NULL,
            lot_count             INTEGER NOT NULL,
            opens_at              TEXT,
            closes_at             TEXT,
            first_seen_at         TEXT    NOT NULL,
            last_seen_at          TEXT    NOT NULL,
            closed_at             TEXT
        );

        CREATE TABLE lot (
            id              INTEGER PRIMARY KEY,
            sale_id         INTEGER NOT NULL,
            url             TEXT    NOT NULL,
            title           TEXT    NOT NULL,
            trade_only      INTEGER,
            starting_price  REAL,
            postcode        TEXT    NOT NULL DEFAULT '',
            department      TEXT    NOT NULL DEFAULT '',
            first_seen_at   TEXT    NOT NULL,
            last_seen_at    TEXT    NOT NULL
        );
        CREATE INDEX idx_lot_sale ON lot (sale_id);
        CREATE INDEX idx_lot_department ON lot (department);

        -- One row per bid CHANGE, not one per run: that is what keeps two
        -- identical runs silent.
        CREATE TABLE bid (
            lot_id       INTEGER NOT NULL,
            recorded_at  TEXT    NOT NULL,
            amount       REAL,
            PRIMARY KEY (lot_id, recorded_at)
        );
        CREATE INDEX idx_bid_lot ON bid (lot_id, recorded_at);

        CREATE TABLE hammer_price (
            lot_id          INTEGER PRIMARY KEY,
            amount          REAL NOT NULL,
            starting_price  REAL,
            observed_at     TEXT NOT NULL
        );

        -- Cache of detailed listings: vehicle attributes do not change, so
        -- re-downloading an unchanged listing is pointless.
        CREATE TABLE listing_cache (
            lot_id       INTEGER PRIMARY KEY,
            fingerprint  TEXT NOT NULL,
            payload      TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        """,
    ),
)
