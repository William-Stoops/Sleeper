"""Translation of Magento API responses into typed objects.

This layer is where the upstream contract meets ours. It applies a strict
discipline:

* a missing STRUCTURAL field raises `UpstreamSchemaError` — that is a broken
  upstream contract, not missing data;
* a field that is present but unreadable feeds `unreadable_fields`, which
  surfaces in `champs_manquants` and then in `run.erreurs`;
* a field that is present and explicitly null stays null, quietly: that is a
  legitimate absence under the output contract.

Attributes carrying personal or banking data are dropped at read time: no
buying decision needs them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from sleeper.domain import text
from sleeper.domain.codes import SENSITIVE_ATTRIBUTES, to_bool
from sleeper.errors import UpstreamSchemaError

_MIN_YEAR: Final = 1900


@dataclass(frozen=True, slots=True)
class Pagination:
    """Pagination state returned by the source."""

    total_count: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class SaleSource:
    """A sale as the source describes it."""

    id: int
    title: str
    description: str
    status: int
    status_label: str
    type_label: str
    opens_at: datetime | None
    closes_at: datetime | None
    regional_directorate: str
    lot_count: int
    categories: tuple[str, ...]
    trade_only: bool | None
    #: Conditions of sale, when the source publishes them. Empty in practice:
    #: `auction_documents.conditions_of_sale.url_path` is null on every sale
    #: observed to date.
    conditions_text: str = ""


@dataclass(frozen=True, slots=True)
class LotSource:
    """A lot as the sale's lot list describes it."""

    id: int
    sku: str
    url_key: str
    number: str
    title: str
    sale_id: int
    trade_only: bool | None
    starting_price: float | None
    current_bid: float | None
    reserve_price: float | None
    #: Hammer price, published by the source once the lot has been sold.
    hammer_price: float | None
    status_label: str
    opens_at: datetime | None
    closes_at: datetime | None
    collection_city: str
    collection_postcode: str
    description: str
    regional_directorate: str
    unreadable_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VehicleAttributes:
    """Vehicle attributes of a lot listing."""

    make: str
    model: str
    fuel: str
    gearbox: str
    body_type: str
    kind: str
    mileage: int | None
    has_key: bool | None
    registration_certificate: bool | None
    roadworthiness_test: bool | None
    first_registration: str
    first_registration_year: int | None
    vat: str
    declared_end_of_life: bool | None
    non_compliant: bool | None
    re_registrable: bool | None
    odometer_altered: bool | None
    impounded: bool | None
    collection_city: str
    collection_postcode: str
    description: str
    raw_attributes: Mapping[str, str] = field(default_factory=dict)
    unreadable_fields: tuple[str, ...] = ()

    @property
    def is_a_vehicle(self) -> bool:
        """True when the listing carries at least one identifying vehicle attribute."""
        return bool(self.kind or self.make or self.model)


def _data_block(payload: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    """Open the GraphQL envelope, refusing to work on a failed response."""
    if errors := payload.get("errors"):
        first = errors[0].get("message", "sans message") if errors else "sans message"
        raise UpstreamSchemaError(path, f"erreur GraphQL renvoyée par la source : {first}")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise UpstreamSchemaError(path, "bloc « data » absent de la réponse")
    return data


def _require(source: Mapping[str, Any], key: str, path: str) -> Any:
    """Fetch a STRUCTURAL key. Its absence breaks the upstream contract."""
    if key not in source:
        raise UpstreamSchemaError(f"{path}.{key}", "champ structurant absent de la réponse")
    return source[key]


def _as_text(value: Any) -> str:
    """Return a clean string, never `None`: the output contract wants `\"\"`."""
    return "" if value is None else str(value).strip()


def _as_number(value: Any) -> float | None:
    """Convert an amount. An unreadable value means absence, not zero."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_number(value)
    return None if number is None else int(number)


def _as_datetime(value: Any) -> datetime | None:
    """Read an ISO 8601 timestamp. An unreadable value means absence."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _tolerant_bool(value: Any) -> bool | None:
    """Read an upstream boolean without ever raising: `None` when unreadable."""
    try:
        return to_bool(value)
    except ValueError:
        return None


def _pagination(block: Mapping[str, Any], path: str) -> Pagination:
    info = block.get("page_info") or {}
    return Pagination(
        total_count=int(_require(block, "total_count", path) or 0),
        total_pages=int(info.get("total_pages") or 0),
    )


def read_sales(payload: Mapping[str, Any]) -> tuple[tuple[SaleSource, ...], Pagination]:
    """Translate one page of the sales list."""
    path = "data.auctionsList"
    data = _data_block(payload, path)
    block = data.get("auctionsList")
    if not isinstance(block, Mapping):
        raise UpstreamSchemaError(path, "bloc absent : l'opération getAuctions a changé")
    items = _require(block, "items", path)
    if not isinstance(items, Sequence):
        raise UpstreamSchemaError(f"{path}.items", "liste attendue")
    sales = tuple(_sale(item, f"{path}.items[{i}]") for i, item in enumerate(items))
    return sales, _pagination(block, path)


def _sale(item: Mapping[str, Any], path: str) -> SaleSource:
    categories = tuple(
        _as_text(c.get("name")) for c in (item.get("categories") or []) if c.get("name")
    )
    return SaleSource(
        id=int(_require(item, "dnid_auction_id", path)),
        title=_as_text(item.get("name")),
        description=_as_text(item.get("description")),
        status=int(_require(item, "auction_auto_status", path)),
        status_label=_as_text(item.get("status_text")),
        type_label=_as_text(item.get("type_text")),
        opens_at=_as_datetime(item.get("start_date")),
        closes_at=_as_datetime(item.get("end_date")),
        regional_directorate=_as_text(item.get("sales_inspector_label")),
        lot_count=_as_int(item.get("auction_number_of_lots")) or 0,
        categories=categories,
        trade_only=_tolerant_bool(item.get("professional_only")),
    )


def read_lots(payload: Mapping[str, Any]) -> tuple[tuple[LotSource, ...], Pagination]:
    """Translate one page of a sale's lots."""
    path = "data.products"
    data = _data_block(payload, path)
    block = data.get("products")
    if not isinstance(block, Mapping):
        raise UpstreamSchemaError(path, "bloc absent : l'opération getAuctionLots a changé")
    items = _require(block, "items", path)
    if not isinstance(items, Sequence):
        raise UpstreamSchemaError(f"{path}.items", "liste attendue")
    lots = tuple(_lot(item, f"{path}.items[{i}]") for i, item in enumerate(items))
    return lots, _pagination(block, path)


def _lot(item: Mapping[str, Any], path: str) -> LotSource:
    # `professional_only` is the single most important field of this project:
    # its disappearance from the schema is a breakage, not missing data.
    raw_trade_only = _require(item, "professional_only", path)
    trade_only = _tolerant_bool(raw_trade_only)
    unreadable: list[str] = []
    if trade_only is None and raw_trade_only not in (None, ""):
        unreadable.append("reserve_aux_professionnels")

    collection = item.get("dropoff_location") or {}
    short = text.from_html((item.get("short_description") or {}).get("html"))
    long = text.from_html((item.get("description") or {}).get("html"))
    return LotSource(
        id=int(_require(item, "id", path)),
        sku=_as_text(item.get("sku")),
        url_key=_as_text(_require(item, "url_key", path)),
        number=_as_text(item.get("lot_number")),
        title=_as_text(item.get("name")),
        sale_id=int(_require(item, "auction", path)),
        trade_only=trade_only,
        starting_price=_as_number(_require(item, "price_auction", path)),
        current_bid=_as_number(item.get("last_bid")),
        reserve_price=_as_number(item.get("reserve_price")),
        hammer_price=_as_number(item.get("bid_winner_amount")),
        status_label=_as_text(item.get("lot_status_label")),
        opens_at=_as_datetime(item.get("start_date")),
        closes_at=_as_datetime(item.get("end_date")),
        collection_city=_as_text(collection.get("city")),
        collection_postcode=_as_text(collection.get("postcode")),
        description=" ".join(x for x in (short, long) if x),
        regional_directorate=_as_text((item.get("sales_inspector_data") or {}).get("cav_name")),
        unreadable_fields=tuple(unreadable),
    )


def _attribute_value(attribute: Mapping[str, Any]) -> str:
    """Return an attribute's value, whether typed in or picked from a list."""
    entered = (attribute.get("entered_attribute_value") or {}).get("value")
    if entered not in (None, ""):
        return _as_text(entered)
    options = (attribute.get("selected_attribute_options") or {}).get("attribute_option") or []
    return " / ".join(_as_text(o.get("label")) for o in options if o.get("label"))


def read_vehicle_attributes(payload: Mapping[str, Any]) -> VehicleAttributes:
    """Translate a lot's detailed listing into vehicle attributes."""
    path = "data.products.items[0]"
    data = _data_block(payload, path)
    block = data.get("products")
    if not isinstance(block, Mapping):
        raise UpstreamSchemaError(path, "bloc absent : l'opération getProductPageMain a changé")
    items = block.get("items")
    if not items:
        raise UpstreamSchemaError("data.products.items", "fiche vide : lot introuvable")
    item = items[0]

    raw = {
        a["attribute_metadata"]["code"]: _attribute_value(a)
        for a in (item.get("custom_attributes") or [])
        if a.get("attribute_metadata", {}).get("code") not in SENSITIVE_ATTRIBUTES
    }
    collection = item.get("dropoff_location") or item.get("dropoff_location_fo") or {}
    registration = raw.get("date_first_registration", "")
    unreadable = tuple(
        name
        for name, code in (("kilometrage", "vehicle_mileage"), ("cles", "vehicle_has_a_key"))
        if code in raw and _is_unreadable(raw[code], code)
    )
    return VehicleAttributes(
        make=raw.get("vehicle_brand", ""),
        model=raw.get("vehicle_model", ""),
        fuel=raw.get("vehicle_energy_type", ""),
        gearbox=raw.get("gearbox_type", ""),
        body_type=raw.get("body_type", ""),
        kind=raw.get("kind", ""),
        mileage=_as_int(raw.get("vehicle_mileage")),
        has_key=_tolerant_bool(raw.get("vehicle_has_a_key")),
        registration_certificate=_tolerant_bool(raw.get("registration_certificate")),
        roadworthiness_test=_tolerant_bool(raw.get("technical_control")),
        first_registration=registration[:10],
        first_registration_year=_year(registration),
        vat=raw.get("tax_class_id", ""),
        declared_end_of_life=_tolerant_bool(raw.get("vhu_declared")),
        non_compliant=_tolerant_bool(raw.get("not_conforme")),
        re_registrable=_tolerant_bool(raw.get("registrable_again")),
        odometer_altered=_tolerant_bool(raw.get("counter_change")),
        impounded=_tolerant_bool(raw.get("administrative_pound")),
        collection_city=_as_text(collection.get("city")),
        collection_postcode=_as_text(collection.get("postcode")),
        description=text.from_html((item.get("short_description") or {}).get("html")),
        raw_attributes=raw,
        unreadable_fields=unreadable,
    )


def _is_unreadable(value: str, code: str) -> bool:
    """Detect a value that is present but unusable for the target attribute."""
    if not value:
        return False
    if code == "vehicle_mileage":
        return _as_number(value) is None
    return _tolerant_bool(value) is None


def _year(timestamp: str) -> int | None:
    """Extract the year from a first-registration date."""
    date = _as_datetime(timestamp)
    if date is None or date.year < _MIN_YEAR:
        return None
    return date.year
