"""Traduction des reponses de l'API Magento en objets typés du domaine.

Cette couche est le point ou le contrat amont rencontre le notre. Elle
applique une discipline stricte :

* un champ STRUCTURANT absent leve `SchemaAmontError` — c'est une casse du
  contrat amont, pas une donnee manquante ;
* un champ present mais illisible alimente `champs_illisibles`, ce qui
  remontera dans `champs_manquants` puis dans `run.erreurs` ;
* un champ present et explicitement nul reste nul, sans bruit : c'est une
  absence legitime au sens du contrat de sortie.

Les attributs porteurs de donnees personnelles ou bancaires sont ecartes des
la lecture : ils ne sont necessaires a aucune decision d'achat.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from sleeper.domain import texte
from sleeper.domain.codes import ATTRIBUTS_SENSIBLES, vers_booleen
from sleeper.errors import SchemaAmontError

_ANNEE_MIN: Final = 1900


@dataclass(frozen=True, slots=True)
class Pagination:
    """Etat de pagination renvoye par la source."""

    total_count: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class VenteSource:
    """Une vente telle que la source la decrit."""

    id: int
    intitule: str
    description: str
    statut: int
    statut_libelle: str
    type_libelle: str
    date_ouverture: datetime | None
    date_cloture: datetime | None
    direction_regionale: str
    nb_lots: int
    categories: tuple[str, ...]
    reserve_aux_professionnels: bool | None


@dataclass(frozen=True, slots=True)
class LotSource:
    """Un lot tel que la liste des lots d'une vente le decrit."""

    id: int
    sku: str
    url_key: str
    numero: str
    titre: str
    vente_id: int
    reserve_aux_professionnels: bool | None
    mise_a_prix: float | None
    enchere_en_cours: float | None
    prix_reserve: float | None
    statut_libelle: str
    date_ouverture: datetime | None
    date_cloture: datetime | None
    ville_retrait: str
    code_postal_retrait: str
    description: str
    direction_regionale: str
    champs_illisibles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttributsVehicule:
    """Attributs vehicule d'une fiche de lot."""

    marque: str
    modele: str
    energie: str
    boite: str
    carrosserie: str
    genre: str
    kilometrage: int | None
    a_une_cle: bool | None
    certificat_immatriculation: bool | None
    controle_technique: bool | None
    premiere_mise_en_circulation: str
    annee_mise_en_circulation: int | None
    tva: str
    vhu_declare: bool | None
    non_conforme: bool | None
    immatriculable_a_nouveau: bool | None
    compteur_modifie: bool | None
    fourriere_administrative: bool | None
    ville_retrait: str
    code_postal_retrait: str
    description: str
    attributs_bruts: Mapping[str, str] = field(default_factory=dict)
    champs_illisibles: tuple[str, ...] = ()

    @property
    def est_un_vehicule(self) -> bool:
        """Vrai si la fiche porte au moins un attribut vehicule identifiant."""
        return bool(self.genre or self.marque or self.modele)


def _bloc_donnees(payload: Mapping[str, Any], chemin: str) -> Mapping[str, Any]:
    """Ouvre l'enveloppe GraphQL, en refusant de travailler sur une reponse en erreur."""
    if erreurs := payload.get("errors"):
        premier = erreurs[0].get("message", "sans message") if erreurs else "sans message"
        raise SchemaAmontError(chemin, f"erreur GraphQL renvoyee par la source : {premier}")
    donnees = payload.get("data")
    if not isinstance(donnees, Mapping):
        raise SchemaAmontError(chemin, "bloc 'data' absent de la reponse")
    return donnees


def _exiger(source: Mapping[str, Any], cle: str, chemin: str) -> Any:
    """Recupere une cle STRUCTURANTE. Son absence casse le contrat amont."""
    if cle not in source:
        raise SchemaAmontError(f"{chemin}.{cle}", "champ structurant absent de la reponse")
    return source[cle]


def _texte(valeur: Any) -> str:
    """Rend une chaine propre, jamais `None` : le contrat de sortie veut `\"\"`."""
    return "" if valeur is None else str(valeur).strip()


def _nombre(valeur: Any) -> float | None:
    """Convertit un montant. Une valeur illisible vaut absence, pas zero."""
    if valeur is None or valeur == "":
        return None
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _entier(valeur: Any) -> int | None:
    nombre = _nombre(valeur)
    return None if nombre is None else int(nombre)


def _horodatage(valeur: Any) -> datetime | None:
    """Lit un horodatage ISO 8601. Une valeur illisible vaut absence."""
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError:
        return None


def _pagination(bloc: Mapping[str, Any], chemin: str) -> Pagination:
    infos = bloc.get("page_info") or {}
    return Pagination(
        total_count=int(_exiger(bloc, "total_count", chemin) or 0),
        total_pages=int(infos.get("total_pages") or 0),
    )


def lire_ventes(payload: Mapping[str, Any]) -> tuple[tuple[VenteSource, ...], Pagination]:
    """Traduit une page de la liste des ventes."""
    chemin = "data.auctionsList"
    donnees = _bloc_donnees(payload, chemin)
    bloc = donnees.get("auctionsList")
    if not isinstance(bloc, Mapping):
        raise SchemaAmontError(chemin, "bloc absent : l'operation getAuctions a change")
    items = _exiger(bloc, "items", chemin)
    if not isinstance(items, Sequence):
        raise SchemaAmontError(f"{chemin}.items", "liste attendue")
    ventes = tuple(_vente(item, f"{chemin}.items[{i}]") for i, item in enumerate(items))
    return ventes, _pagination(bloc, chemin)


def _vente(item: Mapping[str, Any], chemin: str) -> VenteSource:
    categories = tuple(
        _texte(c.get("name")) for c in (item.get("categories") or []) if c.get("name")
    )
    return VenteSource(
        id=int(_exiger(item, "dnid_auction_id", chemin)),
        intitule=_texte(item.get("name")),
        description=_texte(item.get("description")),
        statut=int(_exiger(item, "auction_auto_status", chemin)),
        statut_libelle=_texte(item.get("status_text")),
        type_libelle=_texte(item.get("type_text")),
        date_ouverture=_horodatage(item.get("start_date")),
        date_cloture=_horodatage(item.get("end_date")),
        direction_regionale=_texte(item.get("sales_inspector_label")),
        nb_lots=_entier(item.get("auction_number_of_lots")) or 0,
        categories=categories,
        reserve_aux_professionnels=_booleen_tolerant(item.get("professional_only")),
    )


def _booleen_tolerant(valeur: Any) -> bool | None:
    """Interprete un booleen amont sans jamais lever : `None` si illisible."""
    try:
        return vers_booleen(valeur)
    except ValueError:
        return None


def lire_lots(payload: Mapping[str, Any]) -> tuple[tuple[LotSource, ...], Pagination]:
    """Traduit une page de lots d'une vente."""
    chemin = "data.products"
    donnees = _bloc_donnees(payload, chemin)
    bloc = donnees.get("products")
    if not isinstance(bloc, Mapping):
        raise SchemaAmontError(chemin, "bloc absent : l'operation getAuctionLots a change")
    items = _exiger(bloc, "items", chemin)
    if not isinstance(items, Sequence):
        raise SchemaAmontError(f"{chemin}.items", "liste attendue")
    lots = tuple(_lot(item, f"{chemin}.items[{i}]") for i, item in enumerate(items))
    return lots, _pagination(bloc, chemin)


def _lot(item: Mapping[str, Any], chemin: str) -> LotSource:
    # `professional_only` est l'information la plus importante du projet :
    # sa disparition du schema est une casse, pas une donnee manquante.
    brut_pro = _exiger(item, "professional_only", chemin)
    reserve = _booleen_tolerant(brut_pro)
    illisibles: list[str] = []
    if reserve is None and brut_pro not in (None, ""):
        illisibles.append("reserve_aux_professionnels")

    retrait = item.get("dropoff_location") or {}
    court = texte.depuis_html((item.get("short_description") or {}).get("html"))
    longue = texte.depuis_html((item.get("description") or {}).get("html"))
    return LotSource(
        id=int(_exiger(item, "id", chemin)),
        sku=_texte(item.get("sku")),
        url_key=_texte(_exiger(item, "url_key", chemin)),
        numero=_texte(item.get("lot_number")),
        titre=_texte(item.get("name")),
        vente_id=int(_exiger(item, "auction", chemin)),
        reserve_aux_professionnels=reserve,
        mise_a_prix=_nombre(_exiger(item, "price_auction", chemin)),
        enchere_en_cours=_nombre(item.get("last_bid")),
        prix_reserve=_nombre(item.get("reserve_price")),
        statut_libelle=_texte(item.get("lot_status_label")),
        date_ouverture=_horodatage(item.get("start_date")),
        date_cloture=_horodatage(item.get("end_date")),
        ville_retrait=_texte(retrait.get("city")),
        code_postal_retrait=_texte(retrait.get("postcode")),
        description=" ".join(x for x in (court, longue) if x),
        direction_regionale=_texte((item.get("sales_inspector_data") or {}).get("cav_name")),
        champs_illisibles=tuple(illisibles),
    )


def _valeur_attribut(attribut: Mapping[str, Any]) -> str:
    """Rend la valeur d'un attribut, qu'elle soit saisie ou choisie dans une liste."""
    saisie = (attribut.get("entered_attribute_value") or {}).get("value")
    if saisie not in (None, ""):
        return _texte(saisie)
    options = (attribut.get("selected_attribute_options") or {}).get("attribute_option") or []
    return " / ".join(_texte(o.get("label")) for o in options if o.get("label"))


def lire_attributs(payload: Mapping[str, Any]) -> AttributsVehicule:
    """Traduit la fiche detaillee d'un lot en attributs vehicule."""
    chemin = "data.products.items[0]"
    donnees = _bloc_donnees(payload, chemin)
    bloc = donnees.get("products")
    if not isinstance(bloc, Mapping):
        raise SchemaAmontError(chemin, "bloc absent : l'operation getProductPageMain a change")
    items = bloc.get("items")
    if not items:
        raise SchemaAmontError("data.products.items", "fiche vide : lot introuvable")
    item = items[0]

    bruts = {
        a["attribute_metadata"]["code"]: _valeur_attribut(a)
        for a in (item.get("custom_attributes") or [])
        if a.get("attribute_metadata", {}).get("code") not in ATTRIBUTS_SENSIBLES
    }
    retrait = item.get("dropoff_location") or item.get("dropoff_location_fo") or {}
    mec = bruts.get("date_first_registration", "")
    illisibles = tuple(
        nom
        for nom, code in (("kilometrage", "vehicle_mileage"), ("cles", "vehicle_has_a_key"))
        if code in bruts and _valeur_illisible(bruts[code], code)
    )
    return AttributsVehicule(
        marque=bruts.get("vehicle_brand", ""),
        modele=bruts.get("vehicle_model", ""),
        energie=bruts.get("vehicle_energy_type", ""),
        boite=bruts.get("gearbox_type", ""),
        carrosserie=bruts.get("body_type", ""),
        genre=bruts.get("kind", ""),
        kilometrage=_entier(bruts.get("vehicle_mileage")),
        a_une_cle=_booleen_tolerant(bruts.get("vehicle_has_a_key")),
        certificat_immatriculation=_booleen_tolerant(bruts.get("registration_certificate")),
        controle_technique=_booleen_tolerant(bruts.get("technical_control")),
        premiere_mise_en_circulation=mec[:10],
        annee_mise_en_circulation=_annee(mec),
        tva=bruts.get("tax_class_id", ""),
        vhu_declare=_booleen_tolerant(bruts.get("vhu_declared")),
        non_conforme=_booleen_tolerant(bruts.get("not_conforme")),
        immatriculable_a_nouveau=_booleen_tolerant(bruts.get("registrable_again")),
        compteur_modifie=_booleen_tolerant(bruts.get("counter_change")),
        fourriere_administrative=_booleen_tolerant(bruts.get("administrative_pound")),
        ville_retrait=_texte(retrait.get("city")),
        code_postal_retrait=_texte(retrait.get("postcode")),
        description=texte.depuis_html((item.get("short_description") or {}).get("html")),
        attributs_bruts=bruts,
        champs_illisibles=illisibles,
    )


def _valeur_illisible(valeur: str, code: str) -> bool:
    """Detecte une valeur presente mais inexploitable pour l'attribut vise."""
    if not valeur:
        return False
    if code == "vehicle_mileage":
        return _nombre(valeur) is None
    return _booleen_tolerant(valeur) is None


def _annee(horodatage: str) -> int | None:
    """Extrait l'annee d'une date de premiere mise en circulation."""
    date = _horodatage(horodatage)
    if date is None or date.year < _ANNEE_MIN:
        return None
    return date.year
