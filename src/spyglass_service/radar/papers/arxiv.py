"""arXiv access for paper search: build queries from a topic, call the API, parse the feed.

A topic becomes a ladder of queries, precise first. The precise one ANDs the few most specific
words; if it finds too little, the next rungs keep the two most specific words and OR the rest,
then OR the specific words alone. arXiv asks clients to leave three seconds between requests
and answers "429 Too Many Requests" when they do not, so a request is retried once after a pause.
"""

import logging
import re
import time
from collections.abc import Callable
from urllib.parse import urlencode

import feedparser
import httpx

from spyglass_service.radar import netguard

logger = logging.getLogger(__name__)

FetchFn = Callable[[str], str]

API_URL = "https://export.arxiv.org/api/query"
# One request returns this many relevance-ranked papers; the model narrows them down later.
MAX_RESULTS = 40
# Query terms beyond this many only make an all-terms (AND) search return nothing.
MAX_TERMS = 4
# A rung that finds fewer papers than this is followed by a looser rung.
ENOUGH_RESULTS = 3
# arXiv's rule for API clients: at least this many seconds between two requests.
REQUEST_GAP_SECONDS = 3.0
# Words that carry no topic information in a search over titles and abstracts.
_STOPWORDS = frozenset(
    "a an and are as at be by for from how in into is it of on or that the their to using use used "
    "via what when where which with without about can do does papers paper research study".split()
)
# Words that fit almost any machine-learning paper: kept only when the topic has few other words.
_GENERIC = frozenset(
    "model models learning deep approach approaches method methods based novel new framework "
    "network networks neural analysis system systems towards toward review survey evaluation "
    "application applications data dataset large".split()
)
_ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf)/([a-z\-]+/\d{7}|\d{4}\.\d{4,5})", re.IGNORECASE)


def arxiv_id_from(text: str | None) -> str | None:
    """The arXiv identifier (without version) found in an arxiv.org link, or None."""
    match = _ARXIV_ID.search(text or "")
    return re.sub(r"v\d+$", "", match.group(1)) if match else None


def _terms(topic: str) -> tuple[list[str], list[str]]:
    """(quoted phrases, single words) of a topic, words ordered most specific first, de-duplicated."""
    phrases = [p.strip() for p in re.findall(r'"([^"]+)"', topic) if p.strip()]
    rest = re.sub(r'"[^"]*"', " ", topic)
    words = list(dict.fromkeys(
        w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", rest) if w.lower() not in _STOPWORDS))
    # Specific words first (generic ones last), longer before shorter within each group.
    ranked = sorted(words, key=lambda w: (w.lower() in _GENERIC, -len(w)))
    return phrases, ranked


def build_query(topic: str) -> str:
    """The precise arXiv `search_query` for a topic: quoted phrases kept whole, other words ANDed.

    At most `MAX_TERMS` terms are used, the most specific words first, in their original order.
    Returns an empty string when the topic has no usable word.
    """
    phrases, ranked = _terms(topic)
    kept = set(ranked[: max(0, MAX_TERMS - len(phrases))])
    original = [w for w in dict.fromkeys(re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", re.sub(r'"[^"]*"', " ", topic)))
                if w in kept]
    return " AND ".join([f'all:"{p}"' for p in phrases] + [f"all:{w}" for w in original])


def query_ladder(topic: str) -> list[str]:
    """Queries for a topic from precise to loose; looser rungs only differ when the topic has enough words."""
    precise = build_query(topic)
    if not precise:
        return []
    phrases, ranked = _terms(topic)
    anchors = [f'all:"{p}"' for p in phrases] + [f"all:{w}" for w in ranked]
    rungs = [precise]
    if len(anchors) > 2:
        core, rest = anchors[:2], anchors[2:MAX_TERMS + 2]
        rungs.append(f"{' AND '.join(core)} AND ({' OR '.join(rest)})")
    if len(anchors) > 1:
        rungs.append(" OR ".join(anchors[:MAX_TERMS]))
    return list(dict.fromkeys(rungs))


def _http_fetch(url: str) -> str:
    """GET a URL and return its text; retries once after a pause on 429, 5xx or a timeout.

    Raises httpx.HTTPError when the second attempt fails as well.
    """
    for attempt in (1, 2):
        try:
            # The guarded client allows public addresses only and sends the generic agent.
            with netguard.page_client(timeout=30.0) as client:
                response = client.get(url)
            if response.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                time.sleep(REQUEST_GAP_SECONDS * 2)
                continue
            response.raise_for_status()
            return response.text
        except httpx.TimeoutException:
            if attempt == 2:
                raise
            time.sleep(REQUEST_GAP_SECONDS)
    raise httpx.HTTPError("arXiv did not answer")  # unreachable; keeps the type checker content


def parse_feed(text: str) -> list[dict]:
    """Papers from an arXiv Atom feed: title, authors, published (YYYY-MM-DD), urls, abstract."""
    papers = []
    for entry in feedparser.parse(text).entries:
        link = entry.get("id") or entry.get("link") or ""
        arxiv_id = arxiv_id_from(link)
        title = " ".join((entry.get("title") or "").split())
        if not arxiv_id or not title:
            continue
        pdf = next((lk.get("href") for lk in entry.get("links", []) if lk.get("title") == "pdf"), None)
        papers.append(
            {
                "title": title,
                "authors": [a.get("name", "") for a in entry.get("authors", []) if a.get("name")],
                "published": (entry.get("published") or "")[:10] or None,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": pdf or f"https://arxiv.org/pdf/{arxiv_id}",
                "abstract": " ".join((entry.get("summary") or "").split()),
                "arxiv_id": arxiv_id,
            }
        )
    return papers


def _request_url(query: str) -> str:
    """The API address of a relevance-sorted search."""
    return f"{API_URL}?" + urlencode({"search_query": query, "sortBy": "relevance", "max_results": MAX_RESULTS})


def search_arxiv(topic: str, fetch: FetchFn | None = None) -> list[dict]:
    """Search arXiv for a topic, loosening the query until enough papers come back (best matches first).

    Raises on network failure of the first request; a later rung that fails only ends the search
    with what was found so far.
    """
    pause = time.sleep if fetch is None else (lambda _seconds: None)
    found: dict[str, dict] = {}
    for number, query in enumerate(query_ladder(topic)):
        if number:
            pause(REQUEST_GAP_SECONDS)
        try:
            papers = parse_feed((fetch or _http_fetch)(_request_url(query)))
        except Exception:
            if not found and number == 0:
                raise
            logger.exception("arXiv rung %d failed for %r; keeping the earlier results", number, topic)
            break
        for paper in papers:
            found.setdefault(paper["arxiv_id"], paper)
        if len(found) >= ENOUGH_RESULTS:
            break
    return list(found.values())


def lookup_arxiv(ids: list[str], fetch: FetchFn | None = None) -> dict[str, dict]:
    """Papers by arXiv id (id -> paper), for filling in authors; {} when the call fails."""
    if not ids:
        return {}
    url = f"{API_URL}?" + urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
    try:
        return {p["arxiv_id"]: p for p in parse_feed((fetch or _http_fetch)(url))}
    except Exception:
        logger.exception("arXiv lookup by id failed for %d papers", len(ids))
        return {}
