"""Helpers for the items API: kinds inferred from addresses, and de-duplicated related lists.

An item nobody has judged has no stored kind, so the feed's kind filter and the item's kind fall
back to what its address says (a paper site, a video site, a code host). The related items and
the story sources of an item are de-duplicated by normalised address and title (or publication),
because the same story often arrives through several feeds.
"""

import re
from urllib.parse import urlsplit

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from spyglass_service.models import Item
from spyglass_service.radar.models import Assessment

# What an unjudged item's address says it is.
ADDRESS_KINDS = {
    "paper": ("arxiv.org", "doi.org", "biorxiv.org", "medrxiv.org"),
    "video": ("youtube.com", "youtu.be"),
    "tool": ("github.com",),
}
# Query parameters that only track where a visitor came from, ignored when comparing addresses.
_TRACKING_PARAM = re.compile(r"^(?:utm_.*|fbclid|gclid|mc_.*|ref|ref_src|source|cmp|cid)$", re.IGNORECASE)


def address_kind(url: str) -> str | None:
    """The kind implied by an address (a paper site, a video site, a code host), or None."""
    host = (urlsplit(url or "").hostname or "").lower()
    for kind, domains in ADDRESS_KINDS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return kind
    return None


def kind_condition(kind: str):
    """SQL for the kind filter: the stored kind, or for an unjudged item the kind its address implies."""
    domains = ADDRESS_KINDS.get(kind)
    if not domains:
        return Assessment.kind == kind
    by_address = or_(*[or_(Item.url.ilike(f"%://{d}/%"), Item.url.ilike(f"%.{d}/%")) for d in domains])
    return or_(Assessment.kind == kind, and_(Assessment.id.is_(None), by_address))


def infer_kinds(items: list[dict]) -> list[dict]:
    """The items, with an unjudged item's kind taken from its address when that says more than "news"."""
    return [{**it, "kind": address_kind(it["url"]) or it["kind"]} if it.get("tier") == "unjudged" else it
            for it in items]


def address_key(url: str) -> str:
    """A web address reduced for comparison: no scheme, "www.", fragment, tracking parameters or trailing slash."""
    parts = urlsplit((url or "").strip().lower())
    query = "&".join(q for q in parts.query.split("&") if q and not _TRACKING_PARAM.match(q.split("=")[0]))
    path = parts.path.rstrip("/")
    return f"{(parts.hostname or '').removeprefix('www.')}{path}{'?' + query if query else ''}"


def title_key(title: str) -> str:
    """A title reduced to lower-case letters and digits for comparison."""
    return re.sub(r"[\W_]+", " ", title.lower()).strip()


def unique_related(candidates: list[dict], own_url: str, own_title: str) -> list[dict]:
    """The candidates without any that repeat the item itself or an earlier candidate (by address or title)."""
    seen_urls, seen_titles = {address_key(own_url)}, {title_key(own_title)}
    unique: list[dict] = []
    for candidate in candidates:
        url_k, title_k = address_key(candidate["url"]), title_key(candidate["title"])
        if url_k in seen_urls or title_k in seen_titles:
            continue
        seen_urls.add(url_k)
        seen_titles.add(title_k)
        unique.append(candidate)
    return unique


def unique_sources(items: list[dict], own_url: str) -> list[dict]:
    """`[{item_id, name, url}]` for the items, without the item's own address, repeated addresses or repeated publications.

    An item without a publication name is never merged with another by name.
    """
    seen_urls, seen_names = {address_key(own_url)}, set()
    sources: list[dict] = []
    for it in items:
        publication = (it["origin"] or "").strip().lower()
        if address_key(it["url"]) in seen_urls or (publication and publication in seen_names):
            continue
        seen_urls.add(address_key(it["url"]))
        seen_names.add(publication)
        sources.append({"item_id": it["id"], "name": it["origin"] or it["source"], "url": it["url"]})
    return sources


def story_sources(session: Session, item_id: int) -> list[dict]:
    """The other items in this item's story, as `[{item_id, name, url}]`.

    The members come from the most recent brief that showed the item, so the reader sees
    exactly the sources that brief counted.
    """
    # Imported here because `serialize` itself imports this module.
    from spyglass_service.radar.brief.document import story_members
    from spyglass_service.radar.serialize import radar_items

    ids = [i for i in story_members(session, item_id) if i != item_id]
    if not ids:
        # Not shown in any brief: fall back to items that carry the same event key.
        own = session.exec(
            select(Assessment.event_key).where(Assessment.item_id == item_id)
        ).first()
        if not own:
            return []
        ids = list(session.exec(
            select(Assessment.item_id)
            .where(Assessment.event_key == own, Assessment.item_id != item_id)
            .order_by(Assessment.item_id)
        ).all())
    if not ids:
        return []
    own_item = session.get(Item, item_id)
    return unique_sources(radar_items(session, ids), own_item.url if own_item else "")
