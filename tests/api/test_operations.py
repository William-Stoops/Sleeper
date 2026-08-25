"""GraphQL requests must stay identical to the application's own.

The site's web application firewall validates the shape of the parameters: a
forged request, even a semantically equivalent one, is rejected and followed
by an anti-bot challenge. This test is a guard rail, not a formality.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sleeper.api import operations

REFERENCE = json.loads(
    (Path(__file__).parent.parent / "fixtures/api/operations_reference.json").read_text(
        encoding="utf-8"
    )
)

MAPPINGS = {
    "SALES_LIST": "getAuctions",
    "SALE_HEADER": "getAuctionHeaderInfos",
    "SALE_LOTS": "getAuctionLots",
    "LOT_MAIN": "getProductPageMain",
    "LOT_BIDDING": "getProductPageSide",
}


@pytest.mark.parametrize(("constant", "operation"), MAPPINGS.items())
def test_request_is_identical_to_the_capture(constant: str, operation: str) -> None:
    assert getattr(operations, constant) == REFERENCE[operation]["query"]


@pytest.mark.parametrize(("constant", "operation"), MAPPINGS.items())
def test_operation_name_is_declared(constant: str, operation: str) -> None:
    assert operations.OPERATION_NAME[getattr(operations, constant)] == operation


def test_gateway_path() -> None:
    assert operations.GRAPHQL_PATH == "/gateway/magento/graphql/"
