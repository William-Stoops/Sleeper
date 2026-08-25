"""Domain models.

The output contract is frozen here and nowhere else: the JSON Schema
published under `schemas/` derives from these classes, and the document is
validated against that schema before it is written.

**Identifiers are English, the wire format is French.** The JSON keys were
specified in French and are consumed by a downstream system, so they are
pinned as aliases rather than renamed. Serialisation always goes through
`by_alias=True`; a test guards the contract.

Non-negotiable convention on null values:

* `null` means "information absent from the source";
* a failed extraction never writes `null` silently: it feeds `missing_fields`
  on the lot and `run.erreurs` on the execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Postcode = Annotated[str, Field(max_length=10)]
Department = Annotated[str, Field(max_length=3)]

#: Field whose absence makes a lot unusable for a buying decision.
#: It is the single most important piece of information in this project.
CRITICAL_FIELD = "reserve_aux_professionnels"


class SleeperModel(BaseModel):
    """Shared base: unknown fields rejected, immutable, populated by name."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class RunError(SleeperModel):
    """An anomaly met during the run. Never swallowed."""

    step: str = Field(alias="etape")
    target: str = Field(alias="cible")
    kind: str = Field(alias="type")
    message: str = Field(alias="message")


class Run(SleeperModel):
    """Numeric summary of the execution."""

    timestamp: datetime = Field(alias="horodatage")
    duration_seconds: float = Field(alias="duree_secondes", ge=0)
    sales_scanned: int = Field(alias="ventes_scannees", ge=0)
    lots_seen: int = Field(alias="lots_vus", ge=0)
    lots_kept: int = Field(alias="lots_retenus", ge=0)
    lots_rejected: int = Field(alias="lots_ecartes", ge=0)
    errors: list[RunError] = Field(alias="erreurs", default_factory=list)


class Sale(SleeperModel):
    """A Domaine sale."""

    id: str
    url: str
    title: str = Field(alias="intitule")
    dnid: str
    opens_at: datetime | None = Field(alias="date_ouverture")
    closes_at: datetime | None = Field(alias="date_cloture")
    collection_place: str = Field(alias="lieu_retrait")
    postcode: Postcode = Field(alias="code_postal")
    department: Department = Field(alias="departement")
    in_scope: bool = Field(alias="dans_perimetre")
    lot_count: int = Field(alias="nb_lots", ge=0)


class Lot(SleeperModel):
    """A vehicle lot, in the exact shape of the output contract."""

    id: str
    url: str
    sale_id: str = Field(alias="vente_id")
    number: str = Field(alias="numero")
    title: str = Field(alias="titre")
    category: str = Field(alias="categorie")
    trade_only: bool | None = Field(alias=CRITICAL_FIELD)
    make: str = Field(alias="marque")
    model: str = Field(alias="modele")
    variant: str = Field(alias="version")
    first_registration: str = Field(alias="premiere_mise_en_circulation")
    mileage: int | None = Field(alias="kilometrage", default=None, ge=0)
    fuel: str = Field(alias="energie")
    gearbox: str = Field(alias="boite")
    tax_horsepower: int | None = Field(alias="puissance_fiscale", default=None, ge=0)
    vin: str
    crit_air: str
    inspection: str = Field(alias="controle_technique")
    registration_certificate: bool | None = Field(alias="carte_grise")
    keys: bool | None = Field(alias="cles")
    declared_condition: str = Field(alias="etat_declare")
    starting_price: float | None = Field(alias="mise_a_prix", default=None, ge=0)
    current_bid: float | None = Field(alias="enchere_en_cours", default=None, ge=0)
    bidder_count: int | None = Field(alias="nb_encherisseurs", default=None, ge=0)
    collection_place: str = Field(alias="lieu_retrait")
    postcode: Postcode = Field(alias="code_postal")
    department: Department = Field(alias="departement")
    viewing_dates: str = Field(alias="dates_visite")
    buyer_fee_pct: float | None = Field(alias="frais_acheteur_pct", default=None, ge=0)
    vat_reclaimable: bool | None = Field(alias="tva_recuperable")
    full_description: str = Field(alias="description_integrale")
    out_of_scope: bool = Field(alias="hors_perimetre")
    new_since_last_run: bool = Field(alias="nouveau_depuis_dernier_run")
    bid_moved: bool = Field(alias="enchere_a_bouge")
    missing_fields: list[str] = Field(alias="champs_manquants", default_factory=list)

    @property
    def is_incomplete(self) -> bool:
        """A lot missing the critical field must not be treated as deliverable."""
        return CRITICAL_FIELD in self.missing_fields


class RejectedLot(SleeperModel):
    """A lot dropped by a business rule, with its reason."""

    id: str
    url: str
    title: str = Field(alias="titre")
    reason: str = Field(alias="motif")


class OutputDocument(SleeperModel):
    """The document produced by each execution."""

    schema_version: Literal["1.0"] = "1.0"
    run: Run
    sales: list[Sale] = Field(alias="ventes")
    lots: list[Lot]
    rejected: list[RejectedLot] = Field(alias="ecartes")
