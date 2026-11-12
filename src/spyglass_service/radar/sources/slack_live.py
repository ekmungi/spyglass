"""Near-instant Slack capture over Socket Mode.

Slack delivers each new message in the capture channel over a WebSocket that this program opens
(no public address is needed): `apps.connections.open` with the app-level token returns a
`wss://` address, every event arrives in an envelope that must be acknowledged with its
`envelope_id`, and Slack asks for the connection to be replaced every few hours (`disconnect`
messages), which is answered by connecting again at once. Any other loss of the connection is
retried with a growing wait.

A message is handled exactly as the timer-based reader handles it (`sources.slack`): the links
are extracted with the same function, each goes through `capture_url(..., via="slack")` with the
message text as the note, and the same stored watermark is advanced, so the two never process one
message twice. On every (re)connection the listener first reads the channel history since the
watermark, which fills any gap left while it was disconnected.

NOTE: unit-tested with a fake socket only; it has not been run against a real workspace.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from spyglass_service.radar.capture import CaptureError, capture_url
from spyglass_service.radar.sources.slack import (
    FIRST_RUN_DAYS,
    _http_transport,
    _load_watermark,
    _save_watermark,
    extract_links,
    fetch_messages,
    message_note,
)
from spyglass_service.radar.sources._common import capture_sources_lock
from spyglass_service.radar.sources.slack_files import Download, import_message_files
from spyglass_service.radar.sources.slack_socket import (
    SlackLiveError,
    Socket,
    open_connection_url,
    websocket_connect,
)

__all__ = ["BACKOFF_MAX", "SlackLiveError", "SlackLiveListener", "live_configured",
           "open_connection_url"]

logger = logging.getLogger(__name__)

RECV_TIMEOUT = 5.0  # how often a quiet socket is checked for a stop request
BACKOFF_START = 1.0
BACKOFF_MAX = 60.0
# How long to wait after Slack refuses the token itself (revoked, wrong type): retrying quickly
# cannot help, and the reader has to fix it.
FATAL_WAIT = 300.0
# Longest a message waits for the lock shared with the timer-based readers (seconds).
LOCK_WAIT = 30.0
# Human messages carry no subtype; a file share and a broadcast thread reply are also theirs.
ACCEPTED_SUBTYPES = (None, "file_share", "thread_broadcast")


def live_configured(settings) -> bool:
    """True when the app-level token and the capture channel are both set."""
    return bool(getattr(settings, "slack_app_token", None)
                and getattr(settings, "slack_capture_channel", ""))


def _ts_value(ts: str | None) -> Decimal | None:
    """A Slack timestamp as an exact number (floats lose the last digit), or None if malformed."""
    try:
        return Decimal(str(ts))
    except (InvalidOperation, ValueError):
        return None


def _skip_reason(message: dict, channel: str) -> str | None:
    """Why a message is not a new human message in the capture channel, or None if it is."""
    if message.get("channel") not in (None, channel):
        return "another channel"
    if message.get("bot_id"):
        return "from a bot"
    if message.get("subtype") not in ACCEPTED_SUBTYPES:
        return f"subtype {message.get('subtype')}"
    thread = message.get("thread_ts")
    if thread and thread != message.get("ts") and message.get("subtype") != "thread_broadcast":
        return "a reply inside a thread"
    return None


class SlackLiveListener:
    """Receives Slack messages as they are posted and captures their links at once."""

    def __init__(
        self,
        engine,
        settings,
        *,
        on_capture: Callable[[int], None],
        connect: Callable[[str], Socket] | None = None,
        open_url: Callable[[], str] | None = None,
        wait: Callable[[float], bool] | None = None,
        fetch_history: Callable[[str], list[dict]] | None = None,
        download: Download | None = None,
    ) -> None:
        """`on_capture(item_id)` is called in the listener's thread for each captured link.

        The remaining arguments replace the real socket, the address request, the sleeping
        (returns True when asked to stop), the history read and the file download, for tests.
        """
        self._engine, self._settings, self._on_capture = engine, settings, on_capture
        self._download = download
        self._connect = connect or websocket_connect
        self._open_url = open_url or (lambda: open_connection_url(settings.slack_app_token))
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait
        self._fetch_history = fetch_history or self._default_history
        self._channel = str(getattr(settings, "slack_capture_channel", "") or "")
        self._thread: threading.Thread | None = None
        self._sock: Socket | None = None
        self._lock = threading.Lock()
        self._connected = False
        self._last_event_at: str | None = None
        self._last_error: str | None = None
        self._reconnects = 0
        self._captured = 0
        self._seen: set[str] = set()
        self._hold = False  # a capture failed: leave the watermark so it is retried

    # ---- control -------------------------------------------------------------------------

    def start(self) -> bool:
        """Start the listener thread; False (and nothing started) when not configured."""
        if not live_configured(self._settings):
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._stop.clear()
            self._thread = threading.Thread(target=self.run, daemon=True, name="radar-slack-live")
            self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the thread to end, close the socket it is waiting on, and wait up to `timeout`."""
        self._stop.set()
        with self._lock:
            sock, thread = self._sock, self._thread
        if sock is not None:
            sock.close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def status(self) -> dict:
        """A snapshot for the status page."""
        with self._lock:
            thread = self._thread
            return {
                "configured": live_configured(self._settings),
                "running": bool(thread and thread.is_alive()),
                "connected": self._connected, "last_event_at": self._last_event_at,
                "last_error": self._last_error, "reconnects": self._reconnects,
                "captured": self._captured,
            }

    def is_connected(self) -> bool:
        """True while the live connection is up (the timer-based reader may then stand down)."""
        with self._lock:
            return self._connected

    # ---- the connection loop -------------------------------------------------------------

    def run(self) -> None:
        """Connect, serve, and reconnect until stopped (the thread's target)."""
        delay = BACKOFF_START
        while not self._stop.is_set():
            sock: Socket | None = None
            try:
                sock = self._connect(self._open_url())
            except SlackLiveError as exc:
                self._note_error(str(exc))
                if self._wait(FATAL_WAIT if exc.fatal else delay):
                    break
                delay = delay if exc.fatal else min(delay * 2, BACKOFF_MAX)
                continue
            except Exception as exc:  # noqa: BLE001 -- any failure to connect is retried
                logger.warning("Slack live connection failed: %s", type(exc).__name__)
                self._note_error(f"Could not connect to Slack ({type(exc).__name__}).")
                if self._wait(delay):
                    break
                delay = min(delay * 2, BACKOFF_MAX)
                continue
            with self._lock:
                self._sock = sock
            if self._stop.is_set():
                sock.close()
                break
            outcome, saw_hello = self._serve(sock)
            sock.close()
            with self._lock:
                self._sock, self._connected = None, False
                self._reconnects += 1
            if outcome == "stopped":
                break
            if saw_hello:
                delay = BACKOFF_START
            if outcome == "refresh" and saw_hello:
                continue  # Slack asked for a new connection after a good one: no reason to wait
            if self._wait(delay):
                break
            delay = min(delay * 2, BACKOFF_MAX)
        with self._lock:
            self._connected = False

    def _serve(self, sock: Socket) -> tuple[str, bool]:
        """Read frames until the connection ends; returns (stopped|refresh|lost, saw_hello)."""
        saw_hello = False
        while not self._stop.is_set():
            try:
                raw = sock.recv(timeout=RECV_TIMEOUT)
            except TimeoutError:
                continue
            except (ConnectionError, OSError):
                return ("stopped" if self._stop.is_set() else "lost"), saw_hello
            frame = self._parse(raw)
            if frame is None:
                continue
            kind = frame.get("type")
            if kind == "hello":
                saw_hello = True
                with self._lock:
                    self._connected, self._last_error = True, None
                self._catch_up()
            elif kind == "disconnect":
                logger.info("Slack asked for a new connection (%s)", frame.get("reason"))
                return "refresh", saw_hello
            elif frame.get("envelope_id"):
                try:
                    sock.send(json_ack(frame["envelope_id"]))
                except (ConnectionError, OSError):
                    return "lost", saw_hello
                if kind == "events_api":
                    self._on_event((frame.get("payload") or {}).get("event"))
        return "stopped", saw_hello

    @staticmethod
    def _parse(raw: str | bytes) -> dict | None:
        """A received frame as a dict, or None for anything that is not a JSON object."""
        try:
            frame = json.loads(raw)
        except (TypeError, ValueError):
            logger.debug("ignoring a Slack frame that is not JSON")
            return None
        return frame if isinstance(frame, dict) else None

    def _note_error(self, text: str) -> None:
        """Remember the latest problem for the status page."""
        with self._lock:
            self._last_error = text

    # ---- handling messages ---------------------------------------------------------------

    def _on_event(self, event: object) -> None:
        """Handle one Events API event: only messages are of interest."""
        with self._lock:
            self._last_event_at = datetime.now(UTC).isoformat()
        if isinstance(event, dict) and event.get("type") == "message":
            self._process([event])

    def _default_history(self, oldest: str) -> list[dict]:
        """Channel history since `oldest` with the bot token; none when there is no bot token."""
        token = getattr(self._settings, "slack_bot_token", None)
        if not token:
            return []
        return fetch_messages(_http_transport(token), self._channel, oldest)

    def _catch_up(self) -> None:
        """Handle messages posted since the watermark (covers time spent disconnected)."""
        self._seen.clear()
        self._hold = False
        oldest = _load_watermark(self._engine) or f"{time.time() - FIRST_RUN_DAYS * 86400:.6f}"
        try:
            messages = self._fetch_history(oldest)
        except Exception as exc:  # noqa: BLE001 -- live events still work without the catch-up
            logger.warning("Slack catch-up failed: %s", exc)
            self._note_error(f"Reading the channel history failed: {exc}")
            return
        self._process(messages)

    def _process(self, messages: list[dict]) -> None:
        """Handle messages while holding the lock the Gmail and Slack readers share.

        The timer-based reader and the cycle's collectors read and rewrite the same watermark;
        the lock keeps one writer at a time. The callbacks run after the lock is released.
        """
        if not capture_sources_lock.acquire(timeout=LOCK_WAIT):
            logger.warning("Slack messages left for the next check: the capture lock is busy")
            self._hold = True  # do not move the watermark past what was not handled
            return
        announced: list[int] = []
        try:
            for message in messages:
                announced += self._handle_message(message)
        finally:
            capture_sources_lock.release()
        for item_id in announced:
            self._announce(item_id)

    def _handle_message(self, message: dict) -> list[int]:
        """Capture the links of one new human message, advance the shared watermark, return ids."""
        ts = str(message.get("ts") or "")
        value = _ts_value(ts)
        reason = _skip_reason(message, self._channel)
        if value is None or reason:
            logger.debug("Slack message %s ignored: %s", ts, reason or "no timestamp")
            return []
        stored = _load_watermark(self._engine)
        mark = _ts_value(stored) if stored else None
        if ts in self._seen or (mark is not None and value <= mark):
            return []  # already handled here, by the timer-based reader, or by an earlier run
        text = str(message.get("text") or "")
        note = message_note(text)
        failed = False
        captured: list[int] = []
        for link in extract_links(text):
            try:
                item_id = capture_url(self._engine, self._settings, link, note=note, via="slack")
            except CaptureError as exc:
                logger.info("Slack link rejected (%s): %s", exc, link)
                continue
            except Exception:  # noqa: BLE001 -- keep the watermark so the message is retried
                logger.exception("Slack capture failed for message %s", ts)
                failed = True
                break
            with self._lock:
                self._captured += 1
            captured.append(item_id)
        if not failed and message.get("files"):
            try:
                made = import_message_files(
                    self._engine, self._settings, message, note=note,
                    token=getattr(self._settings, "slack_bot_token", None), download=self._download)
            except Exception:  # noqa: BLE001 -- keep the watermark so the message is retried
                logger.exception("Slack files of message %s were not imported", ts)
                failed, made = True, []
            with self._lock:
                self._captured += len(made)
            captured += made
        if failed:
            self._hold = True
            return captured
        self._seen.add(ts)
        if not self._hold:
            _save_watermark(self._engine, ts)
        return captured

    def _announce(self, item_id: int) -> None:
        """Tell the caller an item was captured; its failure must not stop the listener."""
        try:
            self._on_capture(item_id)
        except Exception:  # noqa: BLE001 -- a bug in the callback must not drop the connection
            logger.exception("the Slack capture callback failed for item %s", item_id)


def json_ack(envelope_id: str) -> str:
    """The acknowledgment Slack expects for an envelope."""
    return json.dumps({"envelope_id": envelope_id})
