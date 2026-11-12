"""Capture: turn a link the reader sends in (any device, any channel) into a from-you item.

Every channel ends here: the Capture box, a Slack message, an email to self, a Raindrop bookmark.
A capture never fails because the page could not be fetched; the item exists the moment the
link is accepted, with the page's title when a quick, guarded fetch finds it. Every capture
records when the reader sent the item (`ItemState.captured_at`), also for an item the radar
already had, because the brief's "From you" section is built from that time. An item the
reader sends in that was judged irrelevant is sent back to be digested: the reader sending it
is new evidence.
"""

import logging
import socket
from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunparse

from sqlalchemy import Engine, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from spyglass_service.cards import materialize_cards
from spyglass_service.config import Settings
from spyglass_service.models import Item
from spyglass_service.radar import netguard
from spyglass_service.radar.assess_prompt import tier_for
from spyglass_service.radar.models import Assessment, ItemState, Signal, utcnow
from spyglass_service.radar.sources._common import host_of, short_hash

logger = logging.getLogger(__name__)

SOURCE = "capture"
# Query parameters that only track the sender; dropping them lets one page dedupe to one item.
_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "mkt_tok", "ref_src")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp")
MAX_URL_LENGTH = 2048
_REFUSED = "Links to this computer or a private network are not accepted."

TitleFn = Callable[[str], str | None]
Resolver = Callable[[str], list[str]]


class CaptureError(ValueError):
    """The link cannot be captured; the message says why in a sentence fit for the reader."""


def _numeric_host(host: str) -> str | None:
    """The IPv4 address a numeric host stands for, or None when the host is a name.

    Short, octal, hexadecimal and decimal forms such as 127.1, 0177.0.0.1, 0x7f.1 and 2130706433
    all mean 127.0.0.1 to the system resolver, although Python's address parser rejects them.
    A real host name never ends in an all-digit label, so such a host is treated as numeric.
    """
    last = host.rsplit(".", 1)[-1]
    if not (last.isdigit() or last.startswith("0x")):
        return None
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        return "0.0.0.0"  # numeric-looking but not an address: refused as unspecified


def _check_host(host: str) -> None:
    """Refuse local, internal and private hosts, however they are written (no lookups)."""
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES) or netguard.is_internal_host(host):
        raise CaptureError(_REFUSED)
    if ":" in host:
        return  # an IPv6 literal; private ranges were refused just above
    numeric = _numeric_host(host)
    if numeric is not None and (numeric != host or netguard.is_private_address(numeric)):
        # A non-standard way of writing an address is only ever used to hide where it points.
        raise CaptureError(_REFUSED)
    if "." not in host:
        raise CaptureError(_REFUSED)


def validate_capture_url(url: str) -> str:
    """Check a link is a public http(s) address and return its normalised form.

    Normalising lowercases the scheme and host, drops a trailing dot in the host, the fragment,
    default ports and tracking parameters. Raises CaptureError for other schemes (file:,
    javascript:, ...), addresses with credentials, and local, private or internal hosts in any
    spelling. Whether a public-looking name resolves to a private address is checked by
    `capture_url`, which can look the name up.
    """
    raw = (url or "").strip()
    if not raw or len(raw) > MAX_URL_LENGTH:
        raise CaptureError("The link is empty or too long.")
    parts = urlparse(raw)
    if parts.scheme.lower() not in ("http", "https"):
        raise CaptureError("Only http and https links can be captured.")
    try:
        port = parts.port
    except ValueError as exc:
        raise CaptureError("The link has an invalid port.") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise CaptureError("The link has no host name.")
    if parts.username or parts.password:
        raise CaptureError("Links that contain a user name or password are not accepted.")
    _check_host(host)
    shown_host = f"[{host}]" if ":" in host else host
    default_port = 443 if parts.scheme.lower() == "https" else 80
    netloc = shown_host if port in (None, default_port) else f"{shown_host}:{port}"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not k.lower().startswith(_TRACKING_PARAMS)])
    return urlunparse((parts.scheme.lower(), netloc, parts.path or "/", parts.params, query, ""))


def _resolve(host: str) -> list[str]:
    """All addresses a host name resolves to (netguard's resolver; replaced in tests)."""
    return netguard.resolve(host)


def _assert_public(normalized: str, resolver: Resolver | None) -> None:
    """Refuse a link that netguard does not accept as public; an unresolvable name is kept.

    The decision is `netguard.is_public_url`'s, made on the addresses the name resolves to now.
    A name that does not resolve (offline, or a typo) is still captured: the item is only a
    record, and the title fetch refuses to request a name it cannot resolve.
    """
    host = urlsplit(normalized).hostname or ""
    try:
        addresses = (resolver or _resolve)(host)
    except OSError:
        return
    if not netguard.is_public_url(normalized, resolver=lambda _host: addresses):
        raise CaptureError(_REFUSED)


def url_forms(normalized: str) -> set[str]:
    """Addresses that name the same page: itself, with/without a trailing slash, and the
    arXiv abstract/PDF pair."""
    bare = normalized.rstrip("/")
    forms = {normalized, bare, bare + "/"}
    if "arxiv.org/abs/" in normalized:
        forms.add(normalized.replace("/abs/", "/pdf/"))
    if "arxiv.org/pdf/" in normalized:
        forms.add(normalized.replace("/pdf/", "/abs/").removesuffix(".pdf"))
    return forms


def _default_title(url: str) -> str | None:
    """The page's own title from the guarded, size-capped title fetch (None on any failure)."""
    from spyglass_service.radar.capture_title import fetch_title

    return fetch_title(url)


def untitled(url: str) -> str:
    """The readable stand-in title of a page whose own title could not be fetched."""
    return f"{urlsplit(url).hostname or url} (title not available)"


def _safe_title(url: str, title_fetch: TitleFn | None) -> str:
    """A fetched title, or a readable stand-in when the fetch fails: a title is never fatal."""
    try:
        title = (title_fetch or _default_title)(url)
    except Exception:  # noqa: BLE001 -- the capture must succeed without a title
        logger.warning("title fetch failed for %s; using the host name as title", url)
        title = None
    return (title or "").strip() or untitled(url)


def _rejudge(session: Session, item_id: int) -> None:
    """Treat the reader's capture as new evidence for an item already judged.

    An item judged "out" goes back to the triage stage with its digest attempts reset, so the
    pipeline digests it again (reader items are always digested); a failed triage gets its
    attempts back. Any judged item is lifted to the reader's floor tier.
    """
    row = session.exec(select(Assessment).where(Assessment.item_id == item_id)).first()
    if row is None:
        return
    if row.tier == "unjudged":
        row.triage_attempts, row.digest_attempts = 0, 0
    else:
        if row.tier == "out":
            row.stage, row.digest_attempts, row.error = "triage", 0, None
        row.tier = tier_for(row.score, from_user=True)
    session.add(row)


def _mark_from_user(
    session: Session, item_id: int, via: str, note: str | None, *, rejudge: bool = False
) -> ItemState:
    """Upsert the item's state as from-you and stamp the capture time.

    The first channel that sent it is kept; the capture time is updated on every capture.
    """
    state = session.exec(select(ItemState).where(ItemState.item_id == item_id)).first()
    if state is None:
        state = ItemState(item_id=item_id)
    if not state.from_user:
        state.from_user = True
        state.captured_via = via
    if note:
        state.user_note = note
    state.captured_at = state.updated_at = utcnow()
    session.add(state)
    session.add(Signal(item_id=item_id, kind="capture", value=via))
    if rejudge:
        _rejudge(session, item_id)
    return state


def capture_url(
    engine: Engine,
    settings: Settings | None,
    url: str,
    note: str | None = None,
    via: str = "manual",
    *,
    title_fetch: TitleFn | None = None,
    resolver: Resolver | None = None,
) -> int:
    """Add a link as a from-you item (or mark the existing item) and return its item id.

    Args:
        engine: Database engine.
        settings: Runtime settings (unused today; kept for the shared collector signature).
        url: The link; validated by `validate_capture_url`.
        note: The reader's own words about it, shown with the item.
        via: The channel: manual, slack, email, raindrop.
        title_fetch: Callable returning a page title; the guarded title fetch by default.
        resolver: Callable resolving a host name to addresses; the system resolver by default.

    Returns:
        The item id, whether newly created or already present.

    Raises:
        CaptureError: When the link is not an acceptable public http(s) address.
    """
    normalized = validate_capture_url(url)
    _assert_public(normalized, resolver)
    forms = url_forms(normalized)

    def find(session: Session) -> Item | None:
        return session.exec(
            select(Item).where(or_(Item.url.in_(forms), Item.external_id.in_(forms)))  # type: ignore[attr-defined]
        ).first()

    with Session(engine) as session:
        existing = find(session)
        if existing is not None:
            _mark_from_user(session, existing.id, via, note, rejudge=True)
            session.commit()
            return existing.id

    title = _safe_title(normalized, title_fetch)  # network call, outside any DB session
    try:
        with Session(engine) as session:
            item = Item(
                source=SOURCE,
                external_id="cap-" + short_hash(normalized),
                title=title,
                url=normalized,
                origin=host_of(normalized),
                published_at=None,
            )
            session.add(item)
            session.flush()
            item_id = item.id
            _mark_from_user(session, item_id, via, note)
            session.commit()
    except IntegrityError:
        # Two captures of the same link raced past the lookup; answer with the winner.
        with Session(engine) as session:
            existing = find(session) or session.exec(
                select(Item).where(Item.source == SOURCE,
                                   Item.external_id == "cap-" + short_hash(normalized))
            ).first()
            if existing is None:
                raise
            _mark_from_user(session, existing.id, via, note)
            session.commit()
            return existing.id
    materialize_cards(engine)
    return item_id


def mark_raindrop_captures(engine: Engine) -> int:
    """Mark every Raindrop bookmark as from-you (the reader bookmarked it on purpose).

    Idempotent: items already marked are left alone. The capture time of a newly marked
    bookmark is when it was collected, so bookmarks imported in bulk long ago never flood the
    brief's "From you" section.

    Returns:
        The number of items newly marked.
    """
    marked = 0
    with Session(engine) as session:
        already = set(session.exec(
            select(ItemState.item_id).where(ItemState.from_user == True)  # noqa: E712
        ).all())
        rows = session.exec(select(Item.id, Item.fetched_at).where(Item.source == "raindrop")).all()
        for item_id, fetched_at in rows:
            if item_id in already:
                continue
            state = _mark_from_user(session, item_id, "raindrop", None, rejudge=True)
            state.captured_at = fetched_at
            marked += 1
        session.commit()
    return marked
