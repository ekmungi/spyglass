"""Gmail over IMAP: newsletters become items with a reader copy, mailed-to-self links are captured.

Two labels are read, both read-only (messages are never marked read or moved):
  * the newsletter label: one item per message, with the email body as the reader document;
  * the capture label: the first link in the message goes through `capture_url`.
Which messages were handled is remembered per label as IMAP UIDs in the "gmail_seen" document,
so a message is processed once and a failed one is retried on the next run.

NOTE: this module is unit-tested against fixture messages and a fake IMAP client only. It has
not been exercised against a real Gmail account.
"""

import email
import email.policy
import imaplib
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

import nh3
from bs4 import BeautifulSoup
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.config import Settings
from spyglass_service.content_store import store_fulltext
from spyglass_service.ingest import store_items
from spyglass_service.radar.capture import CaptureError, capture_url
from spyglass_service.radar.egress import assert_secret_destination
from spyglass_service.radar.models import RadarDoc, ReaderDoc, dumps, loads, utcnow
from spyglass_service.radar.sources._common import (
    NotConfigured,
    host_of,
    item_ids_by_external,
    short_hash,
)
from spyglass_service.radar.sources.email_parse import (
    ParsedMessage,
    first_url,
    html_to_text,
    item_url,
    parse_message,
)

logger = logging.getLogger(__name__)

SOURCE = "newsletter"
SEEN_KEY = "gmail_seen"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
# Only mail from this many days back is listed; the seen-UID list does the real de-duplication.
LOOKBACK_DAYS = 14
# Messages handled per label per run, oldest first, so a large backlog drains over a few runs.
MAX_PER_RUN = 60
# Seen UIDs kept per label; older ones fall off together with the look-back window.
SEEN_CAP = 3000
NOTE_LIMIT = 500

# Fallback sanitizer allowlist (used only when the reader sanitizer is unavailable).
_SAFE_TAGS = {"p", "br", "h1", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "a", "img",
              "strong", "em", "b", "i", "table", "thead", "tbody", "tr", "td", "th", "pre",
              "code", "hr", "figure", "figcaption", "span", "div"}
_SAFE_ATTRS = {"a": {"href"}, "img": {"src", "alt", "width", "height"}}

ConnectFn = Callable[[Settings], Any]


def gmail_configured(settings: Settings) -> bool:
    """True when both the address and the app password are set."""
    return bool(settings.gmail_address and settings.gmail_app_password)


def _connect(settings: Settings) -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP connection to Gmail.

    The app password may only go to Gmail's IMAP server; the check runs before connecting.
    """
    assert_secret_destination("gmail_app_password", f"imaps://{IMAP_HOST}:{IMAP_PORT}/")
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
    conn.login(settings.gmail_address, settings.gmail_app_password)
    return conn


def _load_seen(engine: Engine) -> dict:
    """The per-label seen state: {label: {"validity": str, "uids": [int]}}."""
    with Session(engine) as session:
        row = session.get(RadarDoc, SEEN_KEY)
        data = loads(row.body if row else None, {})
    return data if isinstance(data, dict) else {}


def _save_seen(engine: Engine, seen: dict) -> None:
    """Persist the seen state."""
    with Session(engine) as session:
        row = session.get(RadarDoc, SEEN_KEY) or RadarDoc(key=SEEN_KEY, body="{}")
        row.body = dumps(seen)
        row.updated_at = utcnow()
        session.add(row)
        session.commit()


def _fetch_new(conn: Any, label: str, state: dict) -> tuple[str, list[tuple[int, Any]]]:
    """Select `label` read-only and fetch the messages whose UID is not in `state`.

    Returns (uidvalidity, [(uid, EmailMessage)]) oldest first, at most MAX_PER_RUN.
    """
    quoted = '"' + label.replace("\\", "\\\\").replace('"', '\\"') + '"'
    status, _ = conn.select(quoted, readonly=True)
    if status != "OK":
        raise RuntimeError(f"Gmail label {label!r} was not found")
    _, validity_data = conn.response("UIDVALIDITY")
    validity = (validity_data[0] or b"").decode() if validity_data else ""
    since = (datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
    status, data = conn.uid("SEARCH", None, "SINCE", since)
    if status != "OK":
        raise RuntimeError(f"Gmail search failed for label {label!r}")
    seen = set(state.get("uids", [])) if state.get("validity") == validity else set()
    uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) not in seen)
    messages = []
    for uid in uids[:MAX_PER_RUN]:
        status, parts = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
        if status == "OK" and raw:
            messages.append((uid, email.message_from_bytes(raw, policy=email.policy.default)))
    return validity, messages


def _remember(state: dict, validity: str, done: list[int]) -> dict:
    """A new per-label state with `done` UIDs added (reset when the validity changed)."""
    kept = state.get("uids", []) if state.get("validity") == validity else []
    return {"validity": validity, "uids": sorted(set(kept) | set(done))[-SEEN_CAP:]}


def sanitize_email_html(html: str, base_url: str) -> str:
    """Safe HTML for the reader: the reader sanitizer when present, else a strict nh3 pass."""
    try:
        from spyglass_service.radar.reader.sanitize import clean_html

        return clean_html(html, base_url)
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 -- a sanitizer bug must not lose the newsletter
        logger.exception("reader sanitizer failed; using the fallback")
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):  # drop 1-pixel tracking images
        if str(img.get("width", "")) in ("0", "1") or str(img.get("height", "")) in ("0", "1"):
            img.decompose()
    return nh3.clean(str(soup), tags=_SAFE_TAGS, attributes=_SAFE_ATTRS,
                     url_schemes={"http", "https", "mailto"})


def _reader_html(parsed: ParsedMessage, url: str) -> str:
    """Sanitized reader HTML; a plain-text body is wrapped into paragraphs."""
    if parsed.html:
        return sanitize_email_html(parsed.html, url)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", parsed.text) if p.strip()]
    return "".join(f"<p>{escape(p)}</p>" for p in paragraphs)


def _store_newsletters(engine: Engine, parsed: list[ParsedMessage]) -> int:
    """Create items, reader documents and stored text for newsletter messages; returns new items."""
    items = [
        CollectedItem(
            source=SOURCE,
            external_id="mail-" + short_hash(p.message_id),
            title=p.subject,
            url=item_url(p),
            summary=" ".join(p.text.split())[:400] or None,
            published_at=p.date,
            origin=p.sender,
        )
        for p in parsed
    ]
    new = store_items(engine, items)
    ids = item_ids_by_external(engine, SOURCE, [i.external_id for i in items])
    for message, item in zip(parsed, items, strict=True):
        item_id = ids.get(item.external_id)
        if item_id is None:
            continue
        with Session(engine) as session:
            if session.exec(select(ReaderDoc).where(ReaderDoc.item_id == item_id)).first():
                continue
            session.add(ReaderDoc(
                item_id=item_id, kind="email", html=_reader_html(message, item.url),
                title=message.subject, byline=message.sender, site=host_of(item.url),
                word_count=len(message.text.split()), source_url=item.url, status="ok",
            ))
            session.commit()
        if message.text:
            store_fulltext(engine, item_id=item_id, markdown=message.text,
                           source_url=item.url, content_type="text/html")
    return new


def _capture_target(parsed: ParsedMessage) -> tuple[str | None, str | None]:
    """(link, note) for a mailed-to-self message: its first link and the reader's own words."""
    text = parsed.text or html_to_text(parsed.html)
    link = first_url(text)
    if link is None and parsed.html:
        anchors = BeautifulSoup(parsed.html, "html.parser").find_all("a", href=True)
        link = next((a["href"] for a in anchors if a["href"].startswith(("http://", "https://"))), None)
    words = " ".join(text.replace(link or "", " ").split())[:NOTE_LIMIT]
    subject = parsed.subject
    if subject == "(no subject)" or (link and link in subject):
        subject = ""
    return link, (words or subject or None)


def _run_label(conn: Any, engine: Engine, seen: dict, label: str,
               handle: Callable[[list[tuple[int, Any]]], list[int]]) -> int:
    """Fetch a label's new messages, hand them to `handle`, and remember the UIDs it finished."""
    validity, messages = _fetch_new(conn, label, seen.get(label, {}))
    done = handle(messages)
    seen[label] = _remember(seen.get(label, {}), validity, done)
    _save_seen(engine, seen)
    return len(done)


def collect_gmail(
    engine: Engine,
    settings: Settings,
    *,
    connect: ConnectFn | None = None,
    newsletters: bool = True,
    captures: bool = True,
) -> dict[str, int]:
    """Read the newsletter and capture labels.

    Returns:
        {"newsletter": new items, "capture": links captured}.

    Raises:
        NotConfigured: No address or app password is set.
        RuntimeError: Every requested label failed.
    """
    if not gmail_configured(settings):
        raise NotConfigured("Gmail address or app password is not set")
    conn = (connect or _connect)(settings)
    seen = _load_seen(engine)
    result = {"newsletter": 0, "capture": 0}
    errors: list[str] = []
    try:
        if newsletters:
            try:
                def handle_news(messages: list[tuple[int, Any]]) -> list[int]:
                    parsed = []
                    for uid, msg in messages:
                        try:
                            parsed.append(parse_message(
                                msg, f"{settings.gmail_newsletter_label}:{uid}"))
                        except Exception:  # noqa: BLE001 -- skip an unreadable message for good
                            logger.exception("newsletter email %s could not be read", uid)
                    result["newsletter"] = _store_newsletters(engine, parsed)
                    return [u for u, _ in messages]

                _run_label(conn, engine, seen, settings.gmail_newsletter_label, handle_news)
            except Exception as exc:  # noqa: BLE001 -- the capture label still runs
                logger.exception("Gmail newsletter label failed")
                errors.append(f"newsletters: {exc}")
        if captures:
            try:
                def handle_captures(messages: list[tuple[int, Any]]) -> list[int]:
                    return _capture_messages(engine, settings, messages, result)

                _run_label(conn, engine, seen, settings.gmail_capture_label, handle_captures)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gmail capture label failed")
                errors.append(f"captures: {exc}")
    finally:
        try:
            conn.logout()
        except (imaplib.IMAP4.error, OSError):
            logger.debug("Gmail logout failed", exc_info=True)
    if errors and len(errors) == int(newsletters) + int(captures):
        raise RuntimeError("; ".join(errors))
    return result


def sent_by_reader(msg: Any, own_address: str | None) -> bool:
    """True when a message's From address is the reader's own and no check on it failed.

    A capture is acted on as if the reader asked for it, so a message from anyone else under
    the capture label is ignored. A message whose authentication results report a DKIM or
    SPF failure is ignored too, because its From line may be forged.
    """
    from email.utils import parseaddr

    if not own_address:
        return False
    _name, address = parseaddr(str(msg.get("From", "")))
    if address.strip().lower() != own_address.strip().lower():
        return False
    results = " ".join(str(v) for v in (msg.get_all("Authentication-Results") or [])).lower()
    return "dkim=fail" not in results and "spf=fail" not in results


def _capture_messages(engine: Engine, settings: Settings, messages: list[tuple[int, Any]],
                      result: dict[str, int]) -> list[int]:
    """Capture each message's link; returns the UIDs that need no retry."""
    finished = []
    for uid, msg in messages:
        if not sent_by_reader(msg, settings.gmail_address):
            # Anyone can mail an address; only the reader's own messages are captures.
            logger.info("capture email %s is not from the reader's own address; skipped", uid)
            finished.append(uid)
            continue
        try:
            parsed = parse_message(msg, f"{settings.gmail_capture_label}:{uid}")
            link, note = _capture_target(parsed)
        except Exception:  # noqa: BLE001 -- one unreadable message must not stop the label
            logger.exception("capture email %s could not be read; will retry", uid)
            continue
        if link is None:
            logger.info("capture email %s has no link; skipped", uid)
            finished.append(uid)
            continue
        try:
            capture_url(engine, settings, link, note=note, via="email")
            result["capture"] += 1
            finished.append(uid)
        except CaptureError as exc:
            logger.info("capture email %s rejected: %s", uid, exc)
            finished.append(uid)
        except Exception:  # noqa: BLE001 -- left unseen so the next run retries it
            logger.exception("capture email %s failed; will retry", uid)
    return finished
