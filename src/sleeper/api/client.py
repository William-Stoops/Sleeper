"""Client HTTP d'exploitation.

Le run quotidien n'ouvre pas de navigateur : il appelle directement la
passerelle GraphQL avec les requetes exactes de l'application (voir
`operations`), en rejouant une session obtenue une fois par un vrai
navigateur.

Trois garanties portees par cette couche :

1. **Cadence.** Un cadenceur partage borne le debit global, quelle que soit
   la concurrence en amont. Le site est un service public : on ne le bouscule
   pas.
2. **Reprises.** Backoff exponentiel plafonne sur les defaillances de
   transport et les 5xx. Les 4xx definitifs ne sont pas reessayes : insister
   ne les guerira pas.
3. **Refus du contournement.** Si le site presente un challenge anti-robot,
   le client s'arrete NET, sans reprise et sans tentative de resolution.
   C'est une limite du projet, pas un incident a absorber.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any, Final, Protocol, Self

import httpx
import structlog

from sleeper.api.operations import CHEMIN_GRAPHQL, NOM_OPERATION
from sleeper.api.session import Session
from sleeper.config import Reseau
from sleeper.errors import ProtectionAntiRobotError, ReseauError

#: Signatures d'un CAPTCHA. TERMINALES : Sleeper ne les resout pas, et ne
#: reessaie pas — reessayer reviendrait a chercher a contourner.
_SIGNATURES_CAPTCHA: Final = (
    re.compile(r"not\s+a\s+robot", re.IGNORECASE),
    re.compile(r"altcha", re.IGNORECASE),
    re.compile(r"captcha", re.IGNORECASE),
)

#: Signatures d'une session simplement expiree : le site redemande son
#: challenge JavaScript d'entree. Un visiteur ordinaire le repasserait sans y
#: penser ; on renouvelle donc la session, UNE fois.
_SIGNATURES_SESSION_EXPIREE: Final = (
    re.compile(r"window\.location\.href\s*=\s*'/redirect_", re.IGNORECASE),
    re.compile(r"requires JS enabled and cookies", re.IGNORECASE),
)

_STATUTS_REESSAYABLES: Final = frozenset({408, 425, 429, 500, 502, 503, 504})
_STATUT_MINI_ERREUR: Final = 400

_LOG = structlog.get_logger(__name__)


class FournisseurSession(Protocol):
    """Source de la session acceptee par le site."""

    def session(self) -> Session:
        """Session courante, potentiellement issue d'un cache."""
        ...

    def renouveler(self) -> Session:
        """Force l'obtention d'une session neuve."""
        ...


class SessionStatique:
    """Session figee, utile aux tests et au rejeu d'une capture."""

    def __init__(self, cookies: Mapping[str, str], user_agent: str = "") -> None:
        self._session = Session(cookies=dict(cookies), user_agent=user_agent)

    def session(self) -> Session:
        return self._session

    def renouveler(self) -> Session:
        return self._session


def _corps_html(reponse: httpx.Response) -> str:
    """Debut du corps, uniquement si la reponse n'est pas du JSON."""
    if "json" in reponse.headers.get("content-type", "").lower():
        return ""
    return reponse.text[:2000]


def _est_captcha(reponse: httpx.Response) -> bool:
    """Le site demande une resolution humaine."""
    extrait = _corps_html(reponse)
    return any(signature.search(extrait) for signature in _SIGNATURES_CAPTCHA)


def _session_expiree(reponse: httpx.Response) -> bool:
    """Le site redemande simplement son challenge JavaScript d'entree."""
    extrait = _corps_html(reponse)
    return any(signature.search(extrait) for signature in _SIGNATURES_SESSION_EXPIREE)


def identifier(agent_navigateur: str, identification: str) -> str:
    """Compose le User-Agent d'exploitation.

    Sleeper rejoue la session d'un navigateur reel : masquer ce navigateur
    ferait echouer la session cote pare-feu, et pretendre etre autre chose
    serait faux. On annonce donc les deux — le client d'origine, et le robot
    qui s'en sert — de sorte qu'un administrateur du site puisse nous
    identifier et nous joindre.
    """
    if not agent_navigateur:
        return identification
    return f"{agent_navigateur} {identification}".strip()


class Cadenceur:
    """Limiteur de debit partage, sur pour un usage concurrent."""

    def __init__(
        self,
        delai_s: float,
        horloge: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._delai = delai_s
        self._horloge = horloge
        self._dormir = dormir
        self._verrou = threading.Lock()
        self._dernier: float | None = None

    def attendre(self) -> None:
        """Bloque le temps necessaire pour respecter le delai entre requetes."""
        with self._verrou:
            maintenant = self._horloge()
            if self._dernier is not None:
                reste = self._delai - (maintenant - self._dernier)
                if reste > 0:
                    self._dormir(reste)
                    maintenant = self._horloge()
            self._dernier = maintenant


class ClientDomaine:
    """Appelle la passerelle GraphQL du Domaine."""

    def __init__(
        self,
        reseau: Reseau,
        session: FournisseurSession,
        transport: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reseau = reseau
        self._session = session
        self._dormir = dormir
        self._cadenceur = Cadenceur(reseau.delai_entre_requetes_s, horloge, dormir)
        self._client = httpx.Client(
            base_url=reseau.base_url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
            timeout=reseau.timeout_s,
            transport=transport,
            follow_redirects=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        type_exc: type[BaseException] | None,
        valeur: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.fermer()

    def fermer(self) -> None:
        self._client.close()

    def interroger(self, requete: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Execute une operation GraphQL et rend son payload JSON."""
        params = {"query": requete, "variables": json.dumps(variables, separators=(",", ":"))}
        if operation := NOM_OPERATION.get(requete):
            params["operationName"] = operation

        derniere: Exception | None = None
        session_renouvelee = False
        for tentative in range(1, self._reseau.tentatives_max + 1):
            self._cadenceur.attendre()
            try:
                session = self._session.session()
                self._client.cookies.update(dict(session.cookies))
                self._client.headers["User-Agent"] = identifier(
                    session.user_agent, self._reseau.user_agent
                )
                reponse = self._client.get(CHEMIN_GRAPHQL, params=params)
            except httpx.HTTPError as exc:
                derniere = exc
            else:
                self._refuser_si_captcha(reponse)
                if _session_expiree(reponse) and not session_renouvelee:
                    _LOG.info("session.expiree", action="renouvellement")
                    self._session.renouveler()
                    session_renouvelee = True
                    continue
                if _session_expiree(reponse):
                    raise ReseauError(
                        "le site redemande son challenge JavaScript malgre une "
                        "session neuve : la protection a probablement change"
                    )
                if reponse.status_code < _STATUT_MINI_ERREUR:
                    return self._payload(reponse)
                if reponse.status_code not in _STATUTS_REESSAYABLES:
                    raise ReseauError(
                        f"reponse definitive {reponse.status_code} de la passerelle : "
                        f"{reponse.text[:200]}"
                    )
                derniere = ReseauError(f"statut {reponse.status_code}")
            if tentative < self._reseau.tentatives_max:
                self._dormir(self._attente(tentative))

        raise ReseauError(
            f"echec apres {self._reseau.tentatives_max} tentatives : {derniere}"
        ) from derniere

    def _attente(self, tentative: int) -> float:
        """Backoff exponentiel plafonne."""
        brut = self._reseau.backoff_initial_s * (self._reseau.backoff_facteur ** (tentative - 1))
        return min(brut, self._reseau.backoff_max_s)

    @staticmethod
    def _refuser_si_captcha(reponse: httpx.Response) -> None:
        """Arrete tout si le site presente un CAPTCHA.

        Sleeper ne resout aucun CAPTCHA et ne reessaie pas : reessayer
        reviendrait a chercher a le contourner.
        """
        if _est_captcha(reponse):
            raise ProtectionAntiRobotError(
                "le site presente un challenge anti-robot (WAF/CAPTCHA). "
                "Sleeper ne le contourne pas : espacer les executions, verifier "
                "la cadence configuree, puis relancer plus tard."
            )

    @staticmethod
    def _payload(reponse: httpx.Response) -> dict[str, Any]:
        try:
            charge = reponse.json()
        except ValueError as exc:
            raise ReseauError(
                f"reponse non JSON de la passerelle ({reponse.headers.get('content-type')}) : "
                f"{reponse.text[:200]}"
            ) from exc
        if not isinstance(charge, dict):
            raise ReseauError("payload JSON inattendu : objet attendu")
        return charge
