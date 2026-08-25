"""Persistent state: new lots, bid movements, cache, history.

Idempotence is the most important property here: two consecutive runs with no
upstream change must raise no false "new lot" alert.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sleeper.state.store import LotObservation, SleeperState

T0 = datetime(2026, 8, 25, 4, 30, tzinfo=UTC)
T1 = T0 + timedelta(days=1)


@pytest.fixture
def state(tmp_path: Path) -> Iterator[SleeperState]:
    with SleeperState(tmp_path / "state.sqlite3") as opened:
        yield opened


def observe(
    state: SleeperState,
    *,
    lot_id: int = 1,
    bid: float | None = None,
    when: datetime = T0,
) -> LotObservation:
    return state.observe_lot(
        lot_id=lot_id,
        sale_id=467,
        url=f"https://exemple/lot/{lot_id}",
        title="DACIA DUSTER",
        trade_only=True,
        starting_price=1500.0,
        current_bid=bid,
        postcode="59000",
        department="59",
        timestamp=when,
    )


def record_sale(state: SleeperState, when: datetime = T0, title: str = "Vente") -> None:
    state.record_sale(
        sale_id=467,
        title=title,
        regional_directorate="LILLE",
        status=3,
        lot_count=161,
        opens_at=T0,
        closes_at=T0,
        timestamp=when,
    )


class TestMigrations:
    def test_creates_the_schema_and_records_its_version(self, tmp_path: Path) -> None:
        with SleeperState(tmp_path / "state.sqlite3") as state:
            assert state.schema_version() >= 1

    def test_reopening_an_existing_database_does_not_recreate_it(self, tmp_path: Path) -> None:
        path = tmp_path / "state.sqlite3"
        with SleeperState(path) as state:
            observe(state)
            version = state.schema_version()
        with SleeperState(path) as state:
            assert state.schema_version() == version
            assert observe(state, when=T1).is_new is False


class TestNewLotDetection:
    def test_a_never_seen_lot_is_new(self, state: SleeperState) -> None:
        assert observe(state).is_new is True

    def test_an_already_seen_lot_is_not(self, state: SleeperState) -> None:
        observe(state)
        assert observe(state, when=T1).is_new is False

    def test_two_identical_runs_raise_no_alert(self, state: SleeperState) -> None:
        observe(state, bid=900.0)
        second = observe(state, bid=900.0, when=T1)
        assert (second.is_new, second.bid_moved) == (False, False)


class TestBidMovement:
    def test_a_first_observed_bid_is_a_movement(self, state: SleeperState) -> None:
        observe(state, bid=None)
        assert observe(state, bid=900.0, when=T1).bid_moved is True

    def test_a_stable_bid_is_not_a_movement(self, state: SleeperState) -> None:
        observe(state, bid=900.0)
        assert observe(state, bid=900.0, when=T1).bid_moved is False

    def test_a_rising_bid_is_a_movement(self, state: SleeperState) -> None:
        observe(state, bid=900.0)
        assert observe(state, bid=1000.0, when=T1).bid_moved is True

    def test_a_fresh_lot_without_a_bid_does_not_move(self, state: SleeperState) -> None:
        assert observe(state, bid=None).bid_moved is False

    def test_the_history_only_keeps_changes(self, state: SleeperState) -> None:
        observe(state, bid=900.0)
        observe(state, bid=900.0, when=T1)
        observe(state, bid=1200.0, when=T1 + timedelta(days=1))
        assert [amount for _, amount in state.bid_history(1)] == [900.0, 1200.0]


class TestListingCache:
    def test_no_cache_returns_none(self, state: SleeperState) -> None:
        assert state.cached_listing(1, "fingerprint") is None

    def test_rereads_a_listing_with_an_identical_fingerprint(self, state: SleeperState) -> None:
        state.cache_listing(1, "f1", {"make": "DACIA"}, T0)
        assert state.cached_listing(1, "f1") == {"make": "DACIA"}

    def test_a_different_fingerprint_invalidates_the_cache(self, state: SleeperState) -> None:
        state.cache_listing(1, "f1", {"make": "DACIA"}, T0)
        assert state.cached_listing(1, "f2") is None

    def test_caching_twice_replaces(self, state: SleeperState) -> None:
        state.cache_listing(1, "f1", {"make": "DACIA"}, T0)
        state.cache_listing(1, "f2", {"make": "RENAULT"}, T1)
        assert state.cached_listing(1, "f2") == {"make": "RENAULT"}


class TestSalesAndHammerPrices:
    def test_records_then_closes_a_sale(self, state: SleeperState) -> None:
        record_sale(state, title="Vente du 27 août")
        state.close_absent_sales({999}, T1)
        assert state.closed_sales() == [467]

    def test_a_still_visible_sale_is_not_closed(self, state: SleeperState) -> None:
        record_sale(state)
        state.close_absent_sales({467}, T1)
        assert state.closed_sales() == []

    def test_keeps_the_hammer_price(self, state: SleeperState) -> None:
        observe(state, bid=900.0)
        state.record_hammer_price(1, 2400.0, 1500.0, T1)
        assert state.hammer_prices() == [(1, 2400.0, 1500.0)]

    def test_the_hammer_price_is_idempotent(self, state: SleeperState) -> None:
        observe(state)
        state.record_hammer_price(1, 2400.0, 1500.0, T0)
        state.record_hammer_price(1, 2400.0, 1500.0, T1)
        assert len(state.hammer_prices()) == 1


class TestProtectedClosure:
    def test_a_run_with_no_sale_at_all_closes_nothing(self, state: SleeperState) -> None:
        """Guard rail: an empty scan is far more likely an upstream failure."""
        record_sale(state)
        state.close_absent_sales(set(), T1)
        assert state.closed_sales() == []

    def test_a_reappearing_sale_is_reopened(self, state: SleeperState) -> None:
        record_sale(state)
        state.close_absent_sales({999}, T1)
        assert state.closed_sales() == [467]
        record_sale(state, when=T1)
        assert state.closed_sales() == []
