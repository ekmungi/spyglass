"""Slack capture: links the reader posts into one channel become from-you items.

The reader pastes a link (optionally with a few words of their own) into a private channel from
a phone or any other device; this module polls `conversations.history` and sends each link
through `capture_url`. A watermark (the newest message timestamp handled) is stored so each
message is processed once. Files and pictures attached to a message are downloaded and imported
as well (see `slack_files`).

NOTE: unit-tested with a fake transport only; it has not been run against a real workspace.
"""

import html
import logging
import re
import time
from collections.abc import Callable

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.radar.capture import CaptureError, capture_url
from spyglass_service.radar.egress import api_client, assert_secret_destination
from spyglass_service.radar.models import RadarDoc, dumps, loads, utcnow
from spyglass_service.radar.sources._common import HTTP_TIMEOUT, NotConfigured
from spyglass_service.radar.sources.slack_files import Download, import_message_files

logger = logging.getLogger(__name__)

WATERMARK_KEY = "slack_watermark"
HISTORY_URL = "https://slack.com/api/conversations.history"
# With no watermark yet, only the last week is read, so an old channel is not replayed.
FIRST_RUN_DAYS = 7
PAGE_LIMIT = 200
MAX_PAGES = 5
NOTE_LIMIT = 500
# Slack wraps links as <https://example.com|label> or <https://example.com>.
_LINK = re.compile(r"<(https?://[^>|\s]+)(?:\|([^>]*))?>")

# (url, params) -> decoded JSON response
Transport = Callable[[str, dict], dict]


def slack_configured(settings: Settings) -> bool:
    """True when a bot token and a channel id are both set."""
    return bool(settings.slack_bot_token and settings.slack_capture_channel)


def _http_transport(token: str) -> Transport:
    """A transport that calls the Slack Web API with the bot token."""
    def call(url: str, params: dict) -> dict:
        """GET one Web API method; the token may only go to Slack (checked before sending)."""
        assert_secret_destination("slack_bot_token", url)
        with api_client("slack_bot_token", timeout=HTTP_TIMEOUT) as client:
            response = client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.json()

    return call


def extract_links(text: str) -> list[str]:
    """http(s) links in a Slack message's markup, in order, without duplicates."""
    links: list[str] = []
    for match in _LINK.finditer(text or ""):
        link = html.unescape(match.group(1))
        if link not in links:
            links.append(link)
    return links


def message_note(text: str) -> str | None:
    """The reader's own words: the message with link markup removed and entities decoded."""
    without_links = _LINK.sub(lambda m: m.group(2) or "", text or "")
    note = " ".join(html.unescape(without_links).split())
    return note[:NOTE_LIMIT] or None


def _load_watermark(engine: Engine) -> str | None:
    """The newest Slack timestamp handled so far, if any."""
    with Session(engine) as session:
        row = session.get(RadarDoc, WATERMARK_KEY)
        data = loads(row.body if row else None, {})
    ts = data.get("ts") if isinstance(data, dict) else None
    return str(ts) if ts else None


def _save_watermark(engine: Engine, ts: str) -> None:
    """Store the watermark."""
    with Session(engine) as session:
        row = session.get(RadarDoc, WATERMARK_KEY) or RadarDoc(key=WATERMARK_KEY, body="{}")
        row.body = dumps({"ts": ts})
        row.updated_at = utcnow()
        session.add(row)
        session.commit()


def fetch_messages(transport: Transport, channel: str, oldest: str) -> list[dict]:
    """All messages newer than `oldest`, oldest first, following pagination.

    Raises:
        RuntimeError: Slack answered ok=false (bad token, wrong channel, missing scope).
    """
    messages: list[dict] = []
    cursor = None
    for _ in range(MAX_PAGES):
        params = {"channel": channel, "oldest": oldest, "limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        payload = transport(HISTORY_URL, params)
        if not payload.get("ok"):
            raise RuntimeError(f"Slack error: {payload.get('error', 'unknown')}")
        messages.extend(payload.get("messages", []))
        cursor = (payload.get("response_metadata") or {}).get("next_cursor")
        if not (payload.get("has_more") and cursor):
            break
    return sorted(messages, key=lambda m: float(m.get("ts", 0)))


def collect_slack(
    engine: Engine, settings: Settings, *, transport: Transport | None = None,
    download: Download | None = None,
) -> int:
    """Capture the links and files posted since the watermark; returns how many items were made.

    The watermark advances past every message handled (captured, rejected or without a link)
    and stops before a message whose capture failed unexpectedly, so that one is retried.

    Raises:
        NotConfigured: No bot token or channel is set.
        RuntimeError: Slack rejected the request.
    """
    if not slack_configured(settings):
        raise NotConfigured("Slack token or capture channel is not set")
    transport = transport or _http_transport(settings.slack_bot_token)
    oldest = _load_watermark(engine) or f"{time.time() - FIRST_RUN_DAYS * 86400:.6f}"
    captured = 0
    watermark = None
    for message in fetch_messages(transport, settings.slack_capture_channel, oldest):
        ts = str(message["ts"])
        if message.get("bot_id") or message.get("subtype") in ("bot_message", "channel_join"):
            watermark = ts
            continue
        text = message.get("text", "")
        links = extract_links(text)
        if not links and not message.get("files"):
            watermark = ts
            continue
        note = message_note(text)
        failed = False
        for link in links:
            try:
                capture_url(engine, settings, link, note=note, via="slack")
                captured += 1
            except CaptureError as exc:
                logger.info("Slack link rejected (%s): %s", exc, link)
            except Exception:  # noqa: BLE001 -- retry this message on the next run
                logger.exception("Slack capture failed for message %s", ts)
                failed = True
                break
        if not failed and message.get("files"):
            try:
                captured += len(import_message_files(
                    engine, settings, message, note=note, token=settings.slack_bot_token,
                    download=download, api=transport))
            except Exception:  # noqa: BLE001 -- a passing failure: read this message again next time
                logger.exception("Slack files of message %s were not imported", ts)
                failed = True
        if failed:
            break
        watermark = ts
    if watermark:
        _save_watermark(engine, watermark)
    return captured
