"""Lookup tables for the Domaine's Magento API.

These values are constants of the upstream protocol, recorded during the
discovery phase (see docs/api.md). They are deliberately not configurable:
they are not business settings, they are the grammar of the source.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final


class SaleStatus(IntEnum):
    """`auction_auto_status`: lifecycle of a sale."""

    UPCOMING = 2
    RUNNING = 3
    CLOSED = 4

    @classmethod
    def open_statuses(cls) -> tuple[SaleStatus, ...]:
        """Statuses a daily run must sweep."""
        return (cls.UPCOMING, cls.RUNNING)


class Tristate(StrEnum):
    """A Domaine boolean attribute, which admits a third state."""

    YES = "Oui"
    NO = "Non"
    UNKNOWN = "N/A"


#: `professional_only` arrives as `str` on a sale and as `int` on a lot.
#: The inconsistency is upstream; it is absorbed here, once and for all.
API_TRUE: Final = frozenset({1, "1", "Oui", "oui"})  # 1 == True in Python
API_FALSE: Final = frozenset({0, "0", "Non", "non"})  # 0 == False in Python

#: Registration-document vehicle kinds (`kind` attribute), field J.1.
KIND_CAR: Final = "VP"
KIND_VAN: Final = "CTTE"

#: Kinds to skip outright: two-wheelers, quadricycles, farm gear, trailers.
#: `QM` covers the powered quadricycle, i.e. the licence-free car.
OUT_OF_SCOPE_KINDS: Final = frozenset(
    {
        "CL",
        "CM",
        "MTL",
        "MTT1",
        "MTT2",
        "MTT3",
        "MTT4",  # two-wheelers
        "QM",
        "QLEM",
        "QLOM",  # quadricycles / licence-free
        "TRA",
        "MAGA",
        "MIAR",
        "MAAG",  # farm equipment
        "REM",
        "REMORQUE",
        "RESP",
        "SREM",  # trailers
    }
)

#: Attribute codes carrying personal or banking data.
#: They are never copied into the output, nor into the fixtures.
SENSITIVE_ATTRIBUTES: Final = frozenset(
    {"biciban", "contact_dropoff_location_id", "bid_winner_user", "id_remitting_entity"}
)


def to_bool(value: object) -> bool | None:
    """Normalise an upstream boolean. Returns `None` when the source is silent.

    `None` means "absent from the source", never "we failed to read it": an
    unknown value raises rather than keeping quiet.
    """
    if value is None or value == "":
        return None
    if value in API_TRUE:
        return True
    if value in API_FALSE:
        return False
    if isinstance(value, str) and value.strip().upper() in {"N/A", "NA", "-"}:
        return None
    raise ValueError(f"booléen amont non reconnu : {value!r}")
