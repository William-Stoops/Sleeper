"""Shared fixtures. No test touches the network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "api"


def load(name: str) -> dict[str, Any]:
    """Load a real API response, captured then stripped of personal data."""
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload


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
