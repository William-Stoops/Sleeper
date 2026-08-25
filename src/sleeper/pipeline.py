"""Orchestration d'un run.

Le flux est lineaire et volontairement lisible :

    ventes ouvertes -> lots de chaque vente -> fiche detaillee (si besoin)
    -> regles d'exclusion -> perimetre -> etat -> document

Trois principes gouvernent la gestion d'erreur :

* une anomalie sur UN lot n'interrompt pas le run, mais elle est consignee
  dans `run.erreurs` — jamais avalee ;
* une casse du contrat amont sur une vente interrompt cette vente, pas les
  autres, et remonte de la meme facon ;
* un challenge anti-robot interrompt TOUT le run, sans reprise : insister
  reviendrait a chercher a le contourner.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

from sleeper.api import mapping, operations
from sleeper.api.mapping import AttributsVehicule, LotSource, VenteSource
from sleeper.config import Configuration
from sleeper.domain import texte
from sleeper.domain.exclusions import MoteurExclusions, SignalLot
from sleeper.domain.models import (
    CHAMP_CRITIQUE,
    DocumentSortie,
    ErreurRun,
    Lot,
    LotEcarte,
    Run,
    Vente,
)
from sleeper.domain.perimetre import Perimetre, departement_depuis_code_postal
from sleeper.errors import ProtectionAntiRobotError, SleeperError
from sleeper.state.store import EtatSleeper

_LOG = structlog.get_logger(__name__)


class PasserelleGraphQL(Protocol):
    """Ce dont le pipeline a besoin, et rien de plus.

    Le pipeline ignore qu'il existe un navigateur, des cookies ou des
    reprises : il envoie une operation, il recoit un payload. C'est ce qui
    permet de le rejouer entierement sur des fixtures.
    """

    def interroger(self, requete: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Execute une operation GraphQL et rend son payload."""
        ...


#: Garde-fou : une vente ne devrait jamais depasser cet ordre de grandeur.
#: Au-dela, on suspecte une pagination qui ne se termine pas.
PAGES_MAX = 200


@dataclass(slots=True)
class Compteurs:
    """Ce qui a ete vu, retenu, ecarte — et pourquoi."""

    ventes_scannees: int = 0
    lots_vus: int = 0
    lots_retenus: int = 0
    lots_ecartes: int = 0
    motifs: dict[str, int] = field(default_factory=dict)

    def ecarter(self, motif: str) -> None:
        self.lots_ecartes += 1
        self.motifs[motif] = self.motifs.get(motif, 0) + 1


class Collecteur:
    """Execute un run complet et rend le document de sortie."""

    def __init__(
        self,
        config: Configuration,
        client: PasserelleGraphQL,
        etat: EtatSleeper,
        horloge: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._etat = etat
        # Une seule source de temps : injectable, donc le run est reproductible
        # en test sans figer l'horloge du processus.
        self._horloge = horloge or (lambda: datetime.now(UTC))
        self._debut = self._horloge()
        self._perimetre: Perimetre = config.perimetre_domaine()
        self._exclusions: MoteurExclusions = config.moteur_exclusions()
        self._compteurs = Compteurs()
        self._erreurs: list[ErreurRun] = []

    # ------------------------------------------------------------------ public

    def executer(self) -> DocumentSortie:
        """Balaye les ventes ouvertes et compose le document du run."""
        ventes: list[Vente] = []
        lots: list[Lot] = []
        ecartes: list[LotEcarte] = []
        vues: set[int] = set()

        for source in self._ventes_de_vehicules():
            vues.add(source.id)
            self._compteurs.ventes_scannees += 1
            retenus, sortis = self._traiter_vente(source)
            lots.extend(retenus)
            ecartes.extend(sortis)
            ventes.append(self._vente(source, retenus, sortis))

        self._etat.cloturer_ventes_absentes(vues, self._debut)
        return self._document(ventes, lots, ecartes)

    # ------------------------------------------------------------------ ventes

    def _ventes_de_vehicules(self) -> Iterator[VenteSource]:
        """Ventes ouvertes comportant la categorie vehicules."""
        cible = self._config.filtres.categorie_vehicules
        statuts = [str(s) for s in self._config.filtres.statuts_vente]
        for page in range(1, PAGES_MAX + 1):
            variables = {
                "currentPage": page,
                "pageSize": self._config.filtres.lots_par_page,
                "sort": {"end_date": "ASC"},
                "filter": {"auction_auto_status": {"in": statuts}},
            }
            charge = self._client.interroger(operations.LISTE_VENTES, variables)
            ventes, pagination = mapping.lire_ventes(charge)
            for vente in ventes:
                if cible in vente.categories:
                    yield vente
                else:
                    _LOG.debug("vente.ignoree", vente=vente.id, categories=vente.categories)
            if page >= max(pagination.total_pages, 1):
                return

    def _traiter_vente(self, source: VenteSource) -> tuple[list[Lot], list[LotEcarte]]:
        """Traite tous les lots d'une vente. Une casse amont arrete cette vente seule."""
        self._etat.enregistrer_vente(
            vente_id=source.id,
            intitule=source.intitule,
            direction_regionale=source.direction_regionale,
            statut=source.statut,
            nb_lots=source.nb_lots,
            date_ouverture=source.date_ouverture,
            date_cloture=source.date_cloture,
            horodatage=self._debut,
        )
        try:
            bruts = list(self._lots_de_vente(source.id))
        except ProtectionAntiRobotError:
            raise
        except SleeperError as exc:
            self._consigner("lots", f"vente {source.id}", exc)
            return [], []

        fiches = self._fiches(bruts)
        retenus: list[Lot] = []
        ecartes: list[LotEcarte] = []
        for brut in bruts:
            self._compteurs.lots_vus += 1
            resultat = self._traiter_lot(brut, fiches.get(brut.id))
            if isinstance(resultat, LotEcarte):
                ecartes.append(resultat)
            elif resultat is not None:
                retenus.append(resultat)
        return retenus, ecartes

    def _lots_de_vente(self, vente_id: int) -> Iterator[LotSource]:
        """Parcourt les pages de lots d'une vente."""
        for page in range(1, PAGES_MAX + 1):
            variables = {
                "currentPage": page,
                "pageSize": self._config.filtres.lots_par_page,
                "sort": {"lot_number": "ASC"},
                "filter": {"auction": {"eq": str(vente_id)}},
            }
            charge = self._client.interroger(operations.LOTS_DE_VENTE, variables)
            lots, pagination = mapping.lire_lots(charge)
            yield from lots
            if page >= max(pagination.total_pages, 1):
                return

    # ------------------------------------------------------------------ fiches

    def _fiches(self, bruts: list[LotSource]) -> dict[int, AttributsVehicule]:
        """Recupere les fiches detaillees manquantes, en respectant la cadence."""
        a_charger = [b for b in bruts if self._etat.fiche_en_cache(b.id, _empreinte(b)) is None]
        charges: dict[int, AttributsVehicule] = {}

        for brut in bruts:
            memo = self._etat.fiche_en_cache(brut.id, _empreinte(brut))
            if memo is None:
                continue
            attributs = _attributs_depuis_memo(memo)
            if attributs is None:
                # Cache ecrit par une version anterieure du modele : on le
                # traite comme absent plutot que de faire tomber le run.
                _LOG.warning("fiche.cache_perime", lot=brut.id)
                a_charger.append(brut)
                continue
            charges[brut.id] = attributs

        if a_charger:
            _LOG.info("fiches.telechargement", a_charger=len(a_charger), en_cache=len(charges))
            with ThreadPoolExecutor(max_workers=self._config.reseau.concurrence_max) as pool:
                resultats = list(pool.map(self._fiche, a_charger))
            for brut, attributs in zip(a_charger, resultats, strict=True):
                if attributs is None:
                    continue
                charges[brut.id] = attributs
                self._etat.memoriser_fiche(
                    brut.id, _empreinte(brut), _memo_depuis_attributs(attributs), self._debut
                )
        return charges

    def _fiche(self, brut: LotSource) -> AttributsVehicule | None:
        """Telecharge une fiche. Un echec unitaire ne fait pas tomber le run."""
        try:
            charge = self._client.interroger(
                operations.FICHE_LOT_PRINCIPALE, {"urlKey": brut.url_key}
            )
            return mapping.lire_attributs(charge)
        except ProtectionAntiRobotError:
            raise
        except SleeperError as exc:
            self._consigner("fiche", f"lot {brut.id}", exc)
            return None

    # -------------------------------------------------------------------- lots

    def _traiter_lot(
        self, brut: LotSource, attributs: AttributsVehicule | None
    ) -> Lot | LotEcarte | None:
        """Applique les regles metier a un lot et le transforme en sortie."""
        signal = _signal(brut, attributs)
        if motif := self._exclusions.motif(signal):
            self._compteurs.ecarter(motif)
            _LOG.debug("lot.ecarte", lot=brut.id, motif=motif)
            return LotEcarte(
                id=str(brut.id),
                url=_url_lot(self._config, brut),
                titre=brut.titre,
                motif=motif,
            )

        observation = self._etat.observer_lot(
            lot_id=brut.id,
            vente_id=brut.vente_id,
            url=_url_lot(self._config, brut),
            titre=brut.titre,
            reserve_aux_professionnels=brut.reserve_aux_professionnels,
            mise_a_prix=brut.mise_a_prix,
            enchere_en_cours=brut.enchere_en_cours,
            code_postal=brut.code_postal_retrait,
            departement=departement_depuis_code_postal(brut.code_postal_retrait) or "",
            horodatage=self._debut,
        )
        lot = _construire_lot(
            config=self._config,
            brut=brut,
            attributs=attributs,
            perimetre=self._perimetre,
            nouveau=observation.nouveau,
            enchere_a_bouge=observation.enchere_a_bouge,
        )
        if CHAMP_CRITIQUE in lot.champs_manquants:
            self._erreurs.append(
                ErreurRun(
                    etape="lot",
                    cible=str(brut.id),
                    type="ChampCritiqueIllisible",
                    message=(
                        "la mention « reserve aux professionnels » n'a pas pu etre lue ; "
                        "le lot est livre incomplet, ne pas decider dessus"
                    ),
                )
            )
        self._compteurs.lots_retenus += 1
        return lot

    # --------------------------------------------------------------- assemblage

    def _vente(self, source: VenteSource, retenus: list[Lot], ecartes: list[LotEcarte]) -> Vente:
        """Compose la vente, en deduisant son lieu du lieu de retrait de ses lots."""
        lieu, code_postal = _lieu_dominant(retenus)
        departement = departement_depuis_code_postal(code_postal) or ""
        return Vente(
            id=str(source.id),
            url=f"{self._config.reseau.base_url}/vente/{source.id}",
            intitule=source.intitule,
            dnid=str(source.id),
            date_ouverture=source.date_ouverture,
            date_cloture=source.date_cloture,
            lieu_retrait=lieu,
            code_postal=code_postal,
            departement=departement,
            dans_perimetre=self._perimetre.contient(code_postal, lieu),
            nb_lots=source.nb_lots or len(retenus) + len(ecartes),
        )

    def _document(
        self, ventes: list[Vente], lots: list[Lot], ecartes: list[LotEcarte]
    ) -> DocumentSortie:
        duree = (self._horloge() - self._debut).total_seconds()
        _LOG.info(
            "run.termine",
            ventes=self._compteurs.ventes_scannees,
            lots_vus=self._compteurs.lots_vus,
            retenus=self._compteurs.lots_retenus,
            ecartes=self._compteurs.lots_ecartes,
            motifs=self._compteurs.motifs,
            erreurs=len(self._erreurs),
            duree_s=round(duree, 1),
        )
        return DocumentSortie(
            run=Run(
                horodatage=self._debut,
                duree_secondes=max(duree, 0.0),
                ventes_scannees=self._compteurs.ventes_scannees,
                lots_vus=self._compteurs.lots_vus,
                lots_retenus=self._compteurs.lots_retenus,
                lots_ecartes=self._compteurs.lots_ecartes,
                erreurs=self._erreurs,
            ),
            ventes=ventes,
            lots=lots,
            ecartes=ecartes,
        )

    def _consigner(self, etape: str, cible: str, exc: Exception) -> None:
        """Consigne une anomalie : dans les logs ET dans le document de sortie."""
        _LOG.warning("run.anomalie", etape=etape, cible=cible, erreur=str(exc))
        self._erreurs.append(
            ErreurRun(etape=etape, cible=cible, type=type(exc).__name__, message=str(exc))
        )


# --------------------------------------------------------------------- helpers


def _empreinte(brut: LotSource) -> str:
    """Empreinte d'un lot : change si sa fiche a des chances d'avoir change."""
    graine = f"{brut.url_key}|{brut.titre}|{brut.description}"
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()[:32]


def _url_lot(config: Configuration, brut: LotSource) -> str:
    return f"{config.reseau.base_url}/lot/{brut.url_key}.html"


def _signal(brut: LotSource, attributs: AttributsVehicule | None) -> SignalLot:
    """Reunit ce que les regles metier ont le droit de regarder."""
    return SignalLot(
        description=brut.description,
        kilometrage=attributs.kilometrage if attributs else None,
        a_une_cle=attributs.a_une_cle if attributs else None,
        certificat_immatriculation=attributs.certificat_immatriculation if attributs else None,
        genre=attributs.genre if attributs else None,
        annee_mise_en_circulation=attributs.annee_mise_en_circulation if attributs else None,
        vhu_declare=attributs.vhu_declare if attributs else None,
        immatriculable_a_nouveau=attributs.immatriculable_a_nouveau if attributs else None,
        non_conforme=attributs.non_conforme if attributs else None,
    )


def _lieu_dominant(lots: list[Lot]) -> tuple[str, str]:
    """Lieu de retrait le plus represente parmi les lots d'une vente."""
    compte: dict[tuple[str, str], int] = {}
    for lot in lots:
        cle = (lot.lieu_retrait, lot.code_postal)
        compte[cle] = compte.get(cle, 0) + 1
    if not compte:
        return "", ""
    return max(compte.items(), key=lambda item: item[1])[0]


def _tva_recuperable(libelle: str) -> bool | None:
    """Interprete l'attribut TVA. `None` quand la source ne tranche pas."""
    aplati = texte.normaliser(libelle)
    if not aplati:
        return None
    if aplati in {"aucun", "aucune", "0", "exonere", "exoneree"}:
        return False
    if "tva" in aplati or any(c.isdigit() for c in aplati):
        return True
    return None


def _construire_lot(
    *,
    config: Configuration,
    brut: LotSource,
    attributs: AttributsVehicule | None,
    perimetre: Perimetre,
    nouveau: bool,
    enchere_a_bouge: bool,
) -> Lot:
    """Assemble le lot du contrat de sortie a partir de toutes ses sources."""
    lieu, code_postal, description = _contexte(brut, attributs)
    return Lot(
        id=str(brut.id),
        url=_url_lot(config, brut),
        vente_id=str(brut.vente_id),
        numero=brut.numero,
        titre=brut.titre,
        categorie=config.filtres.categorie_vehicules,
        reserve_aux_professionnels=brut.reserve_aux_professionnels,
        **_champs_vehicule(brut, attributs, description),
        mise_a_prix=brut.mise_a_prix,
        enchere_en_cours=brut.enchere_en_cours,
        # La source ne publie ni le nombre d'encherisseurs ni les frais
        # acheteur par lot : `null` signifie ici « absent de la source ».
        nb_encherisseurs=None,
        frais_acheteur_pct=None,
        lieu_retrait=lieu,
        code_postal=code_postal,
        departement=departement_depuis_code_postal(code_postal) or "",
        dates_visite=texte.extraire_dates_visite(description) or "",
        description_integrale=description,
        hors_perimetre=not perimetre.contient(code_postal, lieu),
        nouveau_depuis_dernier_run=nouveau,
        enchere_a_bouge=enchere_a_bouge,
        champs_manquants=_champs_manquants(brut, attributs),
    )


def _contexte(brut: LotSource, attributs: AttributsVehicule | None) -> tuple[str, str, str]:
    """Lieu, code postal et description, la liste primant sur la fiche detaillee."""
    code_postal = brut.code_postal_retrait or (attributs.code_postal_retrait if attributs else "")
    lieu = brut.ville_retrait or (attributs.ville_retrait if attributs else "")
    description = brut.description or (attributs.description if attributs else "")
    return lieu, code_postal, description


def _champs_manquants(brut: LotSource, attributs: AttributsVehicule | None) -> list[str]:
    """Champs presents dans la source mais inexploitables, ou fiche absente."""
    manquants = list(brut.champs_illisibles)
    if attributs is None:
        manquants.append("fiche_detaillee")
    else:
        manquants.extend(attributs.champs_illisibles)
    return sorted(set(manquants))


def _champs_vehicule(
    brut: LotSource, attributs: AttributsVehicule | None, description: str
) -> dict[str, Any]:
    """Caracteristiques du vehicule : attributs structures, puis texte libre."""
    return {
        "marque": attributs.marque if attributs else "",
        "modele": attributs.modele if attributs else "",
        "version": _version(brut.titre, attributs),
        "premiere_mise_en_circulation": (
            attributs.premiere_mise_en_circulation if attributs else ""
        ),
        "kilometrage": _kilometrage(attributs, description),
        "energie": attributs.energie if attributs else "",
        "boite": attributs.boite if attributs else "",
        "puissance_fiscale": texte.extraire_puissance_fiscale(description),
        "vin": texte.extraire_vin(description) or "",
        "crit_air": texte.extraire_crit_air(description) or "",
        "controle_technique": (
            texte.extraire_controle_technique(description) or _ct_structure(attributs)
        ),
        "carte_grise": attributs.certificat_immatriculation if attributs else None,
        "cles": attributs.a_une_cle if attributs else None,
        "etat_declare": texte.extraire_etat_declare(description) or "",
        "tva_recuperable": _tva_recuperable(attributs.tva if attributs else ""),
    }


def _version(titre: str, attributs: AttributsVehicule | None) -> str:
    """Ce qui reste du titre une fois la marque et le modele retires."""
    if attributs is None:
        return ""
    reste = titre
    for mot in (attributs.marque, attributs.modele):
        if mot:
            reste = reste.replace(mot, "").replace(mot.title(), "")
    return " ".join(reste.split())


def _kilometrage(attributs: AttributsVehicule | None, description: str) -> int | None:
    """Kilometrage structure s'il existe, sinon celui annonce dans la description."""
    if attributs and attributs.kilometrage:
        return attributs.kilometrage
    return texte.extraire_kilometrage(description)


def _ct_structure(attributs: AttributsVehicule | None) -> str:
    """Mention de controle technique deduite de l'attribut booleen."""
    if attributs is None or attributs.controle_technique is None:
        return ""
    return "présent" if attributs.controle_technique else "absent"


def _memo_depuis_attributs(attributs: AttributsVehicule) -> dict[str, Any]:
    """Forme serialisable d'une fiche, pour le cache SQLite."""
    return {
        champ: getattr(attributs, champ)
        for champ in AttributsVehicule.__dataclass_fields__
        if champ != "attributs_bruts"
    }


def _attributs_depuis_memo(memo: Mapping[str, Any]) -> AttributsVehicule | None:
    """Reconstruit une fiche depuis le cache.

    Rend `None` si la forme memorisee ne correspond plus au modele courant —
    cas d'un cache ecrit par une version anterieure. L'appelant retelecharge.
    """
    donnees = dict(memo)
    donnees["champs_illisibles"] = tuple(donnees.get("champs_illisibles") or ())
    donnees["attributs_bruts"] = {}
    try:
        return AttributsVehicule(**donnees)
    except TypeError:
        return None
