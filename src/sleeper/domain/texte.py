"""Normalisation et extraction sur le texte libre des fiches du Domaine.

Les descriptions sont saisies a la main par les agents des directions
regionales. Elles varient en casse, en accentuation, en ponctuation, et
comportent des fautes de frappe (« porfessionnels » a ete releve tel quel).
Aucune regle metier ne doit donc travailler sur la chaine brute : tout passe
d'abord par `normaliser`.
"""

from __future__ import annotations

import html as html_module
import re
import unicodedata
from typing import Final

_BALISE = re.compile(r"<[^>]+>")
_ESPACES = re.compile(r"\s+")
_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")

#: Un VIN normalise fait 17 caracteres, sans I, O ni Q. Les fiches anciennes
#: en publient parfois de plus courts : on accepte 11 a 17 pour ne pas perdre
#: l'information, la validation stricte n'est pas notre role.
_VIN = re.compile(
    r"(?:n\W{0,3}\s*s[ée]rie|vin|num[ée]ro\s+de\s+s[ée]rie)\s*:?\s*([A-HJ-NPR-Z0-9]{11,17})\b",
    re.IGNORECASE,
)
_PUISSANCE_FISCALE = re.compile(r"\b(\d{1,3})\s*(?:cv|c\.v\.|chevaux\s+fiscaux)\b", re.IGNORECASE)
_KILOMETRAGE = re.compile(
    r"\b(\d{1,3}(?:[\s.\u00a0]\d{3})+|\d{3,7})\s*(?:km|kms|kilom[eè]tres?)\b", re.IGNORECASE
)
_CRIT_AIR = re.compile(r"crit\W{0,2}air\W{0,3}(\d)", re.IGNORECASE)
#: Creneau de visite. Volontairement BORNE : la phrase qui suit la date
#: contient regulierement le nom et le telephone d'un agent public, qui n'ont
#: rien a faire dans un champ structure.
_JOUR = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
_DATE = (
    r"(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{1,2}(?:er)?\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t"
    r"|septembre|octobre|novembre|d[ée]cembre)(?:\s+\d{4})?)"
)
_HEURE = r"\d{1,2}\s*h(?:\s*\d{2})?"
_VISITE = re.compile(
    rf"(?:visites?|journ[ée]es?\s+de\s+visite)[^.]{{0,80}}?"
    rf"({_JOUR}\s+{_DATE}(?:\s*(?:de|entre)\s*{_HEURE}\s*(?:[àa]|et)\s*{_HEURE})?)",
    re.IGNORECASE,
)
_CT_DATE_COMPLETE = re.compile(
    r"(?:ct|contr[oô]le\s+technique)[^.\d]{0,30}(\d{2})[/\-.](\d{2})[/\-.](\d{4})", re.IGNORECASE
)
_CT_MOIS_ANNEE = re.compile(
    r"(?:ct|contr[oô]le\s+technique)[^.\d]{0,30}(\d{2})[/\-.](\d{4})", re.IGNORECASE
)

#: Formulations d'etat rencontrees dans les fiches du Domaine. On rend la
#: mention telle qu'elle est ecrite : c'est la matiere premiere de l'analyse
#: aval, pas une note attribuee par Sleeper.
_ETAT = re.compile(
    r"((?:tr[eè]s\s+)?(?:bon|mauvais|excellent|moyen)\s+[ée]tat(?:\s+g[ée]n[ée]ral)?"
    r"|[ée]tat\s+d\W?usage"
    r"|r[ée]parations?\s+[àa]\s+pr[ée]voir"
    r"|entretien\s+[àa]\s+pr[ée]voir)",
    re.IGNORECASE,
)

_MOIS_MAX: Final = 12


def depuis_html(source: str | None) -> str:
    """Reduit un fragment HTML a son texte, entites et espaces insecables compris."""
    if not source:
        return ""
    sans_balise = _BALISE.sub(" ", source)
    decode = html_module.unescape(sans_balise).replace("\u00a0", " ")
    return _ESPACES.sub(" ", decode).strip()


def normaliser(source: str | None) -> str:
    """Rabat une chaine sur sa forme canonique : minuscules, sans accents ni ponctuation.

    C'est la seule forme sur laquelle les regles metier ont le droit de
    travailler. L'operation est idempotente.
    """
    if not source:
        return ""
    decompose = unicodedata.normalize("NFKD", source)
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    return _NON_ALPHANUM.sub(" ", sans_accent.lower()).strip()


def contient(source: str | None, expression: str) -> bool:
    """Teste la presence d'une expression, en mots entiers, sur la forme normalisee.

    Les mots entiers evitent qu'« charge » declenche sur « chargeur », piege
    reel sur des descriptions qui parlent de batteries et de plateaux.
    """
    aiguille = normaliser(expression)
    if not aiguille:
        return False
    motif = r"\b" + r"\s+".join(re.escape(mot) for mot in aiguille.split()) + r"\b"
    return re.search(motif, normaliser(source)) is not None


def extraire_vin(source: str | None) -> str | None:
    """Recupere le numero de serie annonce dans la description."""
    trouve = _VIN.search(source or "")
    return trouve.group(1).upper() if trouve else None


def extraire_puissance_fiscale(source: str | None) -> int | None:
    """Recupere la puissance fiscale en chevaux (« 06 cv »)."""
    trouve = _PUISSANCE_FISCALE.search(source or "")
    return int(trouve.group(1)) if trouve else None


def extraire_kilometrage(source: str | None) -> int | None:
    """Recupere un kilometrage, quel que soit le separateur de milliers employe."""
    trouve = _KILOMETRAGE.search(source or "")
    if not trouve:
        return None
    return int(re.sub(r"[\s.\u00a0]", "", trouve.group(1)))


def extraire_crit_air(source: str | None) -> str | None:
    """Recupere le niveau de vignette Crit'Air."""
    trouve = _CRIT_AIR.search(source or "")
    return trouve.group(1) if trouve else None


def extraire_controle_technique(source: str | None) -> str | None:
    """Recupere la date du dernier controle technique, en ISO.

    Renvoie `AAAA-MM-JJ` quand le jour est connu, `AAAA-MM` sinon, et `None`
    quand la description ne date pas le controle.
    """
    complet = _CT_DATE_COMPLETE.search(source or "")
    if complet:
        jour, mois, annee = complet.groups()
        return f"{annee}-{mois}-{jour}"
    partiel = _CT_MOIS_ANNEE.search(source or "")
    if partiel:
        mois, annee = partiel.groups()
        if 1 <= int(mois) <= _MOIS_MAX:
            return f"{annee}-{mois}"
    return None


def extraire_dates_visite(source: str | None) -> str | None:
    """Recupere le creneau de visite tel qu'il est redige, sans reformulation."""
    trouve = _VISITE.search(source or "")
    if not trouve:
        return None
    return _ESPACES.sub(" ", trouve.group(1)).strip(" ,;")


def extraire_etat_declare(source: str | None) -> str | None:
    """Recupere la mention d'etat telle qu'elle est redigee, sans reformulation."""
    trouve = _ETAT.search(source or "")
    return _ESPACES.sub(" ", trouve.group(1)).strip() if trouve else None
