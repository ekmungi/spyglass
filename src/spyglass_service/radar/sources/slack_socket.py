"""The wire side of Slack's Socket Mode: asking for a connection address and the WebSocket itself.

`open_connection_url` sends the app-level token to slack.com only, in a header, and accepts only a
`wss://` address on slack.com in return. `websocket_connect` opens that address with the
`websockets` package (installed with the web server). Both are kept apart from the listener so the
listener can be tested with a fake socket.
"""

import logging
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from spyglass_service.radar.egress import api_client, assert_secret_destination

logger = logging.getLogger(__name__)

OPEN_URL = "https://slack.com/api/apps.connections.open"
SLACK_HOST = "slack.com"
HTTP_TIMEOUT = 15.0
# Errors that retrying quickly cannot fix (bad, revoked or wrong-type token); the listener waits
# long after one so a wrong token does not hammer Slack, and the message tells the reader what to fix.
FATAL_ERRORS = frozenset({
    "invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive",
    "not_allowed_token_type", "missing_scope", "invalid_token"})


class SlackLiveError(RuntimeError):
    """Slack refused to open the live connection; `fatal` when only the reader can fix it."""

    def __init__(self, message: str, *, fatal: bool = False) -> None:
        """`message` is short, safe to show and never contains a token."""
        super().__init__(message)
        self.fatal = fatal


class Socket(Protocol):
    """What the listener needs from a socket: recv (TimeoutError / ConnectionError), send, close."""

    def recv(self, timeout: float | None = None) -> str | bytes:
        """Next frame; raises TimeoutError when nothing arrived and ConnectionError when closed."""

    def send(self, data: str) -> None:
        """Send one text frame."""

    def close(self) -> None:
        """Close the connection."""


class _WebSocket:
    """The `websockets` synchronous client, reporting a closed connection as ConnectionError."""

    def __init__(self, ws) -> None:
        """Wrap an open `websockets.sync.client.ClientConnection`."""
        self._ws = ws

    def recv(self, timeout: float | None = None) -> str | bytes:
        """Next frame (TimeoutError when none arrived within `timeout`)."""
        from websockets.exceptions import ConnectionClosed

        try:
            return self._ws.recv(timeout=timeout)
        except ConnectionClosed as exc:
            raise ConnectionError("the Slack connection closed") from exc

    def send(self, data: str) -> None:
        """Send one text frame."""
        from websockets.exceptions import ConnectionClosed

        try:
            self._ws.send(data)
        except ConnectionClosed as exc:
            raise ConnectionError("the Slack connection closed") from exc

    def close(self) -> None:
        """Close, ignoring errors from a connection that is already gone."""
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001 -- closing a dead socket may fail in any way
            logger.debug("closing the Slack socket failed", exc_info=True)


def websocket_connect(url: str) -> Socket:
    """Open the `wss://` address with the `websockets` package (installed with the web server)."""
    from websockets.sync.client import connect

    return _WebSocket(connect(url, open_timeout=15, close_timeout=5, max_size=2 ** 20))


def open_connection_url(app_token: str, *, transport: httpx.BaseTransport | None = None) -> str:
    """Ask Slack for a one-use `wss://` address. The token goes only to slack.com, in a header.

    Raises:
        SlackLiveError: Slack refused (fatal for a bad or wrong-type token) or could not be
            reached, or answered with an address that is not a slack.com `wss://` address.
    """
    try:
        # The app token may only go to Slack; the client re-checks every request it sends.
        assert_secret_destination("slack_app_token", OPEN_URL)
        with api_client("slack_app_token", timeout=HTTP_TIMEOUT, transport=transport) as client:
            response = client.post(OPEN_URL, headers={"Authorization": f"Bearer {app_token}"})
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SlackLiveError(f"Could not reach Slack ({type(exc).__name__}).") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        error = str((payload or {}).get("error", "unknown")) if isinstance(payload, dict) else "unknown"
        raise SlackLiveError(f"Slack refused the live connection: {error}.",
                             fatal=error in FATAL_ERRORS)
    url = str(payload.get("url", ""))
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "wss" or not (host == SLACK_HOST or host.endswith("." + SLACK_HOST)):
        raise SlackLiveError("Slack answered with a connection address that is not a slack.com address.")
    return url
