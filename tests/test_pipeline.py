"""End-to-end test of the run, over the real captured payloads.

No network: a fake gateway replays the fixtures.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog

from sleeper.api import mapping, operations
from sleeper.config import Configuration, LoggingConfig, load_configuration
from sleeper.domain.models import OutputDocument
from sleeper.errors import AntiBotChallengeError, UpstreamSchemaError
from sleeper.logging_setup import configure as configure_logging
from sleeper.output import document
from sleeper.pipeline import Collector, _fingerprint
from sleeper.state.store import SleeperState
from tests.conftest import load

T0 = datetime(2026, 8, 25, 4, 30, tzinfo=UTC)


class FakeGateway:
    """Replays the fixtures and counts the calls, operation by operation."""

    def __init__(self, **overrides: dict[str, Any] | Exception) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responses: dict[str, dict[str, Any] | Exception] = {
            operations.SALES_LIST: _single_page(load("auctions_list_page1.json"), "auctionsList"),
            operations.SALE_LOTS: _single_page(load("auction_lots_467_page1.json"), "products"),
            operations.LOT_MAIN: load("product_main_dacia_duster.json"),
        }
        self._responses.update(overrides)

    def query(self, request: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append((operations.OPERATION_NAME.get(request, "?"), dict(variables)))
        response = self._responses.get(request)
        if response is None:
            raise AssertionError(f"opération non prévue par le test : {request[:60]}")
        if isinstance(response, Exception):
            raise response
        # The lots fixture belongs to sale 467: other sales answer empty, just
        # as the source would.
        if request is operations.SALE_LOTS:
            criteria: Any = variables.get("filter", {})
            requested = str(criteria.get("auction", {}).get("eq", ""))
            if requested != "467":
                return _no_lot()
        return copy.deepcopy(response)

    def count(self, operation: str) -> int:
        return sum(1 for name, _ in self.calls if name == operation)


def _no_lot() -> dict[str, Any]:
    return {"data": {"products": {"total_count": 0, "page_info": {"total_pages": 1}, "items": []}}}


def _single_page(payload: dict[str, Any], block: str) -> dict[str, Any]:
    """Reduce a paginated fixture to a single page, to bound the test."""
    copied = copy.deepcopy(payload)
    copied["data"][block]["page_info"]["total_pages"] = 1
    return copied


@pytest.fixture
def config(tmp_path: Path) -> Configuration:
    base = load_configuration(Path("config/default.toml"))
    return base.model_copy(
        update={
            "output": base.output.model_copy(update={"directory": tmp_path / "sorties"}),
            "state": base.state.model_copy(update={"database": tmp_path / "state.sqlite3"}),
        }
    )


def collect(config: Configuration, gateway: FakeGateway, when: datetime = T0) -> OutputDocument:
    """Run a collection with a frozen clock: the run duration is deterministic."""
    with SleeperState(config.state.database) as state:
        instants = iter([when, when + timedelta(seconds=12)])
        return Collector(config, gateway, state, clock=lambda: next(instants)).run()


class TestNominalRun:
    def test_only_keeps_vehicle_sales(self, config: Configuration) -> None:
        gateway = FakeGateway()
        result = collect(config, gateway)
        # The fixture holds 8 sales, one of which is a "Licence IV" with no vehicles.
        assert result.run.sales_scanned < 8
        assert all("Licence IV" not in sale.title for sale in result.sales)

    def test_produces_a_document_conforming_to_its_schema(self, config: Configuration) -> None:
        document.validate(collect(config, FakeGateway()))

    def test_the_sale_carries_its_regional_directorate(self, config: Configuration) -> None:
        """`dnid` porte la direction régionale, seule information de la source
        qui serait sinon perdue — la remplir avec l'id ne ferait que dupliquer
        le champ `id`."""
        result = collect(config, FakeGateway())
        sale = next(s for s in result.sales if s.id == "467")
        assert sale.dnid == "LA REUNION"
        assert sale.dnid != sale.id

    def test_reads_the_trade_only_mention(self, config: Configuration) -> None:
        result = collect(config, FakeGateway())
        kept = [lot for lot in result.lots if lot.sale_id == "467"]
        assert kept
        assert all(lot.trade_only is True for lot in kept)

    def test_flags_out_of_scope_lots_without_dropping_them(self, config: Configuration) -> None:
        result = collect(config, FakeGateway())
        reunion = [lot for lot in result.lots if lot.department == "974"]
        assert reunion, "les lots de La Réunion doivent être conservés"
        assert all(lot.out_of_scope for lot in reunion)

    def test_fills_in_the_vehicle_attributes(self, config: Configuration) -> None:
        result = collect(config, FakeGateway())
        lot = next(lot for lot in result.lots if lot.id == "267804")
        assert (lot.make, lot.model, lot.fuel) == ("DACIA", "DUSTER", "Gazole")
        assert lot.mileage == 110430
        assert lot.registration_certificate is True
        assert lot.keys is True
        assert lot.vin == "UU1HSDJ9G53808834"
        assert lot.tax_horsepower == 6

    def test_keeps_the_source_description_verbatim(self, config: Configuration) -> None:
        result = collect(config, FakeGateway())
        lot = next(lot for lot in result.lots if lot.id == "267804")
        assert lot.full_description.startswith("Lot réservé aux professionnels")
        assert "<" not in lot.full_description

    def test_the_viewing_dates_carry_no_personal_data(self, config: Configuration) -> None:
        result = collect(config, FakeGateway())
        lot = next(lot for lot in result.lots if lot.id == "267804")
        assert lot.viewing_dates == "Mercredi 29/07/2026 de 08h00 à 11h00"

    def test_the_run_duration_is_measured(self, config: Configuration) -> None:
        assert collect(config, FakeGateway()).run.duration_seconds == 12.0

    def test_the_counters_are_consistent(self, config: Configuration) -> None:
        result = collect(config, FakeGateway())
        assert result.run.lots_seen == result.run.lots_kept + result.run.lots_rejected
        assert len(result.lots) == result.run.lots_kept
        assert len(result.rejected) == result.run.lots_rejected


class TestIdempotence:
    def test_the_first_run_declares_everything_new(self, config: Configuration) -> None:
        result = collect(config, FakeGateway())
        assert all(lot.new_since_last_run for lot in result.lots)

    def test_a_second_identical_run_reports_nothing_new(self, config: Configuration) -> None:
        collect(config, FakeGateway())
        second = collect(config, FakeGateway(), T0 + timedelta(days=1))
        assert not any(lot.new_since_last_run for lot in second.lots)
        assert not any(lot.bid_moved for lot in second.lots)

    def test_a_rising_bid_is_reported(self, config: Configuration) -> None:
        collect(config, FakeGateway())
        risen = _single_page(load("auction_lots_467_page1.json"), "products")
        risen["data"]["products"]["items"][0]["last_bid"] = 3000
        gateway = FakeGateway(**{operations.SALE_LOTS: risen})
        second = collect(config, gateway, T0 + timedelta(days=1))
        moved = [lot for lot in second.lots if lot.bid_moved]
        assert [lot.current_bid for lot in moved] == [3000.0]


class TestCache:
    def test_the_listing_is_downloaded_only_once(self, config: Configuration) -> None:
        first = FakeGateway()
        collect(config, first)
        second = FakeGateway()
        collect(config, second, T0 + timedelta(days=1))
        assert first.count("getProductPageMain") > 0
        assert second.count("getProductPageMain") == 0

    def test_a_cache_written_by_an_earlier_version_is_refetched(
        self, config: Configuration
    ) -> None:
        """Guard rail: an incompatible cache must not bring the run down."""
        collect(config, FakeGateway())

        # Replace each memorised listing with an obsolete shape, under its
        # current fingerprint — exactly what an earlier model would leave.
        lots, _ = mapping.read_lots(load("auction_lots_467_page1.json"))
        with SleeperState(config.state.database) as state:
            for raw in lots:
                state.cache_listing(raw.id, _fingerprint(raw), {"gone_field": 1}, T0)

        gateway = FakeGateway()
        result = collect(config, gateway, T0 + timedelta(days=1))
        assert gateway.count("getProductPageMain") == len(lots)
        assert result.lots
        assert all(lot.make == "DACIA" for lot in result.lots)


class TestErrorHandling:
    def test_an_upstream_breakage_on_lots_does_not_cancel_the_run(
        self, config: Configuration
    ) -> None:
        gateway = FakeGateway(**{operations.SALE_LOTS: {"data": {"products": {"total_count": 0}}}})
        result = collect(config, gateway)
        assert result.run.errors
        assert result.run.errors[0].kind == UpstreamSchemaError.__name__
        assert result.run.sales_scanned > 0

    def test_an_anti_bot_challenge_interrupts_everything(self, config: Configuration) -> None:
        gateway = FakeGateway(**{operations.SALE_LOTS: AntiBotChallengeError("captcha")})
        with pytest.raises(AntiBotChallengeError):
            collect(config, gateway)

    def test_a_lot_without_a_readable_trade_flag_is_reported_incomplete(
        self, config: Configuration
    ) -> None:
        damaged = _single_page(load("auction_lots_467_page1.json"), "products")
        damaged["data"]["products"]["items"][0]["professional_only"] = "peut-être"
        gateway = FakeGateway(**{operations.SALE_LOTS: damaged})
        result = collect(config, gateway)
        incomplete = [lot for lot in result.lots if lot.is_incomplete]
        assert len(incomplete) == 1
        assert incomplete[0].trade_only is None
        assert any(e.kind == "ChampCritiqueIllisible" for e in result.run.errors)


class TestHammerPriceHistory:
    """The historical series that will yield the price / starting-price ratio."""

    def _with_hammer_price(self, amount: float) -> dict[str, Any]:
        payload = _single_page(load("auction_lots_467_page1.json"), "products")
        payload["data"]["products"]["items"][0]["bid_winner_amount"] = amount
        return payload

    def test_records_the_price_as_soon_as_it_becomes_visible(self, config: Configuration) -> None:
        gateway = FakeGateway(**{operations.SALE_LOTS: self._with_hammer_price(2400)})
        collect(config, gateway)
        with SleeperState(config.state.database) as state:
            assert state.hammer_prices() == [(267804, 2400.0, 1500.0)]

    def test_stays_idempotent_from_one_run_to_the_next(self, config: Configuration) -> None:
        payload = self._with_hammer_price(2400)
        collect(config, FakeGateway(**{operations.SALE_LOTS: payload}))
        collect(
            config,
            FakeGateway(**{operations.SALE_LOTS: payload}),
            T0 + timedelta(days=1),
        )
        with SleeperState(config.state.database) as state:
            assert len(state.hammer_prices()) == 1

    def test_a_rejected_lot_still_feeds_the_series(self, config: Configuration) -> None:
        """La série décrit le marché, pas notre présélection : un lot écarté
        par une règle métier doit tout de même y figurer."""
        payload = self._with_hammer_price(2400)
        # Ce lot serait écarté : aucun attribut véhicule ne le concerne, et sa
        # description ne porte aucun kilométrage.
        payload["data"]["products"]["items"][0]["short_description"] = {
            "html": "<p>Canapé d'angle en cuir</p>"
        }
        gateway = FakeGateway(
            **{
                operations.SALE_LOTS: payload,
                operations.LOT_MAIN: {"data": {"products": {"items": [{"custom_attributes": []}]}}},
            }
        )
        result = collect(config, gateway)
        assert any(lot.id == "267804" for lot in result.rejected)
        with SleeperState(config.state.database) as state:
            assert state.hammer_prices() == [(267804, 2400.0, 1500.0)]

    def test_no_hammer_price_while_nothing_is_sold(self, config: Configuration) -> None:
        collect(config, FakeGateway())
        with SleeperState(config.state.database) as state:
            assert state.hammer_prices() == []


class TestProgressReporting:
    """A half-hour run must not stay silent: the operator cannot tell work
    from a hang."""

    @pytest.fixture
    def events(self, config: Configuration, capsys: pytest.CaptureFixture[str]) -> str:
        """Run a collection with logging routed to the error stream."""
        configure_logging(LoggingConfig(level="INFO", format="json"))
        try:
            collect(config, FakeGateway())
            return capsys.readouterr().err
        finally:
            structlog.reset_defaults()
            logging.basicConfig(force=True)

    def test_each_sale_is_announced_and_summarised(self, events: str) -> None:
        assert "sale.starting" in events
        assert "sale.finished" in events

    def test_listing_downloads_emit_a_heartbeat(self, events: str) -> None:
        # 8 lots in the fixture: the final beat must fire even below the step.
        assert "listings.progress" in events

    def test_lot_pagination_is_reported(self, events: str) -> None:
        assert "lots.listing" in events
