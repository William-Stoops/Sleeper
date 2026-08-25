"""Regles d'exclusion metier.

Deux sources de verite, dans cet ordre :

1. les attributs structures de la fiche (`vehicle_has_a_key`, `vhu_declared`…),
   qui sont fiables ;
2. le texte libre de la description, qui ne l'est pas — il est saisi a la main
   par des agents differents selon la direction regionale, et comporte des
   fautes de frappe releees en production (« porfessionnels »).

Chaque regle porte donc des expressions declenchantes ET des contre-expressions
qui l'annulent. Ce choix est volontairement explicite plutot qu'heuristique :
« sans choc apparent » ne doit pas ecarter un lot sain, et on veut pouvoir
lire, tester et enrichir la liste sans deviner ce que fait un analyseur.

Les formulations reconnues sont documentees dans docs/regles-metier.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from sleeper.domain import texte
from sleeper.domain.codes import GENRES_HORS_CIBLE

#: Millesime en deca duquel un vehicule releve de la collection, pas du negoce.
ANNEE_COLLECTION: Final = 1990


@dataclass(frozen=True, slots=True)
class SignalLot:
    """Ce qu'une regle a le droit de regarder pour trancher.

    Volontairement pauvre : une regle ne voit ni les prix, ni le perimetre, ni
    l'etat de la vente. Elle ne juge que le bien.
    """

    description: str
    kilometrage: int | None
    a_une_cle: bool | None
    certificat_immatriculation: bool | None
    genre: str | None
    annee_mise_en_circulation: int | None
    vhu_declare: bool | None
    immatriculable_a_nouveau: bool | None
    non_conforme: bool | None


@dataclass(frozen=True, slots=True)
class Regle:
    """Une regle d'exclusion nommee, testable et extensible."""

    code: str
    libelle: str
    expressions: tuple[str, ...] = ()
    contre_expressions: tuple[str, ...] = ()

    def declenche(self, signal: SignalLot) -> bool:
        """Applique la regle. Le predicat structure passe avant le texte."""
        if self._verdict_structure(signal) is True:
            return True
        if any(texte.contient(signal.description, c) for c in self.contre_expressions):
            return False
        return any(texte.contient(signal.description, e) for e in self.expressions)

    def _verdict_structure(self, signal: SignalLot) -> bool | None:
        """Verdict issu des attributs fiables. `None` = la regle n'en a pas."""
        return _VERDICTS_STRUCTURES.get(self.code, _sans_verdict)(signal)


def _sans_verdict(_: SignalLot) -> bool | None:
    return None


def _kilometrage_absent(signal: SignalLot) -> bool | None:
    """Un compteur a zero n'est pas un kilometrage : c'est une absence de saisie."""
    if signal.kilometrage:
        return False
    return None if texte.extraire_kilometrage(signal.description) else True


def _sans_cle(signal: SignalLot) -> bool | None:
    return None if signal.a_une_cle is None else not signal.a_une_cle


def _sans_certificat(signal: SignalLot) -> bool | None:
    if signal.certificat_immatriculation is None:
        return None
    return not signal.certificat_immatriculation


def _non_roulant(signal: SignalLot) -> bool | None:
    if signal.immatriculable_a_nouveau is False:
        return True
    return None


def _epave(signal: SignalLot) -> bool | None:
    return True if signal.vhu_declare else None


def _genre_hors_cible(signal: SignalLot) -> bool | None:
    if not signal.genre:
        return None
    return True if signal.genre.strip().upper() in GENRES_HORS_CIBLE else None


def _collection(signal: SignalLot) -> bool | None:
    annee = signal.annee_mise_en_circulation
    if annee is None:
        return None
    return annee < ANNEE_COLLECTION


_VERDICTS_STRUCTURES: Final = {
    "kilometrage_inconnu": _kilometrage_absent,
    "sans_cle": _sans_cle,
    "sans_certificat_immatriculation": _sans_certificat,
    "non_roulant": _non_roulant,
    "epave_ou_pieces": _epave,
    "genre_hors_cible": _genre_hors_cible,
    "collection_avant_1990": _collection,
}


#: L'ordre est significatif : c'est celui dans lequel les motifs sont evalues,
#: et donc celui qui rend le verdict reproductible pour un lot cumulant
#: plusieurs defauts.
REGLES_PAR_DEFAUT: Final[tuple[Regle, ...]] = (
    Regle(
        code="genre_hors_cible",
        libelle="Genre de vehicule hors cible (deux-roues, quadricycle, agricole, remorque)",
        expressions=(
            "moto",
            "motocyclette",
            "scooter",
            "cyclomoteur",
            "quad",
            "quadricycle",
            "remorque",
            "semi remorque",
            "caravane",
            "tracteur agricole",
            "engin agricole",
            "moissonneuse",
            "tondeuse autoportee",
            "sans permis",
            "voiturette",
        ),
        contre_expressions=("porte moto", "remorque non comprise"),
    ),
    Regle(
        code="collection_avant_1990",
        libelle="Vehicule de collection anterieur a 1990",
        expressions=("vehicule de collection", "carte grise de collection"),
    ),
    Regle(
        code="sans_cle",
        libelle="Vehicule sans cle",
        expressions=(
            "sans cle",
            "sans cles",
            "sans clef",
            "sans clefs",
            "cle absente",
            "cles absentes",
            "clef absente",
            "absence de cle",
            "absence de cles",
            "absence de clef",
            "pas de cle",
            "pas de cles",
            "pas de clef",
            "aucune cle",
            "cle manquante",
            "cles manquantes",
        ),
        contre_expressions=("avec cle", "avec cles", "avec clef", "presence de cle"),
    ),
    Regle(
        code="sans_certificat_immatriculation",
        libelle="Absence de certificat d'immatriculation",
        expressions=(
            "sans carte grise",
            "sans cg",
            "cg absente",
            "carte grise absente",
            "absence de carte grise",
            "absence de certificat d immatriculation",
            "sans certificat d immatriculation",
            "pas de carte grise",
            "pas de cg",
            "carte grise manquante",
            "cg non fournie",
            "carte grise non fournie",
            "vehicule non immatricule",
        ),
        contre_expressions=("avec cg", "avec carte grise", "carte grise fournie"),
    ),
    Regle(
        code="epave_ou_pieces",
        libelle="Epave ou vente pour pieces",
        expressions=(
            "epave",
            "pour pieces",
            "pieces detachees",
            "vehicule hors d usage",
            "vhu",
            "destruction obligatoire",
            "a detruire",
            "cession pour destruction",
        ),
        contre_expressions=("pieces jointes", "pieces du dossier"),
    ),
    Regle(
        code="non_roulant",
        libelle="Vehicule non roulant",
        expressions=(
            "non roulant",
            "ne roule pas",
            "ne demarre pas",
            "vehicule immobilise",
            "etat non roulant",
            "hors etat de rouler",
            "ne circule plus",
        ),
        # Une contre-expression ne doit jamais etre un fragment de son propre
        # declencheur : « roulant » seul annulerait « non roulant ».
        contre_expressions=(
            "vehicule roulant",
            "en etat de rouler",
            "demarre correctement",
            "demarre et roule",
        ),
    ),
    Regle(
        code="moteur_hors_service",
        libelle="Moteur hors service",
        expressions=(
            "moteur hors service",
            "moteur hs",
            "moteur casse",
            "moteur a refaire",
            "moteur serre",
            "moteur bloque",
            "joint de culasse hs",
            "boite hs",
        ),
        contre_expressions=("moteur en bon etat", "moteur revise"),
    ),
    Regle(
        code="choc_ou_accident",
        libelle="Choc, accident ou degats de carrosserie",
        expressions=(
            "accidente",
            "accidentee",
            "vehicule accidente",
            "choc avant",
            "choc arriere",
            "choc lateral",
            "degats de carrosserie",
            "degat de carrosserie",
            "carrosserie endommagee",
            "carrosserie abimee",
            "sinistre",
            "vehicule sinistre",
            "impacts de carrosserie",
        ),
        contre_expressions=(
            "sans choc",
            "aucun choc",
            "non accidente",
            "non accidentee",
            "aucun degat de carrosserie",
            "aucun degat",
            "sans degat",
            "carrosserie en bon etat",
        ),
    ),
    Regle(
        code="gage_ou_opposition",
        libelle="Gage ou opposition",
        expressions=(
            "gage",
            "gagee",
            "vehicule gage",
            "opposition",
            "saisie conservatoire",
            "situation administrative bloquee",
        ),
        contre_expressions=("sans gage", "non gage", "aucune opposition", "sans opposition"),
    ),
    Regle(
        code="kilometrage_inconnu",
        libelle="Kilometrage inconnu, non renseigne ou absent",
        expressions=(
            "kilometrage inconnu",
            "kilometrage non renseigne",
            "km inconnu",
            "compteur non fonctionnel",
            "compteur hs",
            "compteur bloque",
            "kilometrage non garanti",
            "compteur non fiable",
        ),
    ),
)


class MoteurExclusions:
    """Applique les regles dans l'ordre et rend le premier motif declenche."""

    def __init__(self, regles: Sequence[Regle]) -> None:
        self._regles = tuple(regles)

    @property
    def regles(self) -> tuple[Regle, ...]:
        return self._regles

    def motif(self, signal: SignalLot) -> str | None:
        """Code du motif d'exclusion, ou `None` si le lot est retenu."""
        for regle in self._regles:
            if regle.declenche(signal):
                return regle.code
        return None

    def libelle(self, code: str) -> str:
        """Libelle lisible d'un motif, pour la restitution."""
        for regle in self._regles:
            if regle.code == code:
                return regle.libelle
        raise KeyError(code)

    @classmethod
    def avec_ajouts(
        cls, regles: Sequence[Regle], ajouts: Mapping[str, Iterable[str]]
    ) -> MoteurExclusions:
        """Enrichit les regles avec les formulations rencontrees en production.

        Une cle inconnue est une erreur : une faute de frappe dans la
        configuration ne doit pas se traduire par une regle silencieusement
        inoperante.
        """
        connues = {r.code for r in regles}
        if inconnues := set(ajouts) - connues:
            raise KeyError(f"regle(s) d'exclusion inconnue(s) : {', '.join(sorted(inconnues))}")
        enrichies = [
            replace(r, expressions=r.expressions + tuple(ajouts.get(r.code, ()))) for r in regles
        ]
        return cls(enrichies)
