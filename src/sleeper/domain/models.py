"""Modeles du domaine.

Le contrat de sortie est fige ici, et nulle part ailleurs : le JSON Schema
publie dans `schemas/` en est derive, et le document est valide contre ce
schema avant ecriture.

Convention non negociable sur les valeurs nulles :

* `null` signifie « information absente de la source » ;
* un echec d'extraction n'ecrit jamais `null` en silence : il alimente
  `champs_manquants` sur le lot et `run.erreurs` sur l'execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

CodePostal = Annotated[str, Field(max_length=10)]
Departement = Annotated[str, Field(max_length=3)]

#: Champ dont l'absence rend un lot inexploitable pour la decision d'achat.
#: C'est l'information la plus importante du projet.
CHAMP_CRITIQUE = "reserve_aux_professionnels"


class ModeleSleeper(BaseModel):
    """Base commune : interdiction des champs inconnus, immutabilite."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ErreurRun(ModeleSleeper):
    """Une anomalie rencontree pendant l'execution, jamais avalee."""

    etape: str
    cible: str
    type: str
    message: str


class Run(ModeleSleeper):
    """Bilan chiffre de l'execution."""

    horodatage: datetime
    duree_secondes: float = Field(ge=0)
    ventes_scannees: int = Field(ge=0)
    lots_vus: int = Field(ge=0)
    lots_retenus: int = Field(ge=0)
    lots_ecartes: int = Field(ge=0)
    erreurs: list[ErreurRun] = Field(default_factory=list)


class Vente(ModeleSleeper):
    """Une vente du Domaine."""

    id: str
    url: str
    intitule: str
    dnid: str
    date_ouverture: datetime | None
    date_cloture: datetime | None
    lieu_retrait: str
    code_postal: CodePostal
    departement: Departement
    dans_perimetre: bool
    nb_lots: int = Field(ge=0)


class Lot(ModeleSleeper):
    """Un lot vehicule, dans la forme exacte du contrat de sortie."""

    id: str
    url: str
    vente_id: str
    numero: str
    titre: str
    categorie: str
    reserve_aux_professionnels: bool | None
    marque: str
    modele: str
    version: str
    premiere_mise_en_circulation: str
    kilometrage: int | None = Field(default=None, ge=0)
    energie: str
    boite: str
    puissance_fiscale: int | None = Field(default=None, ge=0)
    vin: str
    crit_air: str
    controle_technique: str
    carte_grise: bool | None
    cles: bool | None
    etat_declare: str
    mise_a_prix: float | None = Field(default=None, ge=0)
    enchere_en_cours: float | None = Field(default=None, ge=0)
    nb_encherisseurs: int | None = Field(default=None, ge=0)
    lieu_retrait: str
    code_postal: CodePostal
    departement: Departement
    dates_visite: str
    frais_acheteur_pct: float | None = Field(default=None, ge=0)
    tva_recuperable: bool | None
    description_integrale: str
    hors_perimetre: bool
    nouveau_depuis_dernier_run: bool
    enchere_a_bouge: bool
    champs_manquants: list[str] = Field(default_factory=list)

    @property
    def incomplet(self) -> bool:
        """Un lot prive du champ critique ne doit pas etre traite comme livrable."""
        return CHAMP_CRITIQUE in self.champs_manquants


class LotEcarte(ModeleSleeper):
    """Un lot elimine par une regle metier, avec son motif."""

    id: str
    url: str
    titre: str
    motif: str


class DocumentSortie(ModeleSleeper):
    """Le document produit a chaque execution."""

    schema_version: Literal["1.0"] = "1.0"
    run: Run
    ventes: list[Vente]
    lots: list[Lot]
    ecartes: list[LotEcarte]
