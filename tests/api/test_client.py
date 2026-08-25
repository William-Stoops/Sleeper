"""HTTP client: pacing, retries, and explicit refusal of the anti-bot challenge.

No test touches the network: httpx.MockTransport plays the responses back.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from sleeper.api.client import DomaineClient, RateLimiter, StaticSession, build_user_agent
from sleeper.api.session import Session
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


def client_with(network: Network, handler: Any, sleeps: list[float] | None = None) -> DomaineClient:
    return DomaineClient(
        network=network,
        session=StaticSession({"bot_mitigation_cookie": "x"}, user_agent="Chrome/140"),
        transport=httpx.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
        clock=racing_clock(),
    )


class CountingSession:
    """A session that counts its renewals."""

    def __init__(self) -> None:
        self.renewals = 0
        self._session = Session(cookies={"bot_mitigation_cookie": "v0"}, user_agent="Chrome/140")

    def session(self) -> Session:
        return self._session

    def renew(self) -> Session:
        self.renewals += 1
        self._session = Session(
            cookies={"bot_mitigation_cookie": f"v{self.renewals}"}, user_agent="Chrome/140"
        )
        return self._session


class TestNominalRequest:
    def test_returns_the_json_payload(self, network: Network) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"ok": True}})

        with client_with(network, handler) as client:
            assert client.query("query x{y}", {"a": 1}) == {"data": {"ok": True}}

    def test_sends_query_variables_and_operation(self, network: Network) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": {}})

        with client_with(network, handler) as client:
            client.query("query getAuctions{a}", {"currentPage": 2})

        params = seen[0].url.params
        assert params["query"] == "query getAuctions{a}"
        assert json.loads(params["variables"]) == {"currentPage": 2}

    def test_announces_the_browser_then_the_robot(self, network: Network) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": {}})

        with client_with(network, handler) as client:
            client.query("query x{y}", {})

        # Both the originating browser AND the robot are announced: the session
        # stays valid at the firewall, and the site operator can reach us.
        agent = seen[0].headers["user-agent"]
        assert agent.startswith("Chrome/140")
        assert "SleeperBot/0.1 (+mailto:test@example.org)" in agent

    def test_sends_the_session_cookies(self, network: Network) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": {}})

        with client_with(network, handler) as client:
            client.query("query x{y}", {})
        assert "bot_mitigation_cookie=x" in seen[0].headers["cookie"]


class TestAntiBotChallenge:
    @pytest.mark.parametrize("status", [200, 403])
    def test_a_captcha_page_is_terminal(self, network: Network, status: int) -> None:
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(status, text=ALTCHA_PAGE, headers={"content-type": "text/html"})

        with client_with(network, handler) as client, pytest.raises(AntiBotChallengeError):
            client.query("query x{y}", {})
        # No retry: insisting on a challenge is trying to get around it.
        assert calls == 1

    def test_a_captcha_is_not_mistaken_for_an_expired_session(self, network: Network) -> None:
        session = CountingSession()

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=ALTCHA_PAGE, headers={"content-type": "text/html"})

        client = DomaineClient(
            network=network,
            session=session,
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=racing_clock(),
        )
        with client, pytest.raises(AntiBotChallengeError):
            client.query("query x{y}", {})
        assert session.renewals == 0


class TestExpiredSession:
    """The entry JS challenge is NOT a CAPTCHA: it is a session to redo."""

    def _client(self, network: Network, handler: Any, session: CountingSession) -> DomaineClient:
        return DomaineClient(
            network=network,
            session=session,
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=racing_clock(),
        )

    def test_renews_the_session_then_succeeds(self, network: Network) -> None:
        session = CountingSession()
        responses = [
            httpx.Response(200, text=JS_CHALLENGE_PAGE, headers={"content-type": "text/html"}),
            httpx.Response(200, json={"data": {"ok": 1}}),
        ]

        def handler(_: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        with self._client(network, handler, session) as client:
            assert client.query("query x{y}", {}) == {"data": {"ok": 1}}
        assert session.renewals == 1

    def test_the_request_restarts_with_the_new_cookies(self, network: Network) -> None:
        session = CountingSession()
        seen: list[httpx.Request] = []
        responses = [
            httpx.Response(200, text=JS_CHALLENGE_PAGE, headers={"content-type": "text/html"}),
            httpx.Response(200, json={"data": {}}),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return responses.pop(0)

        with self._client(network, handler, session) as client:
            client.query("query x{y}", {})
        assert "bot_mitigation_cookie=v1" in seen[-1].headers["cookie"]

    def test_a_challenge_persisting_after_renewal_is_a_clear_error(self, network: Network) -> None:
        session = CountingSession()

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text=JS_CHALLENGE_PAGE, headers={"content-type": "text/html"}
            )

        with (
            self._client(network, handler, session) as client,
            pytest.raises(NetworkError, match="protection a probablement changé"),
        ):
            client.query("query x{y}", {})
        # A single renewal attempt: we do not insist.
        assert session.renewals == 1


class TestRetries:
    def test_retries_on_a_server_error_then_succeeds(self, network: Network) -> None:
        responses = [httpx.Response(503), httpx.Response(200, json={"data": {"ok": 1}})]

        def handler(_: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        sleeps: list[float] = []
        with client_with(network, handler, sleeps) as client:
            assert client.query("query x{y}", {}) == {"data": {"ok": 1}}
        assert not responses

    def test_backoff_is_exponential(self, network: Network) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        sleeps: list[float] = []
        with client_with(network, handler, sleeps) as client, pytest.raises(NetworkError):
            client.query("query x{y}", {})
        # max_attempts = 3 -> two waits between the three attempts
        assert sleeps == [0.01, 0.02]
        assert max(sleeps) <= network.backoff_max_s

    def test_backoff_is_capped(self, network: Network) -> None:
        generous = network.model_copy(
            update={"max_attempts": 6, "backoff_initial_s": 1.0, "backoff_max_s": 4.0}
        )

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        sleeps: list[float] = []
        with client_with(generous, handler, sleeps) as client, pytest.raises(NetworkError):
            client.query("query x{y}", {})
        assert sleeps == [1.0, 2.0, 4.0, 4.0, 4.0]

    def test_a_persistent_failure_raises_an_explicit_network_error(self, network: Network) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connexion refusée")

        with (
            client_with(network, handler) as client,
            pytest.raises(NetworkError, match="3 tentatives"),
        ):
            client.query("query x{y}", {})

    def test_a_definitive_client_error_is_not_retried(self, network: Network) -> None:
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(400, json={"message": "Bad query params length"})

        with client_with(network, handler) as client, pytest.raises(NetworkError, match="400"):
            client.query("query x{y}", {})
        assert calls == 1

    def test_a_non_json_response_is_an_error(self, network: Network) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="pas du json", headers={"content-type": "text/plain"})

        with client_with(network, handler) as client, pytest.raises(NetworkError, match="JSON"):
            client.query("query x{y}", {})


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


class TestUserAgentComposition:
    def test_announces_the_browser_then_the_robot(self) -> None:
        composed = build_user_agent("Mozilla/5.0 Chrome/140", "SleeperBot/0.1 (+mailto:a@b.fr)")
        assert composed == "Mozilla/5.0 Chrome/140 SleeperBot/0.1 (+mailto:a@b.fr)"

    def test_without_a_browser_only_the_identification_remains(self) -> None:
        assert build_user_agent("", "SleeperBot/0.1") == "SleeperBot/0.1"
