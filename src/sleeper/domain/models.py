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
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from sleeper.domain.damage import BodyDamage
from sleeper.domain.inspection import Inspection
from sleeper.domain.segment import Segment
from sleeper.domain.territory import ScopeStatus
from sleeper.scoring.engine import ScoreRule

Postcode = Annotated[str, Field(max_length=10)]
Department = Annotated[str, Field(max_length=3)]

#: Field whose absence makes a lot unusable for a buying decision.
#: It is the single most important piece of information in this project.
CRITICAL_FIELD = "reserve_aux_professionnels"

#: Where a buyer's premium came from. `config` is not a source the site
#: published: it is an operator assumption, and it is flagged as such.
FeeSource = Literal["vente", "lot", "config", "absent"]


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
    #: Lots whose collection point could not be read. They are collected, never
    #: dropped, and they are the number to watch after every run.
    lots_scope_unknown: int = Field(alias="lots_perimetre_inconnu", ge=0, default=0)
    #: Lots the quote table does not know. They are not lost: the cheap ones
    #: go into their own queue.
    lots_without_quote: int = Field(alias="lots_sans_cote", ge=0, default=0)
    #: Sales that do not publish their buyer's premium anywhere.
    sales_without_published_fees: int = Field(alias="ventes_sans_frais_publies", ge=0, default=0)
    #: Integrity findings. They never fail the run; they must be seen.
    integrity_anomalies: int = Field(alias="anomalies_integrite", ge=0, default=0)
    errors: list[RunError] = Field(alias="erreurs", default_factory=list)


class Sale(SleeperModel):
    """A Domaine sale."""

    id: str
    url: str
    title: str = Field(alias="intitule")
    #: Regional directorate running the sale ("LILLE", "LA REUNION"). The
    #: contract calls this field `dnid`, after the administration that runs
    #: these sales. Filling it with the sale id would only duplicate `id`,
    #: while the directorate is the one piece of the source that would
    #: otherwise be lost.
    dnid: str
    opens_at: datetime | None = Field(alias="date_ouverture")
    closes_at: datetime | None = Field(alias="date_cloture")
    collection_place: str = Field(alias="lieu_retrait")
    postcode: Postcode = Field(alias="code_postal")
    department: Department = Field(alias="departement")
    scope: ScopeStatus = Field(alias="perimetre")
    lot_count: int = Field(alias="nb_lots", ge=0)
    buyer_fee_pct: float | None = Field(alias="frais_acheteur_pct", default=None, ge=0)
    buyer_fee_source: FeeSource = Field(alias="frais_acheteur_source", default="absent")
    conditions_text: str = Field(alias="conditions_vente_texte", default="")


class Lot(SleeperModel):
    """A vehicle lot, in the exact shape of the output contract."""

    id: str
    url: str
    sale_id: str = Field(alias="vente_id")
    number: str = Field(alias="numero")
    title: str = Field(alias="titre")
    category: str = Field(alias="categorie")
    #: Commercial segment. Which ones are worked is a line of configuration,
    #: never a filter: a lot outside them stays here, stated.
    segment: Segment = Field(alias="segment", default="vl")
    trade_only: bool | None = Field(alias=CRITICAL_FIELD)
    make: str = Field(alias="marque")
    model: str = Field(alias="modele")
    variant: str = Field(alias="version")
    first_registration: str = Field(alias="premiere_mise_en_circulation")
    mileage: int | None = Field(alias="kilometrage", default=None, ge=0)
    #: Mileage divided by the vehicle's age. `None` when either is unknown.
    mileage_per_year: int | None = Field(alias="km_par_an", default=None, ge=0)
    fuel: str = Field(alias="energie")
    gearbox: str = Field(alias="boite")
    tax_horsepower: int | None = Field(alias="puissance_fiscale", default=None, ge=0)
    vin: str
    crit_air: str
    inspection: Inspection = Field(alias="controle_technique", default_factory=Inspection)
    registration_certificate: bool | None = Field(alias="carte_grise")
    keys: bool | None = Field(alias="cles")
    declared_condition: str = Field(alias="etat_declare")
    #: Graded, never grounds for exclusion. See `domain/damage.py`.
    body_damage: BodyDamage = Field(alias="dommages_carrosserie", default="aucun")
    starting_price: float | None = Field(alias="mise_a_prix", default=None, ge=0)
    current_bid: float | None = Field(alias="enchere_en_cours", default=None, ge=0)
    bidder_count: int | None = Field(alias="nb_encherisseurs", default=None, ge=0)
    collection_place: str = Field(alias="lieu_retrait")
    postcode: Postcode = Field(alias="code_postal")
    department: Department = Field(alias="departement")
    viewing_dates: str = Field(alias="dates_visite")
    closes_at: datetime | None = Field(alias="date_cloture", default=None)
    buyer_fee_pct: float | None = Field(alias="frais_acheteur_pct", default=None, ge=0)
    buyer_fee_source: FeeSource = Field(alias="frais_acheteur_source", default="absent")
    #: True when the rate is an assumption, not something the source published.
    #: It must stay visible all the way to the report.
    hypothetical_fees: bool = Field(alias="frais_hypothetiques", default=False)
    vat_reclaimable: bool | None = Field(alias="tva_recuperable")
    full_description: str = Field(alias="description_integrale")
    scope: ScopeStatus = Field(alias="perimetre")
    #: True when the place was inherited from the sale because the lot had none.
    inherited_scope: bool = Field(alias="perimetre_herite", default=False)
    new_since_last_run: bool = Field(alias="nouveau_depuis_dernier_run")
    bid_moved: bool = Field(alias="enchere_a_bouge")
    missing_fields: list[str] = Field(alias="champs_manquants", default_factory=list)

    # --- Tri. Ce n'est pas une cotation : il décide seulement qui reçoit
    # --- l'analyse coûteuse. Voir `scoring/engine.py`.
    quote_eur: float | None = Field(alias="cote_reference", default=None)
    repairs_eur: float = Field(alias="remise_en_etat_estimee", default=0.0, ge=0)
    #: Marge **au prix de départ**, en euros. Ce n'est pas une marge attendue :
    #: le prix au marteau est inconnu et sera plus haut. C'est le meilleur cas,
    #: et c'est le seul que ce tri ait le droit de calculer.
    margin_at_start_eur: float | None = Field(alias="marge_au_prix_de_depart", default=None)
    score: float | None = Field(alias="score", default=None)
    rank: int | None = Field(alias="rang", default=None, ge=1)
    score_explanation: list[ScoreRule] = Field(alias="score_explication", default_factory=list)
    beyond_economic_repair: bool = Field(alias="non_reparable_economiquement", default=False)
    to_quote: bool = Field(alias="a_coter", default=False)
    #: Écarté du classement parce que sa marge ne franchit pas le plancher.
    #: Il reste dans le JSON, avec son motif dans `score_explication`.
    below_margin_floor: bool = Field(alias="marge_sous_le_plancher", default=False)

    @property
    def scope_unknown(self) -> bool:
        """A lot whose collection point could not be read at all."""
        return self.scope == "inconnu"

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


#: Version du contrat de sortie. Déclarée ici, et **seulement ici** : la
#: déclarer aussi dans le module de sérialisation avait laissé les deux
#: dériver, et un document se disait 2.0 pendant que le validateur exigeait
#: 3.0. Toute évolution est documentée dans docs/schema.md et donne lieu à un
#: nouveau fichier de schéma.
SCHEMA_VERSION: Final[Literal["3.0"]] = "3.0"


class OutputDocument(SleeperModel):
    """The document produced by each execution."""

    schema_version: Literal["3.0"] = SCHEMA_VERSION
    run: Run
    sales: list[Sale] = Field(alias="ventes")
    lots: list[Lot]
    rejected: list[RejectedLot] = Field(alias="ecartes")
