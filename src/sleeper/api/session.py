"""Acquisition and caching of the site session.

The site serves a JavaScript challenge before any data: a bare HTTP client
only ever receives "This website requires JS enabled and cookies". A real
browser runs the site's own script and obtains the session cookies, exactly
as any visitor would.

That is the sole reason Playwright takes part in the daily run. Sleeper
solves no challenge: the browser does what a browser does, and nothing more.
If the site serves a CAPTCHA, acquisition fails and the operator is told.

The session is cached on disk and renewed on expiry, so that opening a
browser stays a marginal event.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from sleeper.config import Network
from sleeper.errors import SessionError

_LOG = structlog.get_logger(__name__)

#: Cookie without which the gateway refuses to answer.
REQUIRED_COOKIE = "bot_mitigation_cookie"

#: Markers of a challenge no machine may resolve on its own.
_CAPTCHA_MARKERS = ("not a robot", "altcha", "captcha")


@dataclass(frozen=True, slots=True)
class Session:
    """A site session: cookies, and the client they were issued to.

    The two are inseparable. A web application firewall treats a session
    presented by a different client as a hijacked session — and it is right
    to. The User-Agent therefore travels with the cookies.
    """

    cookies: Mapping[str, str] = field(default_factory=dict)
    user_agent: str = ""


class BrowserSession:
    """Provides the site cookies, opening a browser when needed."""

    def __init__(
        self,
        network: Network,
        cache: Path,
        acquire: Callable[[Network], Session] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._network = network
        self._cache = cache
        self._acquire = acquire or _acquire_with_browser
        self._now = now
        self._session: Session | None = None
        self._obtained_at: datetime | None = None

    def session(self) -> Session:
        """A valid session, from memory, from the disk cache, or from a browser."""
        if self._session is not None and not self._expired(self._obtained_at):
            return self._session
        if (from_disk := self._read_cache()) is not None:
            self._session, self._obtained_at = from_disk
            return self._session
        return self.renew()

    def renew(self) -> Session:
        """Open a browser to obtain a fresh session."""
        _LOG.info("session.acquiring", reason="session absente ou expirée")
        session = self._acquire(self._network)
        if REQUIRED_COOKIE not in session.cookies:
            raise SessionError(
                f"session incomplète : cookie « {REQUIRED_COOKIE} » absent. "
                "Le site a peut-être changé de protection ; rejouer "
                "tools/discover_api.py pour vérifier."
            )
        self._session = session
        self._obtained_at = self._now()
        self._write_cache(session, self._obtained_at)
        _LOG.info("session.acquired", cookies=sorted(session.cookies))
        return session

    def _expired(self, obtained_at: datetime | None) -> bool:
        if obtained_at is None:
            return True
        age = self._now() - obtained_at
        return age >= timedelta(minutes=self._network.session_ttl_minutes)

    def _read_cache(self) -> tuple[Session, datetime] | None:
        """Re-read a cached session, ignoring anything doubtful."""
        if not self._cache.is_file():
            return None
        try:
            raw = json.loads(self._cache.read_text(encoding="utf-8"))
            obtained_at = datetime.fromisoformat(raw["obtained_at"])
            cookies = {str(k): str(v) for k, v in raw["cookies"].items()}
            session = Session(cookies=cookies, user_agent=str(raw.get("user_agent", "")))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            _LOG.warning("session.cache_unreadable", path=str(self._cache))
            return None
        if self._expired(obtained_at) or REQUIRED_COOKIE not in cookies:
            return None
        return session, obtained_at

    def _write_cache(self, session: Session, obtained_at: datetime) -> None:
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "obtained_at": obtained_at.isoformat(),
            "user_agent": session.user_agent,
            "cookies": dict(session.cookies),
        }
        self._cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # A session amounts to implicit authentication: it concerns its owner
        # and nobody else.
        self._cache.chmod(0o600)


def _acquire_with_browser(network: Network) -> Session:  # pragma: no cover
    """Open the home page in Chromium and collect the cookies it is given.

    Playwright is only required by this function; it lives in the `discovery`
    extra so that an operating machine can do without it once the session is
    cached.

    Not covered by tests: it drives a real browser against a real site.
    Everything testable — cache, expiry, required cookie — lives in
    `BrowserSession`, which receives this function by injection.
    """
    try:
        # Deferred import, deliberately: playwright lives in the `discovery`
        # extra, and an operating machine must be able to do without it.
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise SessionError(
            "playwright est requis pour obtenir une session : "
            "uv sync --extra discovery && uv run playwright install chromium"
        ) from exc

    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=network.headless_browser)
        try:
            # The User-Agent is NOT spoofed: the browser announces what it is.
            # That is also what keeps the session usable over plain HTTP next.
            context = browser.new_context(locale="fr-FR")
            page = context.new_page()
            page.goto(f"{network.base_url}/ventes", wait_until="networkidle", timeout=60_000)
            title = (page.title() or "").lower()
            if any(marker in title for marker in _CAPTCHA_MARKERS):
                raise SessionError(
                    "le site présente un CAPTCHA à l'ouverture. Sleeper ne le "
                    "résout pas : espacer les exécutions et relancer plus tard."
                )
            agent = str(page.evaluate("() => navigator.userAgent"))
            return Session(
                cookies={c["name"]: c["value"] for c in context.cookies()},
                user_agent=agent,
            )
        finally:
            browser.close()
