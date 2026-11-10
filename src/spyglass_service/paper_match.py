"""Telling that two links are the same paper.

Papers arrive as many forms of one link: with tracking parameters from a feed or a newsletter, an
arXiv abstract page or its PDF, with or without a trailing slash. The inbox compares their
canonical forms so a paper keeps one card however it was shared or collected.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlmodel import Session, select

from spyglass_service.api_pages import _find_existing
from spyglass_service.documents import normalize_url
from spyglass_service.models import Item

_TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src")


def canonical_paper_url(url: str) -> str:
    """One form per paper: no tracking parameters, fragment or trailing slash; arXiv abs -> pdf."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(_TRACKING)]
    path = parts.path.rstrip("/") or "/"
    clean = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))
    return normalize_url(clean)


def same_paper(session: Session, url: str, canonical: str) -> Item | None:
    """The item for this paper, also when it was stored under another form of its link (a feed's
    tracking parameters, an arXiv abstract page): candidates share the host and the last path
    segment, and match when their canonical forms are equal."""
    item = _find_existing(session, url, canonical)
    if item is not None:
        return item
    parts = urlsplit(canonical)
    last = parts.path.rstrip("/").rsplit("/", 1)[-1]
    if not parts.netloc or not last:
        return None
    pattern = f"%{parts.netloc.removeprefix('www.')}%{last}%"
    for candidate in session.exec(select(Item).where(Item.url.like(pattern)).limit(50)):  # type: ignore[attr-defined]
        if canonical in (canonical_paper_url(candidate.url), canonical_paper_url(candidate.external_id)):
            return candidate
    return None
