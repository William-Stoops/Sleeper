"""Client: pacing, retries, and explicit refusal of the anti-bot challenge.

No test touches the network, and none launches a browser: a fake transport
plays the responses back.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from sleeper.api.client import DomaineClient, RateLimiter
from sleeper.api.operations import SALES_LIST
from sleeper.api.transport import Response
from sleeper.config import Network
from sleeper.errors import AntiBotChallengeError, NetworkError

ALTCHA_PAGE = (
    "<!DOCTYPE html><html><head><title>Check that you are not a robot</title>"
    "<script src='/.well-known/ubika/captcha/altcha.js'></script></head></html>"
)

JS_CHALLENGE_PAGE = (
    "<html><body><script>window.location.href='/redirect_ABC/x'</script>"
    "<noscript>This website requires JS enabled and cookies</noscript></body></html>"
)


def json_response(payload: dict[str, Any], status: int = 200) -> Response:
    return Response(status=status, content_type="application/json", text=json.dumps(payload))


def html_response(text: str, status: int = 200) -> Response:
    return Response(status=status, content_type="text/html", text=text)


class FakeTransport:
    """Replays a queue of responses and counts session renewals."""

    def __init__(self, *responses: Response | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.renewals = 0

    def send(self, path: str, params: Mapping[str, str]) -> Response:
        self.calls.append((path, dict(params)))
        outcome = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def renew(self) -> None:
        self.renewals += 1


@pytest.fixture
def network() -> Network:
    return Network(
        user_agent="SleeperBot/0.1 (+mailto:test@example.org)",
        delay_between_requests_s=0.5,
        max_attempts=3,
        backoff_initial_s=0.01,
        backoff_max_s=0.05,
    )


def racing_clock() -> Callable[[], float]:
    """A clock jumping 1000 s per read: the rate limiter never sleeps.

    Recorded sleeps are then exclusively backoff sleeps, which makes the
    assertions about retries unambiguous.
    """
    counter = itertools.count(0.0, 1000.0)
    return lambda: next(counter)


def client_with(
    network: Network, transport: FakeTransport, sleeps: list[float] | None = None
) -> DomaineClient:
    return DomaineClient(
        network=network,
        transport=transport,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
        clock=racing_clock(),
    )


class TestNominalRequest:
    def test_returns_the_json_payload(self, network: Network) -> None:
        transport = FakeTransport(json_response({"data": {"ok": True}}))
        assert client_with(network, transport).query("query x{y}", {"a": 1}) == {
            "data": {"ok": True}
        }

    def test_sends_query_variables_and_operation(self, network: Network) -> None:
        transport = FakeTransport(json_response({"data": {}}))
        client_with(network, transport).query(SALES_LIST, {"currentPage": 2})
        path, params = transport.calls[0]
        assert path == "/gateway/magento/graphql/"
        assert params["query"] == SALES_LIST
        assert json.loads(params["variables"]) == {"currentPage": 2}
        assert params["operationName"] == "getAuctions"

    def test_an_unknown_operation_carries_no_operation_name(self, network: Network) -> None:
        transport = FakeTransport(json_response({"data": {}}))
        client_with(network, transport).query("query x{y}", {})
        assert "operationName" not in transport.calls[0][1]


class TestAntiBotChallenge:
    @pytest.mark.parametrize("status", [200, 403])
    def test_a_captcha_page_is_terminal(self, network: Network, status: int) -> None:
        transport = FakeTransport(html_response(ALTCHA_PAGE, status))
        with pytest.raises(AntiBotChallengeError):
            client_with(network, transport).query("query x{y}", {})
        # No retry: insisting on a challenge is trying to get around it.
        assert len(transport.calls) == 1

    def test_a_captcha_is_not_mistaken_for_an_expired_session(self, network: Network) -> None:
        transport = FakeTransport(html_response(ALTCHA_PAGE))
        with pytest.raises(AntiBotChallengeError):
            client_with(network, transport).query("query x{y}", {})
        assert transport.renewals == 0


class TestExpiredSession:
    """The entry JS challenge is NOT a CAPTCHA: it is a session to redo."""

    def test_renews_the_session_then_succeeds(self, network: Network) -> None:
        transport = FakeTransport(
            html_response(JS_CHALLENGE_PAGE), json_response({"data": {"ok": 1}})
        )
        assert client_with(network, transport).query("query x{y}", {}) == {"data": {"ok": 1}}
        assert transport.renewals == 1

    def test_a_challenge_persisting_after_renewal_is_a_clear_error(self, network: Network) -> None:
        transport = FakeTransport(html_response(JS_CHALLENGE_PAGE))
        with pytest.raises(NetworkError, match="protection a probablement changé"):
            client_with(network, transport).query("query x{y}", {})
        # A single renewal attempt: we do not insist.
        assert transport.renewals == 1


class TestRetries:
    def test_retries_on_a_server_error_then_succeeds(self, network: Network) -> None:
        transport = FakeTransport(
            Response(503, "text/plain", ""), json_response({"data": {"ok": 1}})
        )
        assert client_with(network, transport).query("query x{y}", {}) == {"data": {"ok": 1}}

    def test_backoff_is_exponential(self, network: Network) -> None:
        transport = FakeTransport(Response(500, "text/plain", ""))
        sleeps: list[float] = []
        with pytest.raises(NetworkError):
            client_with(network, transport, sleeps).query("query x{y}", {})
        # max_attempts = 3 -> two waits between the three attempts
        assert sleeps == [0.01, 0.02]

    def test_backoff_is_capped(self, network: Network) -> None:
        generous = network.model_copy(
            update={"max_attempts": 6, "backoff_initial_s": 1.0, "backoff_max_s": 4.0}
        )
        transport = FakeTransport(Response(500, "text/plain", ""))
        sleeps: list[float] = []
        with pytest.raises(NetworkError):
            client_with(generous, transport, sleeps).query("query x{y}", {})
        assert sleeps == [1.0, 2.0, 4.0, 4.0, 4.0]

    def test_a_persistent_transport_failure_raises_a_network_error(self, network: Network) -> None:
        transport = FakeTransport(RuntimeError("connexion refusée"))
        with pytest.raises(NetworkError, match="3 tentatives"):
            client_with(network, transport).query("query x{y}", {})

    def test_a_definitive_client_error_is_not_retried(self, network: Network) -> None:
        transport = FakeTransport(
            Response(400, "application/json", '{"message": "Bad query params length"}')
        )
        with pytest.raises(NetworkError, match="400"):
            client_with(network, transport).query("query x{y}", {})
        assert len(transport.calls) == 1

    def test_a_non_json_response_is_an_error(self, network: Network) -> None:
        transport = FakeTransport(Response(200, "text/plain", "pas du json"))
        with pytest.raises(NetworkError, match="JSON"):
            client_with(network, transport).query("query x{y}", {})

    def test_a_json_array_is_refused(self, network: Network) -> None:
        transport = FakeTransport(Response(200, "application/json", "[1, 2]"))
        with pytest.raises(NetworkError, match="objet attendu"):
            client_with(network, transport).query("query x{y}", {})


class TestRateLimiter:
    def test_spaces_calls_by_the_requested_delay(self) -> None:
        # Clock reads: 1) first call, 2) second call, 3) after the sleep.
        instants = iter([0.0, 0.2, 0.5])
        sleeps: list[float] = []
        limiter = RateLimiter(0.5, clock=lambda: next(instants), sleep=sleeps.append)
        limiter.wait()  # first call: nothing to wait for
        limiter.wait()  # 0.2 s elapsed: 0.3 s left
        assert sleeps == [pytest.approx(0.3)]

    def test_never_produces_a_negative_delay(self) -> None:
        instants = iter([0.0, 10.0])
        sleeps: list[float] = []
        limiter = RateLimiter(0.5, clock=lambda: next(instants), sleep=sleeps.append)
        limiter.wait()
        limiter.wait()  # far beyond the delay: no sleep at all
        assert sleeps == []
