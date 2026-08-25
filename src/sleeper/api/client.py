"""Operating client for the Domaine gateway.

The client owns everything that is not transport: pacing, retries, refusal of
the anti-bot challenge, and JSON parsing. The transport itself is pluggable,
which is what makes the whole layer testable without a browser.

Three guarantees:

1. **Pacing.** A shared rate limiter bounds the overall throughput whatever
   the concurrency upstream. The site is a public service: we do not shove it.
2. **Retries.** Capped exponential backoff on transport failures and 5xx.
   Definitive 4xx are not retried: insisting will not cure them.
3. **Refusal to circumvent.** If the site serves a CAPTCHA, the client stops
   DEAD, with no retry and no attempt at resolution. That is a boundary of the
   project, not an incident to absorb.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Final

import structlog

from sleeper.api.operations import GRAPHQL_PATH, OPERATION_NAME
from sleeper.api.transport import Response, Transport, payload_of
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


def _html_body(response: Response) -> str:
    """Start of the body, only when the response is not JSON."""
    return "" if response.is_json else response.text[:2000]


def is_captcha(response: Response) -> bool:
    """The site is asking for a human to step in."""
    excerpt = _html_body(response)
    return any(signature.search(excerpt) for signature in _CAPTCHA_SIGNATURES)


def is_expired_session(response: Response) -> bool:
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
    """Calls the Domaine's GraphQL gateway over a transport."""

    def __init__(
        self,
        network: Network,
        transport: Transport,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._network = network
        self._transport = transport
        self._sleep = sleep
        self._limiter = RateLimiter(network.delay_between_requests_s, clock, sleep)

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
                response = self._transport.send(GRAPHQL_PATH, params)
            except NetworkError as exc:
                last = exc
            except Exception as exc:  # third-party transport: the cause is opaque
                last = NetworkError(f"échec de transport : {type(exc).__name__}: {exc}")
            else:
                self._refuse_if_captcha(response)
                if is_expired_session(response) and not session_renewed:
                    _LOG.info("session.expired", action="renewal")
                    self._transport.renew()
                    session_renewed = True
                    continue
                if is_expired_session(response):
                    raise NetworkError(
                        "le site redemande son challenge JavaScript malgré une "
                        "session neuve : la protection a probablement changé"
                    )
                if response.status < _MIN_ERROR_STATUS:
                    return payload_of(response)
                if response.status not in _RETRYABLE_STATUSES:
                    raise NetworkError(
                        f"réponse définitive {response.status} de la passerelle : "
                        f"{response.text[:200]}"
                    )
                last = NetworkError(f"statut {response.status}")
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
    def _refuse_if_captcha(response: Response) -> None:
        """Stop everything if the site serves a CAPTCHA.

        Sleeper solves no CAPTCHA and does not retry: retrying would amount to
        trying to get around it.
        """
        if is_captcha(response):
            raise AntiBotChallengeError(
                "le site présente un challenge anti-robot (WAF/CAPTCHA). "
                "Sleeper ne le contourne pas : espacer les exécutions, vérifier "
                "la cadence configurée, puis relancer plus tard."
            )
