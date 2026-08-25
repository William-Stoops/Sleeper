"""Translation of API responses into typed objects.

Cardinal rule: when a structural field disappears from the source, we fail
loudly. A scraper silently returning `null` would have a buying decision made
on incomplete data.
"""

from __future__ import annotations

from typing import Any

import pytest

from sleeper.api import mapping
from sleeper.errors import UpstreamSchemaError


class TestReadSales:
    def test_reads_the_pagination(self, sales_payload: dict[str, Any]) -> None:
        _, pagination = mapping.read_sales(sales_payload)
        assert pagination.total_count == 11
        assert pagination.total_pages == 2

    def test_reads_the_sales(self, sales_payload: dict[str, Any]) -> None:
        sales, _ = mapping.read_sales(sales_payload)
        assert len(sales) == 8
        first = sales[0]
        assert first.id == 467
        assert first.regional_directorate == "LA REUNION"
        assert first.lot_count == 161
        assert "Véhicules" in first.categories
        assert first.status == 3

    def test_absorbs_professional_only_as_a_string(self, sales_payload: dict[str, Any]) -> None:
        # At sale level the API returns "0"/"1"; at lot level, 0/1.
        sales, _ = mapping.read_sales(sales_payload)
        assert {s.trade_only for s in sales} == {True, False}

    def test_reads_dates_as_aware_datetimes(self, sales_payload: dict[str, Any]) -> None:
        sales, _ = mapping.read_sales(sales_payload)
        assert sales[0].closes_at is not None
        assert sales[0].closes_at.tzinfo is not None

    def test_a_graphql_error_is_terminal(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="erreur GraphQL"):
            mapping.read_sales({"errors": [{"message": "Cannot query field"}]})

    def test_a_missing_block_is_terminal(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="auctionsList"):
            mapping.read_sales({"data": {}})

    def test_missing_items_is_terminal(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="items"):
            mapping.read_sales({"data": {"auctionsList": {"total_count": 0}}})


class TestReadLots:
    def test_reads_the_pagination(self, lots_payload: dict[str, Any]) -> None:
        _, pagination = mapping.read_lots(lots_payload)
        assert pagination.total_count == 161
        assert pagination.total_pages == 21

    def test_reads_the_decisive_fields(self, lots_payload: dict[str, Any]) -> None:
        lots, _ = mapping.read_lots(lots_payload)
        first = lots[0]
        assert first.id == 267804
        assert first.url_key == "daciadustersecteurest-1"
        assert first.trade_only is True
        assert first.starting_price == 1500
        assert first.collection_postcode == "97470"
        assert first.collection_city == "SAINT-BENOIT"
        assert first.sale_id == 467

    def test_a_missing_current_bid_stays_null(self, lots_payload: dict[str, Any]) -> None:
        lots, _ = mapping.read_lots(lots_payload)
        assert lots[0].current_bid is None

    def test_a_present_current_bid_is_read(self, lots_payload: dict[str, Any]) -> None:
        lots, _ = mapping.read_lots(lots_payload)
        with_bid = [lot for lot in lots if lot.current_bid is not None]
        assert {lot.current_bid for lot in with_bid} == {2000.0, 900.0}

    def test_the_description_is_stripped_of_html(self, lots_payload: dict[str, Any]) -> None:
        lots, _ = mapping.read_lots(lots_payload)
        assert "<p>" not in lots[0].description
        assert lots[0].description.startswith("Lot réservé aux professionnels")

    def test_an_unreadable_trade_only_feeds_the_anomalies(self) -> None:
        payload = _lots_payload(_raw_lot(professional_only="peut-etre"))
        lots, _ = mapping.read_lots(payload)
        assert lots[0].trade_only is None
        assert "reserve_aux_professionnels" in lots[0].unreadable_fields

    def test_a_missing_trade_only_is_terminal(self) -> None:
        raw = _raw_lot()
        del raw["professional_only"]
        with pytest.raises(UpstreamSchemaError, match="professional_only"):
            mapping.read_lots(_lots_payload(raw))


class TestHammerPrice:
    def test_absent_while_the_lot_is_unsold(self, lots_payload: dict[str, Any]) -> None:
        lots, _ = mapping.read_lots(lots_payload)
        assert all(lot.hammer_price is None for lot in lots)

    def test_read_as_soon_as_it_appears(self) -> None:
        lots, _ = mapping.read_lots(_lots_payload(_raw_lot(bid_winner_amount=2400)))
        assert lots[0].hammer_price == 2400.0


class TestReadVehicleAttributes:
    def test_reads_the_structured_attributes(self, listing_payload: dict[str, Any]) -> None:
        attributes = mapping.read_vehicle_attributes(listing_payload)
        assert attributes.make == "DACIA"
        assert attributes.model == "DUSTER"
        assert attributes.fuel == "Gazole"
        assert attributes.gearbox == "Boîte manuelle"
        assert attributes.kind == "VP"
        assert attributes.mileage == 110430
        assert attributes.has_key is True
        assert attributes.registration_certificate is True
        assert attributes.roadworthiness_test is False
        assert attributes.first_registration_year == 2015
        assert attributes.first_registration == "2015-12-23"

    def test_reports_the_detailed_collection_point(self, listing_payload: dict[str, Any]) -> None:
        attributes = mapping.read_vehicle_attributes(listing_payload)
        assert attributes.collection_postcode == "97470"
        assert attributes.collection_city == "SAINT-BENOIT"

    def test_exposes_no_sensitive_attribute(self, listing_payload: dict[str, Any]) -> None:
        attributes = mapping.read_vehicle_attributes(listing_payload)
        assert "biciban" not in attributes.raw_attributes
        assert "contact_dropoff_location_id" not in attributes.raw_attributes

    def test_recognises_a_vehicle(self, listing_payload: dict[str, Any]) -> None:
        assert mapping.read_vehicle_attributes(listing_payload).is_a_vehicle is True

    def test_an_empty_product_is_terminal(self) -> None:
        with pytest.raises(UpstreamSchemaError, match="items"):
            mapping.read_vehicle_attributes({"data": {"products": {"items": []}}})


def _lots_payload(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": {
            "products": {
                "total_count": len(items),
                "page_info": {"total_pages": 1},
                "items": list(items),
            }
        }
    }


def _raw_lot(**overrides: Any) -> dict[str, Any]:
    """A minimal lot item conforming to the upstream schema."""
    base: dict[str, Any] = {
        "id": 1,
        "sku": "SKU1",
        "url_key": "un-lot-1",
        "lot_number": 1,
        "name": "UN LOT",
        "auction": 467,
        "professional_only": 1,
        "price_auction": 100,
        "last_bid": None,
        "reserve_price": None,
        "bid_winner_amount": None,
        "lot_status_label": "Vente en cours",
        "start_date": None,
        "end_date": None,
        "dropoff_location": {"city": "LILLE", "postcode": "59000"},
        "short_description": {"html": "<p>Un lot</p>"},
        "description": {"html": ""},
        "sales_inspector_data": {"cav_name": "LILLE"},
    }
    base.update(overrides)
    return base
