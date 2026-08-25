"""Versioned configuration, validated at startup.

No business value is hard-coded: scope, thresholds, rules, paths and pacing
all live here. An invalid configuration stops the tool with an explicit
message — a silently empty scan would be worse, since it would suggest there
is nothing to buy.

**Identifiers are English, the TOML keys are French.** The configuration file
is a user interface: the operator edits it daily and the documentation
describes it in French. The keys are therefore pinned as aliases.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sleeper.domain.codes import SaleStatus
from sleeper.domain.exclusions import DEFAULT_RULES, ExclusionEngine
from sleeper.domain.territory import Perimeter
from sleeper.errors import ConfigurationError

_DEPARTMENT = re.compile(r"^(?:\d{2,3}|2A|2B)$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")

#: Pacing floor. The site is a public service behind a WAF: one run a day,
#: and never more than one request every half-second.
#:
#: There is no concurrency setting: requests are issued sequentially. The
#: transport is a browser, whose synchronous API is single-threaded, and a
#: global rate limit is a stricter guarantee than a cap on simultaneous
#: requests anyway.
MINIMUM_DELAY_S: Final = 0.5

_RULE_CODES: Final = frozenset(r.code for r in DEFAULT_RULES)


def _require_known_rules(codes: set[str]) -> None:
    """Reject any reference to a rule that does not exist.

    A typo in the configuration must never turn into a silently inert rule.
    """
    if unknown := codes - _RULE_CODES:
        raise ValueError(
            f"règle(s) d'exclusion inconnue(s) : {', '.join(sorted(unknown))}. "
            f"Règles disponibles : {', '.join(sorted(_RULE_CODES))}"
        )


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Network(_Section):
    """Transport and politeness."""

    base_url: str = "https://encheres-domaine.gouv.fr"
    user_agent: str
    delay_between_requests_s: Annotated[float, Field(ge=MINIMUM_DELAY_S)] = Field(
        alias="delai_entre_requetes_s", default=1.5
    )
    timeout_s: Annotated[float, Field(gt=0)] = 30.0
    max_attempts: Annotated[int, Field(ge=1, le=8)] = Field(alias="tentatives_max", default=4)
    backoff_initial_s: Annotated[float, Field(gt=0)] = 1.0
    backoff_factor: Annotated[float, Field(ge=1.0)] = Field(alias="backoff_facteur", default=2.0)
    backoff_max_s: Annotated[float, Field(gt=0)] = 30.0
    session_ttl_minutes: Annotated[int, Field(ge=1)] = 45
    # False by default, and that is not an oversight: in headless mode Chromium
    # announces "HeadlessChrome" in its User-Agent, which the site's firewall
    # refuses. Rather than masking that token — which would be a disguise — a
    # real browser window is opened. See README, "Limites assumées".
    headless_browser: bool = Field(alias="navigateur_headless", default=False)

    @field_validator("user_agent")
    @classmethod
    def _must_be_identifiable(cls, value: str) -> str:
        """A robot pretending to be a browser is not being polite."""
        if "@" not in value and "http" not in value.lower():
            raise ValueError(
                "user_agent doit être identifiable : y faire figurer une adresse "
                "de contact ou une URL, par exemple "
                "« SleeperBot/0.1 (+mailto:contact@exemple.fr) »"
            )
        return value


class ScopeConfig(_Section):
    """Geographic allow-list, based on the collection point."""

    # frozenset rather than list: the configuration is frozen, membership is
    # the only useful operation, and order carries no meaning here.
    departments: Annotated[frozenset[str], Field(min_length=1)] = Field(alias="departements")
    foreign_countries: frozenset[str] = Field(
        alias="pays_etrangers", default=frozenset({"BE", "LU"})
    )

    @field_validator("departments", mode="before")
    @classmethod
    def _valid_codes(cls, values: object) -> object:
        if not isinstance(values, list | frozenset | set | tuple):
            return values
        cleaned = [str(v).strip().upper() for v in values]
        if invalid := [v for v in cleaned if not _DEPARTMENT.match(v)]:
            raise ValueError(f"code(s) département invalide(s) : {', '.join(invalid)}")
        return frozenset(cleaned)

    @field_validator("foreign_countries", mode="before")
    @classmethod
    def _iso_countries(cls, values: object) -> object:
        if not isinstance(values, list | frozenset | set | tuple):
            return values
        cleaned = [str(v).strip().upper() for v in values]
        if invalid := [v for v in cleaned if not _COUNTRY.match(v)]:
            raise ValueError(f"code(s) pays non ISO-3166 alpha-2 : {', '.join(invalid)}")
        return frozenset(cleaned)


class ExclusionsConfig(_Section):
    """Selection and enrichment of the business rules."""

    active_rules: list[str] = Field(alias="regles_actives", default_factory=list)
    extra_phrases: dict[str, list[str]] = Field(
        alias="formulations_supplementaires", default_factory=dict
    )

    @field_validator("active_rules")
    @classmethod
    def _known_selection(cls, value: list[str]) -> list[str]:
        _require_known_rules(set(value))
        return value

    @field_validator("extra_phrases")
    @classmethod
    def _known_extras(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        _require_known_rules(set(value))
        return value


class FiltersConfig(_Section):
    """What the run sweeps before business rules even apply."""

    vehicle_category: str = Field(alias="categorie_vehicules", default="Véhicules")
    sale_statuses: list[int] = Field(
        alias="statuts_vente",
        default_factory=lambda: [int(s) for s in SaleStatus.open_statuses()],
    )
    # Applies to the sales list as well as the lots list: it is the page size
    # used by the site's own application, and the firewall does not accept
    # departures from it.
    page_size: Annotated[int, Field(ge=1, le=50)] = Field(alias="taille_de_page", default=8)


class OutputConfig(_Section):
    """Destination of the produced document."""

    directory: Path = Field(alias="repertoire")
    current_link_name: str = Field(alias="nom_lien_courant", default="latest.json")
    digest: bool = True
    digest_name: str = Field(alias="nom_digest", default="latest.md")


class StateConfig(_Section):
    """Persistent state database."""

    database: Path = Field(alias="base")
    keep_bid_history: bool = Field(alias="conserver_historique_encheres", default=True)


class LoggingConfig(_Section):
    """Structured logging."""

    level: str = Field(alias="niveau", default="INFO")
    format: str = "json"

    @field_validator("level")
    @classmethod
    def _known_level(cls, value: str) -> str:
        known = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.strip().upper()
        if upper not in known:
            raise ValueError(f"niveau de journalisation inconnu : {value}")
        return upper

    @field_validator("format")
    @classmethod
    def _known_format(cls, value: str) -> str:
        if value not in {"json", "console"}:
            raise ValueError("format de journalisation attendu : « json » ou « console »")
        return value


class Configuration(BaseModel):
    """Full configuration of the tool."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    network: Network = Field(alias="reseau")
    scope: ScopeConfig = Field(alias="perimetre")
    exclusions: ExclusionsConfig = Field(default_factory=ExclusionsConfig)
    filters: FiltersConfig = Field(alias="filtres", default_factory=FiltersConfig)
    output: OutputConfig = Field(alias="sortie")
    state: StateConfig = Field(alias="etat")
    logging: LoggingConfig = Field(alias="journalisation", default_factory=LoggingConfig)

    def perimeter(self) -> Perimeter:
        """Turn the configuration into a domain object."""
        return Perimeter(
            departments=self.scope.departments,
            foreign_countries=self.scope.foreign_countries,
        )

    def exclusion_engine(self) -> ExclusionEngine:
        """Assemble the rule engine: selection, then enrichment."""
        active = self.exclusions.active_rules
        rules = (
            DEFAULT_RULES
            if not active
            else tuple(r for r in DEFAULT_RULES if r.code in set(active))
        )
        return ExclusionEngine.with_extra_phrases(rules, self.exclusions.extra_phrases)


def load_configuration(path: Path) -> Configuration:
    """Read and validate the configuration. Any anomaly is terminal."""
    if not path.is_file():
        raise ConfigurationError(f"fichier de configuration introuvable : {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"TOML invalide dans {path} : {exc}") from exc
    except OSError as exc:
        raise ConfigurationError(f"lecture impossible de {path} : {exc}") from exc

    try:
        return Configuration.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(_explain(path, exc)) from exc


def _explain(path: Path, exc: ValidationError) -> str:
    """Render the pydantic error for an operator, not for a developer."""
    lines = [f"configuration invalide dans {path} :"]
    for error in exc.errors():
        location = ".".join(str(p) for p in error["loc"]) or "(racine)"
        lines.append(f"  - {location} : {error['msg']}")
    return "\n".join(lines)
