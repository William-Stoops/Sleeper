"""Persistent state on SQLite.

Three jobs:

* tell genuinely new lots apart from lots already seen;
* track the bid history, lot by lot, without noise;
* avoid re-downloading an unchanged listing.

And a fourth, deferred one: build the historical series that will show at what
percentage of the starting price lots actually sell.

`bid_history`, `closed_sales` and `hammer_prices` are the READ surface of that
series. The daily run does not use them — that is expected: it writes, it does
not read back. They exist for the downstream analysis system, they are covered
by tests, and they pin the read contract of the database.
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
    INSERT INTO lot (id, sale_id, url, title, trade_only, starting_price,
                     postcode, department, first_seen_at, last_seen_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        sale_id = excluded.sale_id,
        url = excluded.url,
        title = excluded.title,
        trade_only = excluded.trade_only,
        starting_price = excluded.starting_price,
        postcode = excluded.postcode,
        department = excluded.department,
        last_seen_at = excluded.last_seen_at
"""


@dataclass(frozen=True, slots=True)
class LotObservation:
    """What the state can say about a lot when it is seen again."""

    is_new: bool
    bid_moved: bool
    previous_bid: float | None


class SleeperState:
    """Access to the state database. Use as a context manager."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._cnx = sqlite3.connect(path, isolation_level=None)
        self._cnx.row_factory = sqlite3.Row
        self._cnx.execute("PRAGMA journal_mode = WAL")
        self._cnx.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._cnx.close()

    # ------------------------------------------------------------------ schema

    def _migrate(self) -> None:
        self._cnx.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        current = self.schema_version()
        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            with self._cnx:
                self._cnx.executescript(sql)
                self._cnx.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                    (version,),
                )

    def schema_version(self) -> int:
        """Last migration applied. Zero on a fresh database."""
        with closing(self._cnx.execute("SELECT MAX(version) AS v FROM schema_version")) as cursor:
            return int(cursor.fetchone()["v"] or 0)

    # ------------------------------------------------------------------- sales

    def record_sale(
        self,
        *,
        sale_id: int,
        title: str,
        regional_directorate: str,
        status: int,
        lot_count: int,
        opens_at: datetime | None,
        closes_at: datetime | None,
        timestamp: datetime,
    ) -> None:
        """Record or refresh a sale seen during this run."""
        seen = timestamp.isoformat()
        with self._cnx:
            self._cnx.execute(
                """
                INSERT INTO sale (id, title, regional_directorate, status, lot_count,
                                  opens_at, closes_at, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    regional_directorate = excluded.regional_directorate,
                    status = excluded.status,
                    lot_count = excluded.lot_count,
                    opens_at = excluded.opens_at,
                    closes_at = excluded.closes_at,
                    last_seen_at = excluded.last_seen_at,
                    closed_at = NULL
                """,
                (
                    sale_id,
                    title,
                    regional_directorate,
                    status,
                    lot_count,
                    _iso(opens_at),
                    _iso(closes_at),
                    seen,
                    seen,
                ),
            )

    def close_absent_sales(self, seen: Iterable[int], timestamp: datetime) -> None:
        """Mark known sales that are no longer published as closed.

        A run that saw NO sale closes nothing. The site permanently publishes
        open sales: an empty scan signals an upstream failure far more surely
        than a genuinely empty catalogue, and must not translate into a mass
        closure of the history.
        """
        identifiers = tuple(seen)
        if not identifiers:
            return
        # `holes` is only a run of "?" derived from the number of identifiers:
        # no data is interpolated here.
        holes = ",".join("?" * len(identifiers))
        with self._cnx:
            self._cnx.execute(
                f"UPDATE sale SET closed_at = ? WHERE closed_at IS NULL AND id NOT IN ({holes})",
                (timestamp.isoformat(), *identifiers),
            )

    def closed_sales(self) -> list[int]:
        """Identifiers of sales observed as closed."""
        with closing(
            self._cnx.execute("SELECT id FROM sale WHERE closed_at IS NOT NULL ORDER BY id")
        ) as cursor:
            return [int(row["id"]) for row in cursor]

    # ---------------------------------------------------------------------- lots

    def observe_lot(
        self,
        *,
        lot_id: int,
        sale_id: int,
        url: str,
        title: str,
        trade_only: bool | None,
        starting_price: float | None,
        current_bid: float | None,
        postcode: str,
        department: str,
        timestamp: datetime,
    ) -> LotObservation:
        """Record a lot and report what changed since last time."""
        seen = timestamp.isoformat()
        with closing(self._cnx.execute("SELECT id FROM lot WHERE id = ?", (lot_id,))) as cursor:
            is_new = cursor.fetchone() is None

        previous = self.last_bid(lot_id)
        moved = current_bid is not None and current_bid != previous

        with self._cnx:
            self._cnx.execute(
                _UPSERT_LOT,
                (
                    lot_id,
                    sale_id,
                    url,
                    title,
                    _as_int(trade_only),
                    starting_price,
                    postcode,
                    department,
                    seen,
                    seen,
                ),
            )
            # A history row is written ONLY when the amount changed: that is
            # what guarantees a run with no upstream change leaves no trace and
            # raises no false alert.
            if moved:
                self._cnx.execute(
                    "INSERT OR REPLACE INTO bid (lot_id, recorded_at, amount) VALUES (?, ?, ?)",
                    (lot_id, seen, current_bid),
                )

        return LotObservation(is_new=is_new, bid_moved=moved, previous_bid=previous)

    def last_bid(self, lot_id: int) -> float | None:
        """Last bid amount recorded for this lot."""
        with closing(
            self._cnx.execute(
                "SELECT amount FROM bid WHERE lot_id = ? ORDER BY recorded_at DESC LIMIT 1",
                (lot_id,),
            )
        ) as cursor:
            row = cursor.fetchone()
        return None if row is None or row["amount"] is None else float(row["amount"])

    def bid_history(self, lot_id: int) -> list[tuple[str, float]]:
        """Sequence of observed amounts, oldest first."""
        with closing(
            self._cnx.execute(
                "SELECT recorded_at, amount FROM bid WHERE lot_id = ? ORDER BY recorded_at",
                (lot_id,),
            )
        ) as cursor:
            return [(str(x["recorded_at"]), float(x["amount"])) for x in cursor]

    # ------------------------------------------------------------- hammer prices

    def record_hammer_price(
        self, lot_id: int, amount: float, starting_price: float | None, timestamp: datetime
    ) -> None:
        """Record a hammer price that has become visible."""
        with self._cnx:
            self._cnx.execute(
                "INSERT INTO hammer_price (lot_id, amount, starting_price, observed_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(lot_id) DO UPDATE SET "
                "amount = excluded.amount, starting_price = excluded.starting_price",
                (lot_id, amount, starting_price, timestamp.isoformat()),
            )

    def hammer_prices(self) -> list[tuple[int, float, float | None]]:
        """Known hammer prices: (lot, amount, starting price)."""
        with closing(
            self._cnx.execute(
                "SELECT lot_id, amount, starting_price FROM hammer_price ORDER BY lot_id"
            )
        ) as cursor:
            return [
                (
                    int(x["lot_id"]),
                    float(x["amount"]),
                    None if x["starting_price"] is None else float(x["starting_price"]),
                )
                for x in cursor
            ]

    # ---------------------------------------------------------------- listing cache

    def cached_listing(self, lot_id: int, fingerprint: str) -> dict[str, Any] | None:
        """Memorised listing, if and only if its fingerprint matches."""
        with closing(
            self._cnx.execute(
                "SELECT fingerprint, payload FROM listing_cache WHERE lot_id = ?", (lot_id,)
            )
        ) as cursor:
            row = cursor.fetchone()
        if row is None or row["fingerprint"] != fingerprint:
            return None
        cached: dict[str, Any] = json.loads(row["payload"])
        return cached

    def cache_listing(
        self, lot_id: int, fingerprint: str, payload: Mapping[str, Any], timestamp: datetime
    ) -> None:
        """Memorise a detailed listing so it is not downloaded again."""
        with self._cnx:
            self._cnx.execute(
                "INSERT INTO listing_cache (lot_id, fingerprint, payload, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(lot_id) DO UPDATE SET "
                "fingerprint = excluded.fingerprint, payload = excluded.payload, "
                "updated_at = excluded.updated_at",
                (
                    lot_id,
                    fingerprint,
                    json.dumps(dict(payload), ensure_ascii=False),
                    timestamp.isoformat(),
                ),
            )


def _iso(instant: datetime | None) -> str | None:
    return None if instant is None else instant.isoformat()


def _as_int(value: bool | None) -> int | None:
    return None if value is None else int(value)
