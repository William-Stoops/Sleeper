"""Session caching and renewal. No browser is launched here."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sleeper.api.session import REQUIRED_COOKIE, BrowserSession, Session
from sleeper.config import Network
from sleeper.errors import SessionError

START = datetime(2026, 8, 25, 4, 30, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.instant = START

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, minutes: int) -> None:
        self.instant += timedelta(minutes=minutes)


@pytest.fixture
def network() -> Network:
    return Network(user_agent="SleeperBot/0.1 (+mailto:test@example.org)", session_ttl_minutes=45)


def acquirer(
    counter: list[int], cookies: Mapping[str, str] | None = None
) -> Callable[[Network], Session]:
    """A fake session acquirer: counts how often a "browser" was opened."""
    payload = dict(cookies or {REQUIRED_COOKIE: "jeton", "PHPSESSID": "abc"})

    def _acquire(_: Network) -> Session:
        counter.append(1)
        return Session(
            cookies={**payload, "PHPSESSID": f"abc{len(counter)}"},
            user_agent="Mozilla/5.0 (essai) Chrome/140",
        )

    return _acquire


class TestAcquisition:
    def test_opens_a_browser_on_first_call(self, network: Network, tmp_path: Path) -> None:
        calls: list[int] = []
        session = BrowserSession(network, tmp_path / "s.json", acquirer(calls), Clock())
        assert REQUIRED_COOKIE in session.session().cookies
        assert len(calls) == 1

    def test_does_not_reopen_while_the_session_is_fresh(
        self, network: Network, tmp_path: Path
    ) -> None:
        calls: list[int] = []
        clock = Clock()
        session = BrowserSession(network, tmp_path / "s.json", acquirer(calls), clock)
        session.session()
        clock.advance(44)
        session.session()
        assert len(calls) == 1

    def test_renews_on_expiry(self, network: Network, tmp_path: Path) -> None:
        calls: list[int] = []
        clock = Clock()
        session = BrowserSession(network, tmp_path / "s.json", acquirer(calls), clock)
        session.session()
        clock.advance(46)
        session.session()
        assert len(calls) == 2

    def test_a_missing_required_cookie_is_an_explicit_error(
        self, network: Network, tmp_path: Path
    ) -> None:
        def without_cookie(_: Network) -> Session:
            return Session(cookies={"PHPSESSID": "abc"}, user_agent="Chrome/140")

        session = BrowserSession(network, tmp_path / "s.json", without_cookie, Clock())
        with pytest.raises(SessionError, match=REQUIRED_COOKIE):
            session.session()


class TestDiskCache:
    def test_a_second_instance_reuses_the_cache(self, network: Network, tmp_path: Path) -> None:
        cache = tmp_path / "s.json"
        calls: list[int] = []
        clock = Clock()
        BrowserSession(network, cache, acquirer(calls), clock).session()
        BrowserSession(network, cache, acquirer(calls), clock).session()
        assert len(calls) == 1

    def test_the_cache_is_unreadable_by_others(self, network: Network, tmp_path: Path) -> None:
        cache = tmp_path / "s.json"
        BrowserSession(network, cache, acquirer([]), Clock()).session()
        assert cache.stat().st_mode & 0o077 == 0

    def test_an_expired_cache_is_ignored(self, network: Network, tmp_path: Path) -> None:
        cache = tmp_path / "s.json"
        calls: list[int] = []
        clock = Clock()
        BrowserSession(network, cache, acquirer(calls), clock).session()
        clock.advance(60)
        BrowserSession(network, cache, acquirer(calls), clock).session()
        assert len(calls) == 2

    @pytest.mark.parametrize(
        "content",
        ["{ pas du json", json.dumps({"cookies": {}}), json.dumps({"obtained_at": "hier"})],
    )
    def test_a_corrupt_cache_is_ignored_without_crashing(
        self, network: Network, tmp_path: Path, content: str
    ) -> None:
        cache = tmp_path / "s.json"
        cache.write_text(content, encoding="utf-8")
        calls: list[int] = []
        session = BrowserSession(network, cache, acquirer(calls), Clock())
        assert REQUIRED_COOKIE in session.session().cookies
        assert len(calls) == 1

    def test_renew_forces_a_fresh_acquisition(self, network: Network, tmp_path: Path) -> None:
        calls: list[int] = []
        session = BrowserSession(network, tmp_path / "s.json", acquirer(calls), Clock())
        first = dict(session.session().cookies)
        second = dict(session.renew().cookies)
        assert len(calls) == 2
        assert first["PHPSESSID"] != second["PHPSESSID"]


class TestUserAgent:
    def test_the_session_carries_the_browser_user_agent(
        self, network: Network, tmp_path: Path
    ) -> None:
        session = BrowserSession(network, tmp_path / "s.json", acquirer([]), Clock())
        assert "Chrome/140" in session.session().user_agent

    def test_the_user_agent_survives_the_disk_cache(self, network: Network, tmp_path: Path) -> None:
        cache = tmp_path / "s.json"
        clock = Clock()
        BrowserSession(network, cache, acquirer([]), clock).session()
        reread = BrowserSession(network, cache, acquirer([]), clock).session()
        assert "Chrome/140" in reread.user_agent
