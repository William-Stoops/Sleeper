"""Acquisition et mise en cache de la session du site.

Le site sert un challenge JavaScript avant toute donnee : un client HTTP nu
ne recoit que « This website requires JS enabled and cookies ». Un vrai
navigateur execute le script du site et obtient les cookies de session, comme
n'importe quel visiteur.

C'est la seule raison d'etre de Playwright dans le run quotidien. Aucun
challenge n'est resolu par Sleeper : le navigateur fait ce que fait un
navigateur, et rien de plus. Si le site presente un CAPTCHA, l'acquisition
echoue et l'operateur en est informe.

La session est mise en cache sur disque et renouvelee a l'expiration, pour
que le nombre d'ouvertures de navigateur reste marginal.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from sleeper.config import Reseau
from sleeper.errors import SessionError

_LOG = structlog.get_logger(__name__)

#: Cookie sans lequel la passerelle refuse de repondre.
COOKIE_REQUIS = "bot_mitigation_cookie"

#: Marqueurs d'un challenge non resolvable sans intervention humaine.
_MARQUEURS_CAPTCHA = ("not a robot", "altcha", "captcha")


@dataclass(frozen=True, slots=True)
class Session:
    """Une session du site : des cookies, et le client auquel ils ont ete delivres.

    Les deux sont indissociables. Un pare-feu applicatif considere qu'une
    session presentee par un autre client est une session detournee — et il a
    raison. On transporte donc le User-Agent avec les cookies.
    """

    cookies: Mapping[str, str] = field(default_factory=dict)
    user_agent: str = ""


class SessionNavigateur:
    """Fournit les cookies du site, en ouvrant un navigateur au besoin."""

    def __init__(
        self,
        reseau: Reseau,
        cache: Path,
        acquerir: Callable[[Reseau], Session] | None = None,
        maintenant: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reseau = reseau
        self._cache = cache
        self._acquerir = acquerir or _acquerir_par_navigateur
        self._maintenant = maintenant
        self._session: Session | None = None
        self._obtenus_a: datetime | None = None

    def session(self) -> Session:
        """Session valide, depuis la memoire, le cache disque, ou un navigateur."""
        if self._session is not None and not self._perimee(self._obtenus_a):
            return self._session
        if (depuis_disque := self._lire_cache()) is not None:
            self._session, self._obtenus_a = depuis_disque
            return self._session
        return self.renouveler()

    def renouveler(self) -> Session:
        """Ouvre un navigateur pour obtenir une session neuve."""
        _LOG.info("session.acquisition", motif="session absente ou expiree")
        session = self._acquerir(self._reseau)
        if COOKIE_REQUIS not in session.cookies:
            raise SessionError(
                f"session incomplete : cookie '{COOKIE_REQUIS}' absent. "
                "Le site a peut-etre change de protection ; rejouer "
                "tools/discover_api.py pour verifier."
            )
        self._session = session
        self._obtenus_a = self._maintenant()
        self._ecrire_cache(session, self._obtenus_a)
        _LOG.info("session.acquise", cookies=sorted(session.cookies))
        return session

    def _perimee(self, obtenus_a: datetime | None) -> bool:
        if obtenus_a is None:
            return True
        age = self._maintenant() - obtenus_a
        return age >= timedelta(minutes=self._reseau.session_ttl_minutes)

    def _lire_cache(self) -> tuple[Session, datetime] | None:
        """Relit une session mise en cache, en ignorant tout cache douteux."""
        if not self._cache.is_file():
            return None
        try:
            brut = json.loads(self._cache.read_text(encoding="utf-8"))
            obtenus_a = datetime.fromisoformat(brut["obtenus_a"])
            cookies = {str(k): str(v) for k, v in brut["cookies"].items()}
            session = Session(cookies=cookies, user_agent=str(brut.get("user_agent", "")))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            _LOG.warning("session.cache_illisible", chemin=str(self._cache))
            return None
        if self._perimee(obtenus_a) or COOKIE_REQUIS not in cookies:
            return None
        return session, obtenus_a

    def _ecrire_cache(self, session: Session, obtenus_a: datetime) -> None:
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        charge = {
            "obtenus_a": obtenus_a.isoformat(),
            "user_agent": session.user_agent,
            "cookies": dict(session.cookies),
        }
        self._cache.write_text(json.dumps(charge, indent=2), encoding="utf-8")
        # La session vaut authentification implicite : elle ne regarde que son
        # proprietaire.
        self._cache.chmod(0o600)


def _acquerir_par_navigateur(reseau: Reseau) -> Session:  # pragma: no cover
    """Ouvre la page d'accueil dans Chromium et recupere les cookies poses.

    Playwright n'est requis que pour cette fonction ; il vit dans l'extra
    `discovery` pour qu'un poste d'exploitation puisse s'en passer une fois la
    session mise en cache.

    Non couverte par les tests : elle pilote un vrai navigateur sur un site
    reel. Tout ce qui est testable — cache, expiration, cookie requis — vit
    dans `SessionNavigateur`, qui recoit cette fonction par injection.
    """
    try:
        # Import differé assumé : playwright vit dans l'extra `discovery`,
        # et un poste d'exploitation doit pouvoir s'en passer.
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depend de l'installation
        raise SessionError(
            "playwright est requis pour obtenir une session : "
            "uv sync --extra discovery && uv run playwright install chromium"
        ) from exc

    with sync_playwright() as pilote:
        navigateur = pilote.chromium.launch(headless=reseau.navigateur_headless)
        try:
            # On n'usurpe PAS le User-Agent : le navigateur annonce ce qu'il est.
            # C'est aussi ce qui rend la session utilisable ensuite en HTTP.
            contexte = navigateur.new_context(locale="fr-FR")
            page = contexte.new_page()
            page.goto(f"{reseau.base_url}/ventes", wait_until="networkidle", timeout=60_000)
            titre = (page.title() or "").lower()
            if any(marqueur in titre for marqueur in _MARQUEURS_CAPTCHA):
                raise SessionError(
                    "le site presente un CAPTCHA a l'ouverture. Sleeper ne le "
                    "resout pas : espacer les executions et relancer plus tard."
                )
            agent = str(page.evaluate("() => navigator.userAgent"))
            return Session(
                cookies={c["name"]: c["value"] for c in contexte.cookies()},
                user_agent=agent,
            )
        finally:
            navigateur.close()
