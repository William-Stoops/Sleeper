"""Configuration versionnee, validee au demarrage.

Aucune valeur metier n'est en dur dans le code : perimetre, seuils, regles,
chemins et cadence vivent ici. Une configuration invalide arrete l'outil avec
un message explicite — un scan silencieusement vide serait pire, puisqu'il
donnerait a croire qu'il n'y a rien a acheter.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sleeper.domain.codes import StatutVente
from sleeper.domain.exclusions import REGLES_PAR_DEFAUT, MoteurExclusions
from sleeper.domain.perimetre import Perimetre
from sleeper.errors import ConfigurationError

_DEPARTEMENT = re.compile(r"^(?:\d{2,3}|2A|2B)$")
_PAYS = re.compile(r"^[A-Z]{2}$")

#: Cadence plancher. Le site est un service public sous WAF : une seule
#: execution par jour, quelques requetes par seconde au maximum.
DELAI_MINIMUM_S: Final = 0.5
CONCURRENCE_MAXIMALE: Final = 3

_CODES_REGLES: Final = frozenset(r.code for r in REGLES_PAR_DEFAUT)


def _exiger_regles_connues(codes: set[str]) -> None:
    """Refuse toute reference a une regle qui n'existe pas.

    Une faute de frappe dans la configuration ne doit jamais se traduire par
    une regle silencieusement inoperante.
    """
    if inconnues := codes - _CODES_REGLES:
        raise ValueError(
            f"regle(s) d'exclusion inconnue(s) : {', '.join(sorted(inconnues))}. "
            f"Regles disponibles : {', '.join(sorted(_CODES_REGLES))}"
        )


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Reseau(_Section):
    """Transport et politesse."""

    base_url: str = "https://encheres-domaine.gouv.fr"
    user_agent: str
    concurrence_max: Annotated[int, Field(ge=1, le=CONCURRENCE_MAXIMALE)] = 2
    delai_entre_requetes_s: Annotated[float, Field(ge=DELAI_MINIMUM_S)] = 1.5
    timeout_s: Annotated[float, Field(gt=0)] = 30.0
    tentatives_max: Annotated[int, Field(ge=1, le=8)] = 4
    backoff_initial_s: Annotated[float, Field(gt=0)] = 1.0
    backoff_facteur: Annotated[float, Field(ge=1.0)] = 2.0
    backoff_max_s: Annotated[float, Field(gt=0)] = 30.0
    session_ttl_minutes: Annotated[int, Field(ge=1)] = 45
    # Faux par defaut, et ce n'est pas un oubli : en mode headless, Chromium
    # annonce « HeadlessChrome » dans son User-Agent, ce que le pare-feu du
    # site refuse. Plutot que de masquer ce jeton — ce serait un deguisement —
    # on ouvre un vrai navigateur. Voir README, « Limites assumees ».
    navigateur_headless: bool = False

    @field_validator("user_agent")
    @classmethod
    def _doit_etre_identifiable(cls, valeur: str) -> str:
        """Un robot qui se fait passer pour un navigateur n'est pas poli."""
        if "@" not in valeur and "http" not in valeur.lower():
            raise ValueError(
                "user_agent doit etre identifiable : y faire figurer une adresse "
                "de contact ou une URL, par exemple "
                "'SleeperBot/0.1 (+mailto:contact@exemple.fr)'"
            )
        return valeur


class PerimetreConfig(_Section):
    """Liste blanche geographique, fondee sur le lieu de retrait."""

    # frozenset plutot que list : la configuration est gelee, l'appartenance
    # est la seule operation utile, et l'ordre n'a aucun sens ici.
    departements: Annotated[frozenset[str], Field(min_length=1)]
    pays_etrangers: frozenset[str] = frozenset({"BE", "LU"})

    @field_validator("departements", mode="before")
    @classmethod
    def _codes_valides(cls, valeurs: object) -> object:
        if not isinstance(valeurs, list | frozenset | set | tuple):
            return valeurs
        propres = [str(v).strip().upper() for v in valeurs]
        if invalides := [v for v in propres if not _DEPARTEMENT.match(v)]:
            raise ValueError(f"code(s) departement invalide(s) : {', '.join(invalides)}")
        return frozenset(propres)

    @field_validator("pays_etrangers", mode="before")
    @classmethod
    def _pays_iso(cls, valeurs: object) -> object:
        if not isinstance(valeurs, list | frozenset | set | tuple):
            return valeurs
        propres = [str(v).strip().upper() for v in valeurs]
        if invalides := [v for v in propres if not _PAYS.match(v)]:
            raise ValueError(f"code(s) pays non ISO-3166 alpha-2 : {', '.join(invalides)}")
        return frozenset(propres)


class Exclusions(_Section):
    """Selection et enrichissement des regles metier."""

    regles_actives: list[str] = Field(default_factory=list)
    formulations_supplementaires: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("regles_actives")
    @classmethod
    def _selection_connue(cls, valeur: list[str]) -> list[str]:
        _exiger_regles_connues(set(valeur))
        return valeur

    @field_validator("formulations_supplementaires")
    @classmethod
    def _ajouts_connus(cls, valeur: dict[str, list[str]]) -> dict[str, list[str]]:
        _exiger_regles_connues(set(valeur))
        return valeur


class Filtres(_Section):
    """Ce que le run balaye avant meme d'appliquer les regles metier."""

    categorie_vehicules: str = "Véhicules"
    statuts_vente: list[int] = Field(
        default_factory=lambda: [int(s) for s in StatutVente.ouvertes()]
    )
    lots_par_page: Annotated[int, Field(ge=1, le=50)] = 8


class Sortie(_Section):
    """Destination du document produit."""

    repertoire: Path
    nom_lien_courant: str = "latest.json"
    digest: bool = True
    nom_digest: str = "latest.md"


class Etat(_Section):
    """Base d'etat persistante."""

    base: Path
    conserver_historique_encheres: bool = True


class Journalisation(_Section):
    """Logs structures."""

    niveau: str = "INFO"
    format: str = "json"

    @field_validator("niveau")
    @classmethod
    def _niveau_connu(cls, valeur: str) -> str:
        connus = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        majuscule = valeur.strip().upper()
        if majuscule not in connus:
            raise ValueError(f"niveau de journalisation inconnu : {valeur}")
        return majuscule

    @field_validator("format")
    @classmethod
    def _format_connu(cls, valeur: str) -> str:
        if valeur not in {"json", "console"}:
            raise ValueError("format de journalisation attendu : 'json' ou 'console'")
        return valeur


class Configuration(BaseModel):
    """Configuration complete de l'outil."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reseau: Reseau
    perimetre: PerimetreConfig
    exclusions: Exclusions = Field(default_factory=Exclusions)
    filtres: Filtres = Field(default_factory=Filtres)
    sortie: Sortie
    etat: Etat
    journalisation: Journalisation = Field(default_factory=Journalisation)

    def perimetre_domaine(self) -> Perimetre:
        """Traduit la configuration en objet du domaine."""
        return Perimetre(
            departements=self.perimetre.departements,
            pays_etrangers=self.perimetre.pays_etrangers,
        )

    def moteur_exclusions(self) -> MoteurExclusions:
        """Assemble le moteur de regles : selection puis enrichissement."""
        actives = self.exclusions.regles_actives
        regles = (
            REGLES_PAR_DEFAUT
            if not actives
            else tuple(r for r in REGLES_PAR_DEFAUT if r.code in set(actives))
        )
        return MoteurExclusions.avec_ajouts(regles, self.exclusions.formulations_supplementaires)


def charger_configuration(chemin: Path) -> Configuration:
    """Lit et valide la configuration. Toute anomalie est terminale."""
    if not chemin.is_file():
        raise ConfigurationError(f"fichier de configuration introuvable : {chemin}")
    try:
        brut = tomllib.loads(chemin.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"TOML invalide dans {chemin} : {exc}") from exc
    except OSError as exc:
        raise ConfigurationError(f"lecture impossible de {chemin} : {exc}") from exc

    try:
        return Configuration.model_validate(brut)
    except ValidationError as exc:
        raise ConfigurationError(_expliquer(chemin, exc)) from exc


def _expliquer(chemin: Path, exc: ValidationError) -> str:
    """Rend l'erreur pydantic lisible par un operateur, pas par un developpeur."""
    lignes = [f"configuration invalide dans {chemin} :"]
    for erreur in exc.errors():
        emplacement = ".".join(str(p) for p in erreur["loc"]) or "(racine)"
        lignes.append(f"  - {emplacement} : {erreur['msg']}")
    return "\n".join(lignes)
