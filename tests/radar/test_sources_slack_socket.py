"""Tests for opening a Socket Mode connection: the request, the token's destination, the errors."""

import httpx
import pytest

from spyglass_service.radar.sources.slack_socket import SlackLiveError, open_connection_url


def test_open_connection_url_posts_to_slack_with_the_app_token_in_the_header():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "url": "wss://wss-primary.slack.com/link?ticket=t"})

    url = open_connection_url("xapp-secret", transport=httpx.MockTransport(handler))
    assert url.startswith("wss://wss-primary.slack.com/")
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://slack.com/api/apps.connections.open"
    assert request.headers["authorization"] == "Bearer xapp-secret"
    assert b"xapp-secret" not in request.content and "xapp-secret" not in str(request.url)


@pytest.mark.parametrize("error,fatal", [("invalid_auth", True), ("token_revoked", True),
                                         ("not_allowed_token_type", True), ("ratelimited", False),
                                         ("internal_error", False)])
def test_open_connection_url_error_kinds(error, fatal):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": False, "error": error}))
    with pytest.raises(SlackLiveError) as caught:
        open_connection_url("xapp-1", transport=transport)
    assert caught.value.fatal is fatal and error in str(caught.value)
    assert "xapp-1" not in str(caught.value)


def test_open_connection_url_refuses_an_address_that_is_not_slack():
    transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"ok": True, "url": "wss://evil.example/socket"}))
    with pytest.raises(SlackLiveError):
        open_connection_url("xapp-1", transport=transport)
    plain = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"ok": True, "url": "ws://wss-primary.slack.com/x"}))
    with pytest.raises(SlackLiveError):
        open_connection_url("xapp-1", transport=plain)


def test_open_connection_url_http_error_is_not_fatal():
    with pytest.raises(SlackLiveError) as caught:
        open_connection_url("xapp-1", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert caught.value.fatal is False
