"""Shared fixtures. No test touches the network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sleeper.domain.inspection import Inspection
from sleeper.domain.models import Lot

FIXTURES = Path(__file__).parent / "fixtures" / "api"


def load(name: str) -> dict[str, Any]:
    """Load a real API response, captured then stripped of personal data."""
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload


def minimal_lot(**overrides: Any) -> Lot:
    base: dict[str, Any] = {
        "id": "1",
        "url": "https://exemple/lot/1",
        "sale_id": "467",
        "number": "1",
        "title": "DACIA DUSTER",
        "category": "Véhicules",
        "trade_only": True,
        "make": "DACIA",
        "model": "DUSTER",
        "variant": "",
        "first_registration": "2015-12-23",
        "mileage": 110430,
        "fuel": "Gazole",
        "gearbox": "Boîte manuelle",
        "tax_horsepower": 6,
        "vin": "",
        "crit_air": "",
        "inspection": Inspection(),
        "registration_certificate": True,
        "keys": True,
        "declared_condition": "",
        "starting_price": 1500.0,
        "current_bid": None,
        "bidder_count": None,
        "collection_place": "LILLE",
        "postcode": "59000",
        "department": "59",
        "viewing_dates": "",
        "buyer_fee_pct": None,
        "vat_reclaimable": None,
        "full_description": "",
        "scope": "dans",
        "new_since_last_run": True,
        "bid_moved": False,
        "missing_fields": [],
    }
    base.update(overrides)
    return Lot(**base)


@pytest.fixture
def sales_payload() -> dict[str, Any]:
    return load("auctions_list_page1.json")


@pytest.fixture
def lots_payload() -> dict[str, Any]:
    return load("auction_lots_467_page1.json")


@pytest.fixture
def listing_payload() -> dict[str, Any]:
    return load("product_main_dacia_duster.json")


@pytest.fixture
def bidding_payload() -> dict[str, Any]:
    return load("product_side_dacia_duster.json")
