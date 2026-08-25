"""Orchestration of a run.

The flow is linear and deliberately readable:

    open sales -> lots of each sale -> detailed listing (when needed)
    -> exclusion rules -> scope -> state -> document

Three principles govern error handling:

* an anomaly on ONE lot does not interrupt the run, but it is recorded in
  `run.erreurs` — never swallowed;
* a broken upstream contract on one sale interrupts that sale, not the others,
  and surfaces the same way;
* an anti-bot challenge interrupts the WHOLE run, with no retry: insisting
  would amount to trying to get around it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from sleeper.api import mapping, operations
from sleeper.api.mapping import LotSource, SaleSource, VehicleAttributes
from sleeper.config import Configuration
from sleeper.domain import text
from sleeper.domain.exclusions import ExclusionEngine, LotSignals
from sleeper.domain.models import (
    CRITICAL_FIELD,
    Lot,
    OutputDocument,
    RejectedLot,
    Run,
    RunError,
    Sale,
)
from sleeper.domain.territory import Perimeter, department_from_postcode
from sleeper.errors import AntiBotChallengeError, SleeperError
from sleeper.state.store import SleeperState

_LOG = structlog.get_logger(__name__)

#: Safety net: a sale should never exceed this order of magnitude. Beyond it,
#: we suspect pagination that never terminates.
MAX_PAGES = 200


class GraphQLGateway(Protocol):
    """What the pipeline needs, and nothing more.

    The pipeline knows nothing of browsers, cookies or retries: it sends an
    operation, it receives a payload. That is what makes it entirely
    replayable over fixtures.
    """

    def query(self, request: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Run a GraphQL operation and return its payload."""
        ...


@dataclass(slots=True)
class Counters:
    """What was seen, kept, rejected — and why."""

    sales_scanned: int = 0
    lots_seen: int = 0
    lots_kept: int = 0
    lots_rejected: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.lots_rejected += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


class Collector:
    """Runs a full sweep and returns the output document."""

    def __init__(
        self,
        config: Configuration,
        gateway: GraphQLGateway,
        state: SleeperState,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._state = state
        # A single source of time: injectable, so the run is reproducible in
        # tests without freezing the process clock.
        self._clock = clock or (lambda: datetime.now(UTC))
        self._started_at = self._clock()
        self._perimeter: Perimeter = config.perimeter()
        self._exclusions: ExclusionEngine = config.exclusion_engine()
        self._counters = Counters()
        self._errors: list[RunError] = []

    # ------------------------------------------------------------------ public

    def run(self) -> OutputDocument:
        """Sweep the open sales and compose the run document."""
        sales: list[Sale] = []
        lots: list[Lot] = []
        rejected: list[RejectedLot] = []
        seen: set[int] = set()

        for source in self._vehicle_sales():
            seen.add(source.id)
            self._counters.sales_scanned += 1
            kept, dropped = self._process_sale(source)
            lots.extend(kept)
            rejected.extend(dropped)
            sales.append(self._sale(source, kept, dropped))

        self._state.close_absent_sales(seen, self._started_at)
        return self._document(sales, lots, rejected)

    # ------------------------------------------------------------------- sales

    def _vehicle_sales(self) -> Iterator[SaleSource]:
        """Open sales that carry the vehicle category."""
        target = self._config.filters.vehicle_category
        statuses = [str(s) for s in self._config.filters.sale_statuses]
        for page in range(1, MAX_PAGES + 1):
            variables = {
                "currentPage": page,
                "pageSize": self._config.filters.page_size,
                "sort": {"end_date": "ASC"},
                "filter": {"auction_auto_status": {"in": statuses}},
            }
            payload = self._gateway.query(operations.SALES_LIST, variables)
            sales, pagination = mapping.read_sales(payload)
            for sale in sales:
                if target in sale.categories:
                    yield sale
                else:
                    _LOG.debug("sale.skipped", sale=sale.id, categories=sale.categories)
            if page >= max(pagination.total_pages, 1):
                return

    def _process_sale(self, source: SaleSource) -> tuple[list[Lot], list[RejectedLot]]:
        """Process every lot of a sale. An upstream breakage stops this sale only."""
        self._state.record_sale(
            sale_id=source.id,
            title=source.title,
            regional_directorate=source.regional_directorate,
            status=source.status,
            lot_count=source.lot_count,
            opens_at=source.opens_at,
            closes_at=source.closes_at,
            timestamp=self._started_at,
        )
        try:
            raw_lots = list(self._sale_lots(source.id))
        except AntiBotChallengeError:
            raise
        except SleeperError as exc:
            self._record_anomaly("lots", f"vente {source.id}", exc)
            return [], []

        listings = self._listings(raw_lots)
        kept: list[Lot] = []
        rejected: list[RejectedLot] = []
        for raw in raw_lots:
            self._counters.lots_seen += 1
            outcome = self._process_lot(raw, listings.get(raw.id))
            if isinstance(outcome, RejectedLot):
                rejected.append(outcome)
            else:
                kept.append(outcome)
        return kept, rejected

    def _sale_lots(self, sale_id: int) -> Iterator[LotSource]:
        """Walk the pages of a sale's lots."""
        for page in range(1, MAX_PAGES + 1):
            variables = {
                "currentPage": page,
                "pageSize": self._config.filters.page_size,
                "sort": {"lot_number": "ASC"},
                "filter": {"auction": {"eq": str(sale_id)}},
            }
            payload = self._gateway.query(operations.SALE_LOTS, variables)
            lots, pagination = mapping.read_lots(payload)
            yield from lots
            if page >= max(pagination.total_pages, 1):
                return

    # ---------------------------------------------------------------- listings

    def _listings(self, raw_lots: list[LotSource]) -> dict[int, VehicleAttributes]:
        """Fetch the missing detailed listings, honouring the pacing."""
        found: dict[int, VehicleAttributes] = {}
        to_fetch: list[LotSource] = []

        for raw in raw_lots:
            attributes = self._from_cache(raw)
            if attributes is None:
                to_fetch.append(raw)
            else:
                found[raw.id] = attributes

        if to_fetch:
            _LOG.info("listings.fetching", to_fetch=len(to_fetch), cached=len(found))
        # Sequential, deliberately. The transport is a browser, whose
        # synchronous API is single-threaded; and behind a shared rate limiter
        # concurrency buys nothing anyway — the limiter would serialise the
        # requests regardless. Politeness is enforced by the delay, which is a
        # stricter guarantee than a cap on simultaneous requests.
        for raw in to_fetch:
            attributes = self._listing(raw)
            if attributes is None:
                continue
            found[raw.id] = attributes
            self._state.cache_listing(
                raw.id, _fingerprint(raw), _to_memo(attributes), self._started_at
            )
        return found

    def _from_cache(self, raw: LotSource) -> VehicleAttributes | None:
        """Memorised and still usable listing, `None` when it must be refetched."""
        memo = self._state.cached_listing(raw.id, _fingerprint(raw))
        if memo is None:
            return None
        attributes = _from_memo(memo)
        if attributes is None:
            # Cache written by an earlier version of the model: treat it as
            # absent rather than bringing the run down.
            _LOG.warning("listing.stale_cache", lot=raw.id)
        return attributes

    def _listing(self, raw: LotSource) -> VehicleAttributes | None:
        """Download one listing. A single failure does not fell the run."""
        try:
            payload = self._gateway.query(operations.LOT_MAIN, {"urlKey": raw.url_key})
            return mapping.read_vehicle_attributes(payload)
        except AntiBotChallengeError:
            raise
        except SleeperError as exc:
            self._record_anomaly("fiche", f"lot {raw.id}", exc)
            return None

    # -------------------------------------------------------------------- lots

    def _process_lot(
        self, raw: LotSource, attributes: VehicleAttributes | None
    ) -> Lot | RejectedLot:
        """Apply the business rules to a lot and turn it into output."""
        signals = _signals(raw, attributes)
        if reason := self._exclusions.reason(signals):
            self._counters.reject(reason)
            _LOG.debug("lot.rejected", lot=raw.id, reason=reason)
            return RejectedLot(
                id=str(raw.id),
                url=_lot_url(self._config, raw),
                title=raw.title,
                reason=reason,
            )

        self._record_hammer_price(raw)
        observation = self._state.observe_lot(
            lot_id=raw.id,
            sale_id=raw.sale_id,
            url=_lot_url(self._config, raw),
            title=raw.title,
            trade_only=raw.trade_only,
            starting_price=raw.starting_price,
            current_bid=raw.current_bid,
            postcode=raw.collection_postcode,
            department=department_from_postcode(raw.collection_postcode) or "",
            timestamp=self._started_at,
        )
        lot = _build_lot(
            config=self._config,
            raw=raw,
            attributes=attributes,
            perimeter=self._perimeter,
            is_new=observation.is_new,
            bid_moved=observation.bid_moved,
        )
        if CRITICAL_FIELD in lot.missing_fields:
            self._flag_incomplete(raw.id)
        self._counters.lots_kept += 1
        return lot

    def _record_hammer_price(self, raw: LotSource) -> None:
        """Record the hammer price as soon as it becomes visible.

        This is the datum that, in six months, will tell at what percentage of
        the starting price Domaine lots actually sell. It is recorded even
        when the lot is of no further buying interest.
        """
        if raw.hammer_price is None:
            return
        self._state.record_hammer_price(
            raw.id, raw.hammer_price, raw.starting_price, self._started_at
        )

    def _flag_incomplete(self, lot_id: int) -> None:
        """Surface the unreadability of the single most important field."""
        self._errors.append(
            RunError(
                step="lot",
                target=str(lot_id),
                kind="ChampCritiqueIllisible",
                message=(
                    "la mention « réservé aux professionnels » n'a pas pu être lue ; "
                    "le lot est livré incomplet, ne pas décider dessus"
                ),
            )
        )

    # --------------------------------------------------------------- assembling

    def _sale(self, source: SaleSource, kept: list[Lot], rejected: list[RejectedLot]) -> Sale:
        """Compose the sale, deriving its place from its lots' collection points."""
        place, postcode = _dominant_place(kept)
        department = department_from_postcode(postcode) or ""
        return Sale(
            id=str(source.id),
            url=f"{self._config.network.base_url}/vente/{source.id}",
            title=source.title,
            dnid=source.regional_directorate,
            opens_at=source.opens_at,
            closes_at=source.closes_at,
            collection_place=place,
            postcode=postcode,
            department=department,
            in_scope=self._perimeter.contains(postcode, place),
            lot_count=source.lot_count or len(kept) + len(rejected),
        )

    def _document(
        self, sales: list[Sale], lots: list[Lot], rejected: list[RejectedLot]
    ) -> OutputDocument:
        duration = (self._clock() - self._started_at).total_seconds()
        _LOG.info(
            "run.finished",
            sales=self._counters.sales_scanned,
            lots_seen=self._counters.lots_seen,
            kept=self._counters.lots_kept,
            rejected=self._counters.lots_rejected,
            reasons=self._counters.reasons,
            errors=len(self._errors),
            duration_s=round(duration, 1),
        )
        return OutputDocument(
            run=Run(
                timestamp=self._started_at,
                duration_seconds=max(duration, 0.0),
                sales_scanned=self._counters.sales_scanned,
                lots_seen=self._counters.lots_seen,
                lots_kept=self._counters.lots_kept,
                lots_rejected=self._counters.lots_rejected,
                errors=self._errors,
            ),
            sales=sales,
            lots=lots,
            rejected=rejected,
        )

    def _record_anomaly(self, step: str, target: str, exc: Exception) -> None:
        """Record an anomaly: in the logs AND in the output document."""
        _LOG.warning("run.anomaly", step=step, target=target, error=str(exc))
        self._errors.append(
            RunError(step=step, target=target, kind=type(exc).__name__, message=str(exc))
        )


# --------------------------------------------------------------------- helpers


def _fingerprint(raw: LotSource) -> str:
    """Fingerprint of a lot: changes when its listing plausibly changed."""
    seed = f"{raw.url_key}|{raw.title}|{raw.description}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _lot_url(config: Configuration, raw: LotSource) -> str:
    return f"{config.network.base_url}/lot/{raw.url_key}.html"


def _signals(raw: LotSource, attributes: VehicleAttributes | None) -> LotSignals:
    """Gather what the business rules are allowed to look at."""
    return LotSignals(
        description=raw.description,
        mileage=attributes.mileage if attributes else None,
        has_key=attributes.has_key if attributes else None,
        registration_certificate=attributes.registration_certificate if attributes else None,
        kind=attributes.kind if attributes else None,
        first_registration_year=attributes.first_registration_year if attributes else None,
        declared_end_of_life=attributes.declared_end_of_life if attributes else None,
        re_registrable=attributes.re_registrable if attributes else None,
        non_compliant=attributes.non_compliant if attributes else None,
        has_vehicle_attributes=attributes.is_a_vehicle if attributes else None,
    )


def _dominant_place(lots: list[Lot]) -> tuple[str, str]:
    """Most frequent collection point among a sale's lots."""
    counts: dict[tuple[str, str], int] = {}
    for lot in lots:
        key = (lot.collection_place, lot.postcode)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "", ""
    return max(counts.items(), key=lambda item: item[1])[0]


def _vat_reclaimable(label: str) -> bool | None:
    """Interpret the VAT attribute. `None` when the source does not decide."""
    flattened = text.normalize(label)
    if not flattened:
        return None
    if flattened in {"aucun", "aucune", "0", "exonere", "exoneree"}:
        return False
    if "tva" in flattened or any(c.isdigit() for c in flattened):
        return True
    return None


def _build_lot(
    *,
    config: Configuration,
    raw: LotSource,
    attributes: VehicleAttributes | None,
    perimeter: Perimeter,
    is_new: bool,
    bid_moved: bool,
) -> Lot:
    """Assemble the output-contract lot from all of its sources."""
    place, postcode, description = _context(raw, attributes)
    return Lot(
        id=str(raw.id),
        url=_lot_url(config, raw),
        sale_id=str(raw.sale_id),
        number=raw.number,
        title=raw.title,
        category=config.filters.vehicle_category,
        trade_only=raw.trade_only,
        **_vehicle_fields(raw, attributes, description),
        starting_price=raw.starting_price,
        current_bid=raw.current_bid,
        # The source publishes neither the number of bidders nor per-lot buyer
        # fees: `null` here means "absent from the source".
        bidder_count=None,
        buyer_fee_pct=None,
        collection_place=place,
        postcode=postcode,
        department=department_from_postcode(postcode) or "",
        viewing_dates=text.extract_viewing_dates(description) or "",
        full_description=description,
        out_of_scope=not perimeter.contains(postcode, place),
        new_since_last_run=is_new,
        bid_moved=bid_moved,
        missing_fields=_missing_fields(raw, attributes),
    )


def _context(raw: LotSource, attributes: VehicleAttributes | None) -> tuple[str, str, str]:
    """Place, postcode and description; the list wins over the detailed listing."""
    postcode = raw.collection_postcode or (attributes.collection_postcode if attributes else "")
    place = raw.collection_city or (attributes.collection_city if attributes else "")
    description = raw.description or (attributes.description if attributes else "")
    return place, postcode, description


def _missing_fields(raw: LotSource, attributes: VehicleAttributes | None) -> list[str]:
    """Fields present in the source but unusable, or a missing listing."""
    missing = list(raw.unreadable_fields)
    if attributes is None:
        missing.append("fiche_detaillee")
    else:
        missing.extend(attributes.unreadable_fields)
    return sorted(set(missing))


def _vehicle_fields(
    raw: LotSource, attributes: VehicleAttributes | None, description: str
) -> dict[str, Any]:
    """Vehicle characteristics: structured attributes first, then free text."""
    return {
        "make": attributes.make if attributes else "",
        "model": attributes.model if attributes else "",
        "variant": _variant(raw.title, attributes),
        "first_registration": attributes.first_registration if attributes else "",
        "mileage": _mileage(attributes, description),
        "fuel": attributes.fuel if attributes else "",
        "gearbox": attributes.gearbox if attributes else "",
        "tax_horsepower": text.extract_tax_horsepower(description),
        "vin": text.extract_vin(description) or "",
        "crit_air": text.extract_crit_air(description) or "",
        "inspection": (
            text.extract_inspection_date(description) or _inspection_from_attribute(attributes)
        ),
        "registration_certificate": attributes.registration_certificate if attributes else None,
        "keys": attributes.has_key if attributes else None,
        "declared_condition": text.extract_declared_condition(description) or "",
        "vat_reclaimable": _vat_reclaimable(attributes.vat if attributes else ""),
    }


def _variant(title: str, attributes: VehicleAttributes | None) -> str:
    """What is left of the title once make and model have been removed."""
    if attributes is None:
        return ""
    rest = title
    for word in (attributes.make, attributes.model):
        if word:
            rest = rest.replace(word, "").replace(word.title(), "")
    return " ".join(rest.split())


def _mileage(attributes: VehicleAttributes | None, description: str) -> int | None:
    """Structured mileage when there is one, otherwise the one in the description."""
    if attributes and attributes.mileage:
        return attributes.mileage
    return text.extract_mileage(description)


def _inspection_from_attribute(attributes: VehicleAttributes | None) -> str:
    """Roadworthiness mention derived from the boolean attribute."""
    if attributes is None or attributes.roadworthiness_test is None:
        return ""
    return "présent" if attributes.roadworthiness_test else "absent"


def _to_memo(attributes: VehicleAttributes) -> dict[str, Any]:
    """Serialisable form of a listing, for the SQLite cache."""
    return {
        name: getattr(attributes, name)
        for name in VehicleAttributes.__dataclass_fields__
        if name != "raw_attributes"
    }


def _from_memo(memo: Mapping[str, Any]) -> VehicleAttributes | None:
    """Rebuild a listing from the cache.

    Returns `None` when the memorised shape no longer matches the current
    model — a cache written by an earlier version. The caller refetches.
    """
    data = dict(memo)
    data["unreadable_fields"] = tuple(data.get("unreadable_fields") or ())
    data["raw_attributes"] = {}
    try:
        return VehicleAttributes(**data)
    except TypeError:
        return None
