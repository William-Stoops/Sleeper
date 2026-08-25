"""Transport: response classification and JSON parsing.

The browser transport itself is not unit-tested — it drives a real browser
against a real site. What is testable lives in `Response` and `payload_of`.
"""

from __future__ import annotations

import pytest

from sleeper.api.client import is_captcha, is_expired_session
from sleeper.api.transport import Response, payload_of
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
