"""Community-ranked papers from the Hugging Face daily papers list.

The list is a human-voted shortlist of fresh arXiv papers, which is the "targeted papers with a
community signal" source. Votes are also copied onto the same paper when another source (an
arXiv feed, a bookmark) has already stored it under a different collector.
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.config import Settings
from spyglass_service.ingest import store_items
from spyglass_service.models import Item
from spyglass_service.radar.sources._common import (
    http_get_bytes,
    item_ids_by_external,
    merge_extras,
)

logger = logging.getLogger(__name__)

SOURCE = "hf_papers"
API_URL = "https://huggingface.co/api/daily_papers"
ORIGIN = "Hugging Face Daily Papers"
LIMIT = 50

# (url, params) -> response bytes
FetchFn = Callable[[str, dict], bytes]


def _parse_time(raw: str | None) -> datetime | None:
    """Parse an ISO timestamp such as 2026-11-04T19:00:00.000Z; None when absent or invalid."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_papers(payload: list) -> list[dict]:
    """Plain paper dicts from the daily_papers JSON: arxiv_id, title, summary, authors,
    upvotes, published. Entries without an id or title are skipped."""
    papers = []
    for entry in payload if isinstance(payload, list) else []:
        paper = entry.get("paper") or {}
        arxiv_id = str(paper.get("id") or "").strip()
        title = (paper.get("title") or entry.get("title") or "").strip()
        if not arxiv_id or not title:
            continue
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": " ".join(title.split()),
                "summary": " ".join((paper.get("summary") or entry.get("summary") or "").split()),
                "authors": [a.get("name") for a in paper.get("authors", []) if a.get("name")],
                "upvotes": int(paper.get("upvotes") or 0),
                "published": _parse_time(paper.get("publishedAt") or entry.get("publishedAt")),
            }
        )
    return papers


def fetch_papers(*, fetch: FetchFn | None = None, limit: int = LIMIT) -> list[dict]:
    """Fetch and parse the current daily papers list."""
    raw = (fetch or (lambda url, params: http_get_bytes(url, params)))(API_URL, {"limit": limit})
    return parse_papers(json.loads(raw))


def to_items(papers: list[dict]) -> list[CollectedItem]:
    """Normalise papers into collected items pointing at the arXiv abstract page."""
    return [
        CollectedItem(
            source=SOURCE,
            external_id=p["arxiv_id"],
            title=p["title"],
            url=f"https://arxiv.org/abs/{p['arxiv_id']}",
            summary=p["summary"] or None,
            published_at=p["published"],
            origin=ORIGIN,
        )
        for p in papers
    ]


def copy_votes_to_existing(engine: Engine, papers: list[dict]) -> int:
    """Copy upvotes onto items from other sources whose URL carries the same arXiv id."""
    updates: dict[int, dict] = {}
    with Session(engine) as session:
        for paper in papers:
            pattern = re.compile(rf"arxiv\.org/\w+/{re.escape(paper['arxiv_id'])}(?!\d)")
            rows = session.exec(
                select(Item.id, Item.url)
                .where(Item.source != SOURCE)
                .where(Item.url.like(f"%{paper['arxiv_id']}%"))  # type: ignore[attr-defined]
            ).all()
            for item_id, url in rows:
                if pattern.search(url):
                    updates[item_id] = {
                        "upvotes": paper["upvotes"], "arxiv_id": paper["arxiv_id"]
                    }
    return merge_extras(engine, updates)


def collect_hf_papers(
    engine: Engine, settings: Settings, *, fetch: FetchFn | None = None
) -> int:
    """Store the day's community papers with their upvotes; returns the new item count."""
    papers = fetch_papers(fetch=fetch)
    new = store_items(engine, to_items(papers))
    ids = item_ids_by_external(engine, SOURCE, [p["arxiv_id"] for p in papers])
    merge_extras(
        engine,
        {
            ids[p["arxiv_id"]]: {
                "upvotes": p["upvotes"], "arxiv_id": p["arxiv_id"], "authors": p["authors"]
            }
            for p in papers
            if p["arxiv_id"] in ids
        },
    )
    copy_votes_to_existing(engine, papers)
    return new
