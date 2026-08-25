"""Markdown digest: readable, and honest about what failed.

The rendered text is French: it is the operator's report.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from sleeper.domain.models import Lot, OutputDocument, RejectedLot, Run, RunError
from sleeper.output.digest import SECTION_LIMIT, render


def make_lot(**overrides: Any) -> Lot:
    base: dict[str, Any] = {
        "id": "267804",
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
        "inspection": "",
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
        "out_of_scope": False,
        "new_since_last_run": False,
        "bid_moved": False,
        "missing_fields": [],
    }
    base.update(overrides)
    return Lot(**base)


def make_document(
    lots: list[Lot],
    rejected: list[RejectedLot] | None = None,
    errors: list[RunError] | None = None,
) -> OutputDocument:
    return OutputDocument(
        run=Run(
            timestamp=datetime(2026, 8, 25, 4, 30, tzinfo=UTC),
            duration_seconds=42.0,
            sales_scanned=2,
            lots_seen=len(lots),
            lots_kept=len(lots),
            lots_rejected=len(rejected or []),
            errors=errors or [],
        ),
        sales=[],
        lots=lots,
        rejected=rejected or [],
    )


class TestStructure:
    def test_contains_the_four_expected_sections(self) -> None:
        rendered = render(make_document([make_lot()]))
        for title in (
            "Nouveaux lots",
            "Enchères qui ont bougé",
            "Réservés aux professionnels",
            "Erreurs du run",
        ):
            assert title in rendered

    def test_the_header_carries_the_counters(self) -> None:
        rendered = render(make_document([make_lot(), make_lot(id="2")]))
        assert "2 vente(s) balayée(s)" in rendered
        assert "**2 retenu(s)**" in rendered

    def test_an_empty_run_says_so_instead_of_lying(self) -> None:
        rendered = render(make_document([]))
        assert "aucun nouveau lot depuis le dernier run" in rendered
        assert "run sans erreur" in rendered


class TestContent:
    def test_new_lots_are_isolated(self) -> None:
        rendered = render(
            make_document(
                [
                    make_lot(id="1", title="NEUF", new_since_last_run=True),
                    make_lot(id="2", title="CONNU"),
                ]
            )
        )
        section = rendered.split("## Nouveaux lots")[1].split("##")[0]
        assert "NEUF" in section
        assert "CONNU" not in section

    def test_moved_bids_are_isolated(self) -> None:
        rendered = render(
            make_document([make_lot(id="1", title="MONTE", bid_moved=True, current_bid=2000.0)])
        )
        section = rendered.split("## Enchères qui ont bougé")[1].split("##")[0]
        assert "MONTE" in section
        assert "2 000 €" in section

    def test_out_of_scope_is_flagged(self) -> None:
        assert "*hors périmètre*" in render(make_document([make_lot(out_of_scope=True)]))

    @pytest.mark.parametrize(
        ("value", "expected"), [(True, "**PRO**"), (False, "tous publics"), (None, "⚠️ inconnu")]
    )
    def test_trade_only_mention(self, value: bool | None, expected: str) -> None:
        # The lot is marked "new" so it appears in a table: a lot that is
        # neither new, nor moving, nor trade-only has no business in the
        # digest — the JSON stays the complete source.
        missing = ["reserve_aux_professionnels"] if value is None else []
        rendered = render(
            make_document(
                [make_lot(trade_only=value, new_since_last_run=True, missing_fields=missing)]
            )
        )
        assert expected in rendered

    def test_rejection_reasons_are_counted(self) -> None:
        rejected = [
            RejectedLot(id="1", url="u", title="t", reason="sans_cle"),
            RejectedLot(id="2", url="u", title="t", reason="sans_cle"),
            RejectedLot(id="3", url="u", title="t", reason="epave_ou_pieces"),
        ]
        rendered = render(make_document([], rejected))
        assert "| sans_cle | 2 |" in rendered
        assert "| epave_ou_pieces | 1 |" in rendered

    def test_errors_are_shown_not_hidden(self) -> None:
        errors = [
            RunError(
                step="lots",
                target="vente 467",
                kind="UpstreamSchemaError",
                message="champ professional_only absent",
            )
        ]
        rendered = render(make_document([], errors=errors))
        assert "professional_only absent" in rendered
        assert "run sans erreur" not in rendered


class TestIncompletenessWarning:
    def test_a_lot_without_a_readable_trade_flag_warns_in_the_header(self) -> None:
        incomplete = make_lot(trade_only=None, missing_fields=["reserve_aux_professionnels"])
        rendered = render(make_document([incomplete]))
        assert "lot(s) incomplet(s)" in rendered
        assert rendered.index("incomplet") < rendered.index("## Nouveaux lots")

    def test_no_warning_when_everything_was_read(self) -> None:
        assert "incomplet" not in render(make_document([make_lot()]))

    def test_incomplete_lots_get_their_own_table(self) -> None:
        incomplete = make_lot(
            title="A VERIFIER", trade_only=None, missing_fields=["reserve_aux_professionnels"]
        )
        rendered = render(make_document([incomplete, make_lot(id="2", title="COMPLET")]))
        section = rendered.split("## Lots incomplets")[1].split("##")[0]
        assert "A VERIFIER" in section
        assert "COMPLET" not in section


class TestVolume:
    def test_long_lists_are_truncated_and_say_so(self) -> None:
        lots = [make_lot(id=str(i), new_since_last_run=True) for i in range(SECTION_LIMIT + 5)]
        assert "… et 5 autres" in render(make_document(lots))
