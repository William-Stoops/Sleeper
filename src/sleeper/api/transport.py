"""Transport towards the Domaine gateway.

**Why not a plain HTTP client.** The site sits behind a web application
firewall that discriminates on the TLS fingerprint of the client. A bare
`httpx` request — even with the exact operation, the exact headers, the
browser's own cookies and HTTP/2 — receives the JavaScript entry challenge
instead of JSON. Forging a browser TLS fingerprint would be circumventing an
anti-bot protection, which this project does not do.

The compliant equivalent is to issue the requests **from the browser's own
network stack**. That is not circumvention: it is a real browser, holding a
real session, calling the application's own public API. Pages are simply not
rendered — a performance choice, not an evasion.

The browser session is persisted between runs (`storage_state`), so the entry
challenge is passed once and not on every execution.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

import structlog

from sleeper.config import Network
from sleeper.errors import NetworkError, SessionError

_LOG = structlog.get_logger(__name__)

#: Markers of a challenge no machine may resolve on its own.
_CAPTCHA_MARKERS = ("not a robot", "altcha", "captcha")

#: Functional headers of the application's protocol. `Store` is a Magento
#: header, not an anti-bot token: it selects the store view.
_APPLICATION_HEADERS = {"Store": "default", "Content-Type": "application/json"}


@dataclass(frozen=True, slots=True)
class Response:
    """The minimum the client needs in order to decide."""

    status: int
    content_type: str
    text: str

    @property
    def is_json(self) -> bool:
        return "json" in self.content_type.lower()


class Transport(Protocol):
    """Sends one request and returns its response."""

    def send(self, path: str, params: Mapping[str, str]) -> Response:
        """Issue a GET and return the raw response."""
        ...

    def renew(self) -> None:
        """Obtain a fresh session."""
        ...


class BrowserTransport:
    """Issues requests from a real browser's network stack.

    Opens one browser for the whole run. The window is visible: in headless
    mode Chromium announces "HeadlessChrome" in its User-Agent, which the
    firewall refuses, and masking that token would be a disguise.
    """

    def __init__(self, network: Network, session_cache: Path) -> None:
        self._network = network
        self._session_cache = session_cache
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    def __enter__(self) -> Self:  # pragma: no cover
        self._start()
        return self

    def __exit__(  # pragma: no cover
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:  # pragma: no cover
        """Save the session, then close the browser."""
        if self._context is not None:
            self._save_session()
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def send(self, path: str, params: Mapping[str, str]) -> Response:  # pragma: no cover
        """Issue the request through the browser's request context."""
        if self._context is None:
            self._start()
        headers = {
            **_APPLICATION_HEADERS,
            "Referer": f"{self._network.base_url}/ventes",
            # The robot identifies itself alongside the browser it drives, so
            # that a site administrator can recognise and contact us.
            "X-Robot-Identification": self._network.user_agent,
        }
        raw = self._context.request.get(
            f"{self._network.base_url}{path}",
            params=dict(params),
            headers=headers,
            timeout=self._network.timeout_s * 1000,
        )
        return Response(
            status=raw.status,
            content_type=raw.headers.get("content-type", ""),
            text=raw.text(),
        )

    def renew(self) -> None:  # pragma: no cover
        """Reopen a browser context, discarding the cached session."""
        _LOG.info("session.renewing")
        self._session_cache.unlink(missing_ok=True)
        self.close()
        self._start()

    # ----------------------------------------------------------------- private

    def _start(self) -> None:  # pragma: no cover
        """Launch the browser and pass the entry challenge."""
        try:
            # Deferred import, deliberately: it keeps the domain and output
            # layers importable without a browser installed.
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on the installation
            raise SessionError(
                "playwright est requis : uv sync && uv run playwright install chromium"
            ) from exc

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._network.headless_browser)
        self._context = self._browser.new_context(
            locale="fr-FR", storage_state=self._stored_session()
        )
        self._pass_entry_challenge()

    def _stored_session(self) -> str | None:
        """Path of the persisted session, when there is a usable one.

        A cache left behind by another version — or simply corrupt — is
        ignored rather than allowed to fail the browser start. The cost is one
        extra entry challenge; the alternative is a run that cannot start.
        """
        if not self._session_cache.is_file():
            return None
        try:
            stored = json.loads(self._session_cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LOG.warning("session.cache_unreadable", path=str(self._session_cache))
            return None
        if not isinstance(stored, dict) or "cookies" not in stored:
            _LOG.warning("session.cache_unusable", path=str(self._session_cache))
            return None
        return str(self._session_cache)

    def _pass_entry_challenge(self) -> None:  # pragma: no cover
        """Load the sales page, which is where the site hands out its session."""
        page = self._context.new_page()
        try:
            page.goto(f"{self._network.base_url}/ventes", wait_until="networkidle", timeout=60_000)
            title = (page.title() or "").lower()
            if any(marker in title for marker in _CAPTCHA_MARKERS):
                raise SessionError(
                    "le site présente un CAPTCHA à l'ouverture. Sleeper ne le "
                    "résout pas : espacer les exécutions et relancer plus tard."
                )
            _LOG.info("session.ready", title=page.title())
        finally:
            page.close()

    def _save_session(self) -> None:  # pragma: no cover
        """Persist the session so the next run does not redo the challenge."""
        if self._context is None:
            return
        self._session_cache.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(self._session_cache))
        # A session amounts to implicit authentication: it concerns its owner
        # and nobody else.
        self._session_cache.chmod(0o600)


def payload_of(response: Response) -> dict[str, Any]:
    """Parse a JSON response, refusing anything that is not an object."""
    try:
        parsed = json.loads(response.text)
    except ValueError as exc:
        raise NetworkError(
            f"réponse non JSON de la passerelle ({response.content_type}) : {response.text[:200]}"
        ) from exc
    if not isinstance(parsed, dict):
        raise NetworkError("charge utile JSON inattendue : objet attendu")
    return parsed
