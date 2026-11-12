"""Read one email message into the fields the radar needs (sender, subject, links, bodies).

Pure functions over `email.message.EmailMessage`, so they are tested with fixture messages and
never touch a mail server.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import quote

from bs4 import BeautifulSoup

# Link texts that newsletters use for their web edition.
_BROWSER_LINK = re.compile(
    r"(view|read|open)\s+(this\s+)?(email|message|newsletter|post|story|it)?\s*"
    r"(in\s+(your\s+|a\s+)?browser|online|on\s+the\s+web|on\s+web|as\s+a?\s*web\s*page)"
    r"|view\s+as\s+(a\s+)?web\s*page|read\s+online|read\s+in\s+browser",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
GMAIL_SEARCH = "https://mail.google.com/mail/u/0/#search/rfc822msgid:{id}"


@dataclass(frozen=True)
class ParsedMessage:
    """The radar's view of one email."""

    message_id: str
    sender: str
    subject: str
    date: datetime | None
    html: str
    text: str
    browser_url: str | None


def _body(msg: EmailMessage, kind: str) -> str:
    """The text of the best part of `kind` ("html" or "plain"); empty when none exists."""
    part = msg.get_body(preferencelist=(kind,))
    if part is None:
        return ""
    try:
        return str(part.get_content())
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    """Plain text of an HTML body: scripts and styles dropped, blank lines collapsed."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line for line in lines if line)).strip()


def find_browser_link(html: str) -> str | None:
    """The "view in browser" / "read online" link of a newsletter, when it has one."""
    if not html:
        return None
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        label = " ".join(anchor.get_text(" ").split())
        href = anchor["href"].strip()
        if href.lower().startswith(("http://", "https://")) and _BROWSER_LINK.search(label):
            return href
    return None


def first_url(text: str) -> str | None:
    """The first http(s) address in a piece of text, without trailing punctuation."""
    match = _URL.search(text or "")
    return match.group(0).rstrip(".,;:!?") if match else None


def parse_message(msg: EmailMessage, fallback_id: str) -> ParsedMessage:
    """Extract the fields from a message. `fallback_id` stands in for a missing Message-ID."""
    name, address = parseaddr(str(msg.get("From", "")))
    sender = name.strip() or address.split("@")[0] or "Unknown sender"
    message_id = str(msg.get("Message-ID", "")).strip().strip("<>") or fallback_id
    date = None
    if msg.get("Date"):
        try:
            date = parsedate_to_datetime(str(msg["Date"]))
            date = date if date.tzinfo else date.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            date = None
    html = _body(msg, "html")
    text = _body(msg, "plain") or (html_to_text(html) if html else "")
    return ParsedMessage(
        message_id=message_id,
        sender=sender,
        subject=" ".join(str(msg.get("Subject", "")).split()) or "(no subject)",
        date=date,
        html=html,
        text=text.strip(),
        browser_url=find_browser_link(html),
    )


def item_url(parsed: ParsedMessage) -> str:
    """Where the item opens: the web edition when there is one, else the Gmail message."""
    return parsed.browser_url or GMAIL_SEARCH.format(id=quote(parsed.message_id, safe=""))
