"""Find the few papers that matter for a topic, with one line on how each relates to the reader.

Sources: an arXiv search (loosened step by step when it finds too little), plus papers already
collected locally: real papers only (arXiv or a journal/DOI address) that are close to the topic
by embedding. Community upvotes come from locally stored facts. One model call picks the best
papers for this reader and writes the "why"; without a model the newest papers are returned and
the answer says so. Nothing is ever added to fill the list: if nothing qualifies the list is
empty. A complete answer is cached for 12 hours per topic, a degraded or empty one for 5 minutes.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.embeddings import EmbeddingIndex
from spyglass_service.models import Item
from spyglass_service.radar.brief.llm import LlmFn, json_schema, make_llm
from spyglass_service.radar.models import Assessment, ItemExtra, RadarDoc, dumps, loads
from spyglass_service.radar.papers.arxiv import FetchFn, arxiv_id_from, lookup_arxiv, search_arxiv
from spyglass_service.radar.profile_defaults import load_profile
from spyglass_service.radar.serialize import signal_text

logger = logging.getLogger(__name__)

CACHE_TTL = timedelta(hours=12)
# A degraded or empty answer is kept this long, so a flaky service is not asked again at once
# but is also not remembered as the answer for half a day.
SHORT_CACHE_TTL = timedelta(minutes=5)
# Papers older than this are "not recent": the model prefers newer ones unless a paper is foundational.
RECENT_WINDOW = timedelta(days=730)
# Local papers must be at least this similar to the topic (cosine of the embeddings). Measured on
# the reader's own library: related papers score about 0.6 and above, and news about the same
# field scores 0.3 to 0.5, so the floor sits between the two.
LOCAL_MIN_SIMILARITY = 0.55
# A stored address on one of these hosts (or with a DOI in it) is a journal or preprint page.
PAPER_HOSTS = (
    "arxiv.org", "doi.org", "biorxiv.org", "medrxiv.org", "nature.com", "science.org", "sciencedirect.com",
    "springer.com", "ieee.org", "acm.org", "wiley.com", "thelancet.com", "nejm.org", "bmj.com",
    "jamanetwork.com", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "plos.org", "frontiersin.org",
    "mdpi.com", "openreview.net", "aclanthology.org", "mlr.press", "neurips.cc", "thecvf.com",
    "semanticscholar.org", "tandfonline.com", "sagepub.com", "cell.com", "pnas.org", "oup.com",
)
_DOI = re.compile(r"10\.\d{4,9}/\S+")

NOTICE_ARXIV_DOWN = "The paper search service did not answer; showing matches from your own library only."
NOTICE_NO_MODEL = "The ranking model was unavailable; results are ordered by date and have no relevance notes."
NOTICE_EMPTY = "No papers matched this topic."
NOTICE_EMPTY_ARXIV_DOWN = ("The paper search service did not answer, and your own library has no paper "
                           "close to this topic.")
LOCAL_MAX = 12
# At most this many candidates are shown to the model.
POOL_MAX = 30
ABSTRACT_CHARS = 350

PICK_SCHEMA = json_schema(
    "paper_picks",
    {"picks": {"type": "array", "items": {
        "type": "object",
        "properties": {"index": {"type": "integer"}, "why": {"type": "string"}},
        "required": ["index", "why"], "additionalProperties": False}}},
    ["picks"],
)


def normalise_topic(topic: str) -> str:
    """Lower-case, single-spaced topic text used as the cache key."""
    return " ".join(re.sub(r"[^\w\s]", " ", topic.lower()).split())


def _naive(now: datetime | None) -> datetime:
    """The current time as naive UTC."""
    moment = now or datetime.now(UTC)
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def _norm_title(title: str) -> str:
    """Title reduced to lower-case letters and digits, for matching the same paper."""
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _arxiv_item_map(session: Session) -> dict[str, int]:
    """arXiv id -> local item id, for every stored item that links to arXiv."""
    rows = session.exec(select(Item.id, Item.url).where(Item.url.contains("arxiv.org"))).all()
    return {aid: item_id for item_id, url in rows if (aid := arxiv_id_from(url))}


def _is_paper_address(url: str, arxiv_id: str | None) -> bool:
    """True when the address is an arXiv id, a DOI or a page on a journal or preprint site."""
    if arxiv_id or _DOI.search(url or ""):
        return True
    host = (urlsplit(url or "").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in PAPER_HOSTS)


def _local_papers(session: Session, index: EmbeddingIndex, topic: str) -> list[dict]:
    """Collected papers (kind "paper" with an arXiv, DOI or journal address) close to the topic.

    Closeness is the cosine similarity of the embeddings and must reach `LOCAL_MIN_SIMILARITY`;
    anything below it is not a candidate however few candidates there are.
    """
    ids = list(session.exec(select(Assessment.item_id).where(Assessment.kind == "paper")).all())
    found, matrix = index.matrix_for(ids)
    if not found:
        return []
    query = np.asarray(index.embed_query(topic), dtype=np.float32)
    norm = float(np.linalg.norm(query)) or 1.0
    sims = (matrix @ query) / norm
    order = [int(i) for i in np.argsort(-sims)[:LOCAL_MAX] if sims[i] >= LOCAL_MIN_SIMILARITY]
    chosen = [found[i] for i in order]
    items = {i.id: i for i in session.exec(select(Item).where(Item.id.in_(chosen))).all()}
    extras = {e.item_id: loads(e.data, {}) or {} for e in session.exec(
        select(ItemExtra).where(ItemExtra.item_id.in_(chosen))).all()}
    out = []
    for item_id in chosen:
        item, extra = items[item_id], extras.get(item_id, {})
        aid = extra.get("arxiv_id") or arxiv_id_from(item.url)
        if not _is_paper_address(item.url, aid):
            continue
        out.append({
            "title": item.title, "authors": list(extra.get("authors") or []),
            "published": item.published_at.date().isoformat() if item.published_at else None,
            "url": item.url, "pdf_url": f"https://arxiv.org/pdf/{aid}" if aid else None,
            "abstract": " ".join((item.summary or "").split()), "arxiv_id": aid, "item_id": item_id,
            "upvotes": int(extra.get("upvotes") or 0),
        })
    return out


def _merge(arxiv: list[dict], local: list[dict], by_arxiv: dict[str, int], upvotes: dict[int, int]) -> list[dict]:
    """One list of unique papers: nearest local ones first, then arXiv's ranking."""
    merged: dict[str, dict] = {}
    for paper in [*local, *arxiv]:
        key = paper.get("arxiv_id") or _norm_title(paper["title"])
        before = merged.get(key, {})
        entry = {**before, **{k: v for k, v in paper.items() if v}}
        item_id = paper.get("item_id") or by_arxiv.get(paper.get("arxiv_id") or "") or before.get("item_id")
        entry["item_id"] = item_id
        entry["upvotes"] = max(before.get("upvotes", 0), paper.get("upvotes", 0), upvotes.get(item_id, 0))
        merged[key] = entry
    return list(merged.values())


def _recent(paper: dict, now: datetime) -> bool:
    """True when the paper was published within the recent window (unknown dates count as recent)."""
    if not paper.get("published"):
        return True
    return datetime.fromisoformat(paper["published"]) >= now - RECENT_WINDOW


def _fallback_pick(pool: list[dict], limit: int, now: datetime) -> list[dict]:
    """Newest first, recent papers before old ones, with no explanation."""
    ranked = sorted(pool, key=lambda p: (not _recent(p, now), _neg_date(p.get("published"))))
    return [{**p, "why": None} for p in ranked[:limit]]


def _neg_date(published: str | None) -> float:
    """Sort key placing newer dates first; undated papers last."""
    return -datetime.fromisoformat(published).timestamp() if published else float("inf")


def _messages(topic: str, profile: dict, pool: list[dict], limit: int) -> list[dict]:
    """The prompt asking the model to pick `limit` papers and explain each in a sentence."""
    topics = ", ".join(t["name"] for t in profile.get("topics", []))
    lines = []
    for n, p in enumerate(pool):
        year = (p.get("published") or "????")[:4]
        votes = f", {p['upvotes']} community upvotes" if p.get("upvotes") else ""
        lines.append(f"[{n}] {p['title']} ({year}{votes})\n    {p['abstract'][:ABSTRACT_CHARS]}")
    system = (
        f"You pick papers for one reader. About the reader: {profile.get('statement', '')} "
        f"Their topics: {topics}. From the candidates, pick the {limit} that matter most for "
        "this reader's work on the search topic. Prefer papers from the last 24 months unless "
        "a paper is clearly foundational. For each pick write one plain sentence on how it "
        "relates to the reader's field; if the link is weak, say so honestly. Pick fewer than "
        f"{limit} (or none) when the other candidates are not about the search topic. Order the picks "
        'best first. Return JSON: {"picks": [{"index": n, "why": "..."}]}.'
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"Search topic: {topic}\n\nCandidates:\n" + "\n".join(lines)}]


def _llm_pick(llm: LlmFn, topic: str, profile: dict, pool: list[dict], limit: int) -> list[dict] | None:
    """Ask the model for picks; [] when it chose none, None when the call fails or is unusable."""
    try:
        picks = llm(_messages(topic, profile, pool, limit), PICK_SCHEMA).get("picks")
    except Exception:
        logger.exception("Paper ranking call failed; falling back to recency")
        return None
    if not isinstance(picks, list):
        return None
    chosen, seen = [], set()
    for pick in picks:
        n = pick.get("index") if isinstance(pick, dict) else None
        if isinstance(n, int) and 0 <= n < len(pool) and n not in seen:
            seen.add(n)
            chosen.append({**pool[n], "why": str(pick.get("why") or "").strip() or None})
    return chosen[:limit] if chosen or not picks else None


def _public(paper: dict) -> dict:
    """The API shape of one paper."""
    return {
        "title": paper["title"], "authors": paper.get("authors") or [], "published": paper.get("published"),
        "url": paper["url"], "pdf_url": paper.get("pdf_url"), "abstract": paper.get("abstract") or "",
        "why": paper.get("why"), "signal": signal_text({"upvotes": paper.get("upvotes", 0)}),
        "item_id": paper.get("item_id"),
    }


def _fill_authors(papers: list[dict], fetch: FetchFn | None) -> list[dict]:
    """Papers with authors, published date and abstract filled in from arXiv where they are missing."""
    wanted = [p["arxiv_id"] for p in papers if p.get("arxiv_id") and not p.get("authors")]
    if not wanted:
        return papers
    known = lookup_arxiv(wanted, fetch)
    filled = []
    for paper in papers:
        source = known.get(paper.get("arxiv_id") or "")
        if source and not paper.get("authors"):
            paper = {**paper, **{k: source[k] for k in ("authors", "published", "abstract") if not paper.get(k)}}
            paper["authors"] = source["authors"]
        filled.append(paper)
    return filled


def _status(papers: list[dict], arxiv_ok: bool, ranked: bool) -> tuple[str, str | None]:
    """("ok" | "degraded" | "empty", notice) for an answer."""
    if not papers:
        return "empty", NOTICE_EMPTY if arxiv_ok else NOTICE_EMPTY_ARXIV_DOWN
    notices = ([] if arxiv_ok else [NOTICE_ARXIV_DOWN]) + ([] if ranked else [NOTICE_NO_MODEL])
    return ("degraded", " ".join(notices)) if notices else ("ok", None)


def _cached(session: Session, key: str, limit: int, moment: datetime) -> dict | None:
    """The stored answer for `key` when it is still fresh and holds at least `limit` papers."""
    row = session.get(RadarDoc, key)
    if row is None:
        return None
    doc = loads(row.body, {}) or {}
    if "status" not in doc:
        return None  # stored before answers carried a status: it may be a padded or degraded one
    status = doc["status"]
    ttl = CACHE_TTL if status == "ok" else SHORT_CACHE_TTL
    if moment - _naive(row.updated_at) >= ttl or (doc.get("limit", 0) < limit and doc.get("papers")):
        return None
    return {"papers": doc.get("papers", [])[:limit], "status": status, "notice": doc.get("notice")}


def find_papers(
    engine: Engine,
    settings,
    index: EmbeddingIndex | None,
    topic: str,
    limit: int = 8,
    *,
    llm: LlmFn | None = None,
    fetch: FetchFn | None = None,
    now: datetime | None = None,
) -> dict:
    """The best `limit` papers for a topic, each with a one-sentence "why" for this reader.

    Returns `{"papers": [...], "status": "ok" | "degraded" | "empty", "notice": str | None}`.
    llm: `(messages, schema) -> dict`; defaults to the writer model. Without one (or when it
        fails) the newest candidates are returned with no "why" and the status is "degraded".
    fetch: `(url) -> text` for the arXiv calls, injectable for tests. If arXiv cannot be reached,
        only locally collected papers close to the topic are returned, with status "degraded".
    A degraded or empty answer is cached for 5 minutes, a complete one for 12 hours.
    """
    moment = _naive(now)
    key = f"papers:{normalise_topic(topic)}"
    with Session(engine) as session:
        if (hit := _cached(session, key, limit, moment)) is not None:
            return hit
        profile = load_profile(session)
        arxiv_ok = True
        try:
            arxiv = search_arxiv(topic, fetch)
        except Exception:
            logger.exception("arXiv search failed for %r", topic)
            arxiv, arxiv_ok = [], False
        local = _local_papers(session, index, topic) if index is not None else []
        by_arxiv = _arxiv_item_map(session)
        item_ids = [i for i in by_arxiv.values() if i]
        votes = {
            e.item_id: int((loads(e.data, {}) or {}).get("upvotes") or 0)
            for e in session.exec(select(ItemExtra).where(ItemExtra.item_id.in_(item_ids))).all()
        } if item_ids else {}
        pool = _merge(arxiv, local, by_arxiv, votes)[:POOL_MAX]
        writer = llm if llm is not None else make_llm(settings)
        picked = _llm_pick(writer, topic, profile, pool, limit) if writer and pool else None
        chosen = picked if picked is not None else _fallback_pick(pool, limit, moment)
        papers = [_public(p) for p in (_fill_authors(chosen, fetch) if arxiv_ok else chosen)]
        status, notice = _status(papers, arxiv_ok, ranked=picked is not None or not pool)
        row = session.get(RadarDoc, key) or RadarDoc(key=key, body="")
        row.body = dumps({"limit": limit, "papers": papers, "status": status, "notice": notice})
        row.updated_at = moment
        session.add(row)
        session.commit()
    return {"papers": papers, "status": status, "notice": notice}
