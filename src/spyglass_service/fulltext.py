"""On-demand full-text fetch + store orchestration.

Pure-Python path used by the dashboard's per-card fetch and by the relevance skill:
fetch the document behind a card's link and store its markdown in SQLite. No Claude.
Also repairs source-truncated titles (Raindrop clips long ones) from the page.
"""

import re
from collections.abc import Callable

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.content_store import store_fulltext
from spyglass_service.documents import fetch_fulltext, fetch_page_title
from spyglass_service.models import Card, Item

# arXiv abs pages prefix their <title> with the paper id, e.g. "[2602.05638] ...".
_ID_PREFIX = re.compile(r"^\[[^\]]+\]\s*")
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Casefolded, whitespace-collapsed form for tolerant prefix comparison."""
    return _WS.sub(" ", text).strip().casefold()


def _is_truncated(title: str) -> bool:
    """True for titles the source clipped (trailing ellipsis)."""
    return title.rstrip().endswith(("…", "..."))


def repair_title(saved: str, candidate: str | None) -> str | None:
    """The full title when candidate plausibly completes the truncated saved one.

    The clipped prefix (minus the ellipsis) must reappear at the start of the
    candidate -- anything else (error pages, unrelated titles) is not trusted.
    """
    if not candidate:
        return None
    candidate = _ID_PREFIX.sub("", candidate).strip()
    base = saved.rstrip().rstrip(".…").rstrip()
    if len(candidate) > len(base) and _norm(candidate).startswith(_norm(base)):
        return candidate
    return None


def store_card_markdown(engine: Engine, card_id: int, markdown: str) -> dict | None:
    """Store caller-provided markdown as a card's full text (no fetching).

    Used by Claude sessions that obtained the text themselves -- e.g. a YouTube
    transcript from the yt-transcribe command. Returns {status, text_chars}, or
    None for unknown cards.
    """
    with Session(engine) as session:
        card = session.get(Card, card_id)
        item = session.get(Item, card.item_id) if card else None
    if item is None:
        return None
    store_fulltext(
        engine,
        item_id=item.id,
        markdown=markdown,
        source_url=item.url,
        content_type="text/markdown",
        status="ok" if markdown.strip() else "empty",
        error=None,
    )
    return {"status": "ok" if markdown.strip() else "empty", "text_chars": len(markdown)}


def fetch_card_fulltext(
    engine: Engine,
    card_id: int,
    fetcher: Callable[[str], dict] | None = None,
    title_fetcher: Callable[[str], str | None] | None = None,
) -> dict | None:
    """Fetch and store the full text behind a card's link.

    Returns {status, text_chars, content_type, title}, or None if the card/item
    is unknown. When the saved title was clipped by the source, the page's own
    title (from the ORIGINAL url, e.g. the arXiv abs page) repairs it. fetcher /
    title_fetcher are injectable so callers and tests skip the network path.
    """
    fetch = fetcher or fetch_fulltext
    with Session(engine) as session:
        card = session.get(Card, card_id)
        item = session.get(Item, card.item_id) if card else None
    if item is None:
        return None
    result = fetch(item.url)
    store_fulltext(
        engine,
        item_id=item.id,
        markdown=result["markdown"],
        source_url=result.get("source_url"),
        content_type=result.get("content_type"),
        status=result["status"],
        error=result.get("error"),
        # Structured, card-visible failure record -- see
        # enrich.py's matching pass-through; .get() so a fetcher stub without the structured keys
        # (as in some tests) still stores cleanly, defaulting all four to None.
        detected_type=result.get("detected_type"),
        tier_reached=result.get("tier_reached"),
        http_status=result.get("http_status"),
        error_class=result.get("error_class"),
    )

    title = item.title
    if _is_truncated(item.title):
        candidate = (title_fetcher or fetch_page_title)(item.url)
        repaired = repair_title(item.title, candidate)
        if repaired:
            title = repaired
            with Session(engine) as session:
                stored = session.get(Item, item.id)
                stored.title = repaired
                session.add(stored)
                session.commit()

    return {
        "status": result["status"],
        "text_chars": len(result["markdown"]),
        "content_type": result.get("content_type"),
        "title": title,
    }
