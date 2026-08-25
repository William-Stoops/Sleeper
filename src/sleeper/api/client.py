"""Operating HTTP client.

The daily run opens no browser: it calls the GraphQL gateway directly with
the application's exact requests (see `operations`), replaying a session
obtained once by a real browser.

Three guarantees carried by this layer:

1. **Pacing.** A shared rate limiter bounds the overall throughput whatever
   the concurrency upstream. The site is a public service: we do not shove it.
2. **Retries.** Capped exponential backoff on transport failures and 5xx.
   Definitive 4xx are not retried: insisting will not cure them.
3. **Refusal to circumvent.** If the site serves an anti-bot challenge, the
   client stops DEAD, with no retry and no attempt at resolution. That is a
   boundary of the project, not an incident to absorb.
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

from sleeper.api.operations import GRAPHQL_PATH, OPERATION_NAME
from sleeper.api.session import Session
from sleeper.config import Network
from sleeper.errors import AntiBotChallengeError, NetworkError

#: CAPTCHA signatures. TERMINAL: Sleeper does not solve them, and does not
#: retry — retrying would amount to trying to get around them.
_CAPTCHA_SIGNATURES: Final = (
    re.compile(r"not\s+a\s+robot", re.IGNORECASE),
    re.compile(r"altcha", re.IGNORECASE),
    re.compile(r"captcha", re.IGNORECASE),
)

#: Signatures of a merely expired session: the site is asking for its entry
#: JavaScript challenge again. An ordinary visitor would pass it without a
#: second thought, so the session is renewed — ONCE.
_EXPIRED_SESSION_SIGNATURES: Final = (
    re.compile(r"window\.location\.href\s*=\s*'/redirect_", re.IGNORECASE),
    re.compile(r"requires JS enabled and cookies", re.IGNORECASE),
)

_RETRYABLE_STATUSES: Final = frozenset({408, 425, 429, 500, 502, 503, 504})
_MIN_ERROR_STATUS: Final = 400

_LOG = structlog.get_logger(__name__)


class SessionProvider(Protocol):
    """Source of the session the site accepts."""

    def session(self) -> Session:
        """Current session, possibly from a cache."""
        ...

    def renew(self) -> Session:
        """Force a fresh session to be obtained."""
        ...


class StaticSession:
    """A frozen session, useful in tests and when replaying a capture."""

    def __init__(self, cookies: Mapping[str, str], user_agent: str = "") -> None:
        self._session = Session(cookies=dict(cookies), user_agent=user_agent)

    def session(self) -> Session:
        return self._session

    def renew(self) -> Session:
        return self._session


def build_user_agent(browser_agent: str, identification: str) -> str:
    """Compose the operating User-Agent.

    Sleeper replays a real browser's session: hiding that browser would break
    the session at the firewall, and claiming to be something else would be a
    lie. Both are therefore announced — the originating client, and the robot
    using it — so that a site administrator can identify and reach us.
    """
    if not browser_agent:
        return identification
    return f"{browser_agent} {identification}".strip()


def _html_body(response: httpx.Response) -> str:
    """Start of the body, only when the response is not JSON."""
    if "json" in response.headers.get("content-type", "").lower():
        return ""
    return response.text[:2000]


def _is_captcha(response: httpx.Response) -> bool:
    """The site is asking for a human to step in."""
    excerpt = _html_body(response)
    return any(signature.search(excerpt) for signature in _CAPTCHA_SIGNATURES)


def _is_expired_session(response: httpx.Response) -> bool:
    """The site is merely asking for its entry JavaScript challenge again."""
    excerpt = _html_body(response)
    return any(signature.search(excerpt) for signature in _EXPIRED_SESSION_SIGNATURES)


class RateLimiter:
    """Shared throughput limiter, safe for concurrent use."""

    def __init__(
        self,
        delay_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._delay = delay_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        """Block long enough to honour the delay between requests."""
        with self._lock:
            now = self._clock()
            if self._last is not None:
                remaining = self._delay - (now - self._last)
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._clock()
            self._last = now


class DomaineClient:
    """Calls the Domaine's GraphQL gateway."""

    def __init__(
        self,
        network: Network,
        session: SessionProvider,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._network = network
        self._session = session
        self._sleep = sleep
        self._limiter = RateLimiter(network.delay_between_requests_s, clock, sleep)
        self._client = httpx.Client(
            base_url=network.base_url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
            timeout=network.timeout_s,
            transport=transport,
            follow_redirects=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def query(self, request: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Run a GraphQL operation and return its JSON payload."""
        params = {"query": request, "variables": json.dumps(variables, separators=(",", ":"))}
        if operation := OPERATION_NAME.get(request):
            params["operationName"] = operation

        last: Exception | None = None
        session_renewed = False
        for attempt in range(1, self._network.max_attempts + 1):
            self._limiter.wait()
            try:
                session = self._session.session()
                self._client.cookies.update(dict(session.cookies))
                self._client.headers["User-Agent"] = build_user_agent(
                    session.user_agent, self._network.user_agent
                )
                response = self._client.get(GRAPHQL_PATH, params=params)
            except httpx.HTTPError as exc:
                last = exc
            else:
                self._refuse_if_captcha(response)
                if _is_expired_session(response) and not session_renewed:
                    _LOG.info("session.expired", action="renewal")
                    self._session.renew()
                    session_renewed = True
                    continue
                if _is_expired_session(response):
                    raise NetworkError(
                        "le site redemande son challenge JavaScript malgré une "
                        "session neuve : la protection a probablement changé"
                    )
                if response.status_code < _MIN_ERROR_STATUS:
                    return self._payload(response)
                if response.status_code not in _RETRYABLE_STATUSES:
                    raise NetworkError(
                        f"réponse définitive {response.status_code} de la passerelle : "
                        f"{response.text[:200]}"
                    )
                last = NetworkError(f"statut {response.status_code}")
            if attempt < self._network.max_attempts:
                self._sleep(self._backoff(attempt))

        raise NetworkError(
            f"échec après {self._network.max_attempts} tentatives : {last}"
        ) from last

    def _backoff(self, attempt: int) -> float:
        """Capped exponential backoff."""
        raw = self._network.backoff_initial_s * (self._network.backoff_factor ** (attempt - 1))
        return min(raw, self._network.backoff_max_s)

    @staticmethod
    def _refuse_if_captcha(response: httpx.Response) -> None:
        """Stop everything if the site serves a CAPTCHA.

        Sleeper solves no CAPTCHA and does not retry: retrying would amount to
        trying to get around it.
        """
        if _is_captcha(response):
            raise AntiBotChallengeError(
                "le site présente un challenge anti-robot (WAF/CAPTCHA). "
                "Sleeper ne le contourne pas : espacer les exécutions, vérifier "
                "la cadence configurée, puis relancer plus tard."
            )

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise NetworkError(
                f"réponse non JSON de la passerelle ({response.headers.get('content-type')}) : "
                f"{response.text[:200]}"
            ) from exc
        if not isinstance(payload, dict):
            raise NetworkError("charge utile JSON inattendue : objet attendu")
        return payload
