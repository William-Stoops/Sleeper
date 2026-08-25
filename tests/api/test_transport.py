"""Transport: response classification and JSON parsing.

The browser transport itself is not unit-tested — it drives a real browser
against a real site. What is testable lives in `Response` and `payload_of`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sleeper.api.client import is_captcha, is_expired_session
from sleeper.api.transport import BrowserTransport, Response, payload_of
from sleeper.config import Network
from sleeper.errors import NetworkError


class TestResponse:
    @pytest.mark.parametrize(
        ("content_type", "expected"),
        [
            ("application/json", True),
            ("application/json; charset=utf-8", True),
            ("text/html", False),
            ("", False),
        ],
    )
    def test_detects_a_json_body(self, content_type: str, expected: bool) -> None:
        assert Response(200, content_type, "").is_json is expected


class TestClassification:
    def test_a_json_response_is_never_a_challenge(self) -> None:
        # A payload legitimately mentioning "captcha" must not trip the guard.
        response = Response(200, "application/json", '{"data": {"name": "lot captcha"}}')
        assert is_captcha(response) is False
        assert is_expired_session(response) is False

    def test_an_altcha_page_is_a_captcha(self) -> None:
        response = Response(200, "text/html", "<title>Check that you are not a robot</title>")
        assert is_captcha(response) is True
        assert is_expired_session(response) is False

    def test_the_entry_challenge_is_an_expired_session(self) -> None:
        response = Response(
            200, "text/html", "<noscript>This website requires JS enabled and cookies</noscript>"
        )
        assert is_expired_session(response) is True
        assert is_captcha(response) is False


class TestPayloadOf:
    def test_parses_a_json_object(self) -> None:
        assert payload_of(Response(200, "application/json", '{"a": 1}')) == {"a": 1}

    def test_refuses_a_non_json_body(self) -> None:
        with pytest.raises(NetworkError, match="non JSON"):
            payload_of(Response(200, "text/plain", "pas du json"))

    def test_refuses_a_json_array(self) -> None:
        with pytest.raises(NetworkError, match="objet attendu"):
            payload_of(Response(200, "application/json", "[1]"))


class TestStoredSession:
    """The persisted session must never be able to prevent a run from starting."""

    def _transport(self, tmp_path: Path) -> BrowserTransport:
        network = Network(user_agent="SleeperBot/0.1 (+mailto:test@example.org)")
        return BrowserTransport(network, tmp_path / "session.json")

    def test_no_file_means_no_stored_session(self, tmp_path: Path) -> None:
        assert self._transport(tmp_path)._stored_session() is None

    def test_a_valid_storage_state_is_reused(self, tmp_path: Path) -> None:
        cache = tmp_path / "session.json"
        cache.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
        assert self._transport(tmp_path)._stored_session() == str(cache)

    @pytest.mark.parametrize(
        "content",
        [
            "{ pas du json",
            json.dumps({"obtained_at": "2026-08-25", "user_agent": "Chrome"}),
            json.dumps([1, 2, 3]),
        ],
    )
    def test_an_unusable_cache_is_ignored_rather_than_fatal(
        self, tmp_path: Path, content: str
    ) -> None:
        (tmp_path / "session.json").write_text(content, encoding="utf-8")
        assert self._transport(tmp_path)._stored_session() is None
