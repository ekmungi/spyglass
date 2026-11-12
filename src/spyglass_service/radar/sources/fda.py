"""FDA device decisions for the watched companies, from the public openFDA service.

Once a day, for every active company in the watch register, three lookups run against
`api.fda.gov` (no key, no account): 510(k) clearances and De Novo grants, PMA approvals, and
device recalls, each limited to decisions of the last 30 days. The company is looked up by its name
as an exact phrase, and each record is then kept only when its firm name equals one of the
company's names or starts with it as whole words (never a loose "contains"). The reader can also
list product codes and device keywords; those are searched once per run for everything that
matches, whoever made it. Each decision becomes one watch item (see `fda_records`).

The service is used politely and safely:

- every request goes through `netguard.page_client` (public addresses only, reads only, no
  cookies, no redirects) and is refused unless it is https to `api.fda.gov`;
- at most one request per second, and at most `MAX_REQUESTS` a run; a run that runs out of requests
  remembers where it stopped and starts there next time, so a long watch list is covered over days;
- one failed lookup is counted and the rest go on; a rate-limit answer (429) ends the run with what
  was found; only a run in which nothing could be read at all raises.
"""

import json
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.collectors.base import CollectedItem
from spyglass_service.ingest import store_items
from spyglass_service.radar import netguard
from spyglass_service.radar.models import RadarDoc, WatchEntity, dumps, loads, utcnow
from spyglass_service.radar.sources import fda_records
from spyglass_service.radar.sources._common import NotConfigured
from spyglass_service.radar.watch.registry import entity_names

logger = logging.getLogger(__name__)

HOST = "api.fda.gov"
BASE = f"https://{HOST}/device/"
# How far back decisions are read each run; records already stored are skipped by their number.
WINDOW_DAYS = 30
# Records asked for per request (openFDA allows up to 1000).
PAGE_SIZE = 100
# Seconds between two requests: well inside openFDA's limit of 240 a minute and 1,000 a day.
PAUSE = 1.0
# The most requests one run may make, whatever the watch list holds.
MAX_REQUESTS = 120
TIMEOUT = 25.0
# RadarDoc remembering which company the next run starts with.
CURSOR_DOC = "fda_cursor"
# A product code is three letters or digits; a keyword is plain words (no quotes, no operators).
CODE_PATTERN = re.compile(r"^[A-Za-z0-9]{3}$")
KEYWORD_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .'&/-]{1,59}$")
_MAX_LIST = 5  # codes or keywords per list: each list is one request per endpoint

# (file, firm field, date field, keyword field(s), builder). Recalls are built per event.
_ENDPOINTS = (
    ("510k.json", "applicant", "decision_date", ("device_name",)),
    ("pma.json", "applicant", "decision_date", ("trade_name", "generic_name")),
    ("recall.json", "recalling_firm", "event_date_posted", ("product_description",)),
)

# (url, params) -> (HTTP status, body)
FetchFn = Callable[[str, dict], tuple[int, bytes]]


@dataclass(frozen=True)
class Target:
    """A company to look up: its watch-entity id (None for the owner's own lists) and its names."""

    entity_id: int | None
    names: tuple[str, ...]


@dataclass
class FdaResult:
    """What a run found and how it went."""

    items: list[CollectedItem] = field(default_factory=list)
    requests: int = 0
    failures: int = 0
    covered: int = 0
    stopped: str | None = None
    last_error: str = ""


class _RateLimited(Exception):
    """openFDA answered 429: stop asking for now."""


def default_fetch(url: str, params: dict) -> tuple[int, bytes]:
    """GET one openFDA page through the guarded page client; only https to api.fda.gov is allowed."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") != HOST:
        raise ValueError(f"only https requests to {HOST} are made")
    with netguard.page_client(timeout=TIMEOUT, follow_redirects=False) as client:
        response = client.get(url, params=params)
    return response.status_code, response.content


def parse_list(text: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    """The valid entries of a comma- or semicolon-separated setting, upper-cased for codes."""
    found: list[str] = []
    for part in re.split(r"[,;]", text or ""):
        entry = " ".join(part.split())
        if pattern.match(entry):
            entry = entry.upper() if pattern is CODE_PATTERN else entry
            if entry not in found:
                found.append(entry)
    return tuple(found[:_MAX_LIST])


def _phrase(value: str) -> str:
    """`value` as a quoted search phrase (quotes, backslashes and control characters removed)."""
    cleaned = " ".join(re.sub(r'["\\\x00-\x1f]', " ", value).split())
    return f'"{cleaned}"' if cleaned else ""


class _Run:
    """The requests of one run: pacing, the cap and the counts."""

    def __init__(self, fetch: FetchFn, sleep: Callable[[float], None], pause: float,
                 limit: int) -> None:
        """`limit` is the most requests this run may make."""
        self.fetch, self.sleep, self.pause, self.limit = fetch, sleep, pause, limit
        self.result = FdaResult()

    def affords(self, count: int) -> bool:
        """True when `count` more requests fit under the cap."""
        return self.result.requests + count <= self.limit

    def query(self, endpoint: str, search: str, sort: str) -> list[dict] | None:
        """The records of one lookup; None when it failed. Raises `_RateLimited` on HTTP 429."""
        if self.result.requests:
            self.sleep(self.pause)
        self.result.requests += 1
        params = {"search": search, "sort": sort, "limit": PAGE_SIZE}
        try:
            status, body = self.fetch(BASE + endpoint, params)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            return self._failed(f"{type(exc).__name__}: {exc}")
        if status == 429:
            self._failed("HTTP 429 (rate limit)")
            raise _RateLimited
        if status == 404 and b"NOT_FOUND" in body:
            return []  # openFDA's way of saying "no matches"
        if status != 200:
            return self._failed(f"HTTP {status}")
        try:
            results = json.loads(body).get("results", [])
        except (ValueError, AttributeError):
            return self._failed("an answer that was not JSON")
        return [r for r in results if isinstance(r, dict)]

    def _failed(self, reason: str) -> None:
        """Count a failed lookup and remember why."""
        self.result.failures += 1
        self.result.last_error = reason
        logger.warning("openFDA lookup failed: %s", reason)


def _items_for(file: str, records: list[dict], firm_field: str,
               names: Iterable[str] | None) -> list[CollectedItem]:
    """The items of one lookup's records, kept only for the given firm names (all when None)."""
    kept = [r for r in records if names is None or fda_records.name_matches(names, r.get(firm_field))]
    if file == "recall.json":
        return fda_records.items_recall(kept)
    build = fda_records.item_510k if file == "510k.json" else fda_records.item_pma
    return [item for item in map(build, kept) if item is not None]


def _merge(merged: dict[str, CollectedItem], items: Iterable[CollectedItem],
           entity_id: int | None) -> None:
    """Add items to `merged` by record number, gathering the watch tags of every entity."""
    for item in items:
        tags = [*item.source_tags, *([f"watch:{entity_id}"] if entity_id is not None else [])]
        previous = merged.get(item.external_id)
        if previous is not None:
            tags = [*previous.source_tags, *tags]
        merged[item.external_id] = CollectedItem(
            source=item.source, external_id=item.external_id, title=item.title, url=item.url,
            summary=item.summary, source_tags=list(dict.fromkeys(tags)),
            published_at=item.published_at, origin=item.origin)


def _extras_search(file: str, firm_field: str, keyword_fields: tuple[str, ...],
                   codes: tuple[str, ...], keywords: tuple[str, ...]) -> list[tuple[str, str]]:
    """(label, search terms) for the owner's lists on one endpoint (none when the list is empty)."""
    searches = []
    if codes and file != "recall.json":  # recall product codes carry a "--" suffix: not matched
        searches.append(("codes", " OR ".join(f"product_code:{_phrase(c)}" for c in codes)))
    if keywords:
        searches.append(("keywords", " OR ".join(f"{f}:{_phrase(k)}"
                                                 for k in keywords for f in keyword_fields)))
    return searches


def search(targets: list[Target], *, codes: tuple[str, ...] = (), keywords: tuple[str, ...] = (),
           fetch: FetchFn | None = None, sleep: Callable[[float], None] = time.sleep,
           today: date | None = None, max_requests: int = MAX_REQUESTS,
           pause: float = PAUSE) -> FdaResult:
    """Look up decisions of the last 30 days for the targets, the codes and the keywords.

    Returns the items found (one per record number, with the watch tag of every company that
    matched) and how the run went. Raises RuntimeError when no lookup at all could be read.
    """
    run = _Run(fetch or default_fetch, sleep, pause, max_requests)
    until = today or datetime.now(UTC).date()
    window = f"[{until - timedelta(days=WINDOW_DAYS)} TO {until}]"
    merged: dict[str, CollectedItem] = {}
    try:
        for file, firm_field, date_field, keyword_fields in _ENDPOINTS:
            for _label, terms in _extras_search(file, firm_field, keyword_fields, codes, keywords):
                if not run.affords(1):
                    run.result.stopped = "request limit"
                    break
                records = run.query(file, f"({terms}) AND {date_field}:{window}", f"{date_field}:desc")
                _merge(merged, _items_for(file, records or [], firm_field, None), None)
        for target in targets:
            phrase = _phrase(target.names[0]) if target.names else ""
            if not phrase:
                run.result.covered += 1
                continue
            if not run.affords(len(_ENDPOINTS)):
                run.result.stopped = run.result.stopped or "request limit"
                break
            for file, firm_field, date_field, _keywords in _ENDPOINTS:
                records = run.query(file, f"{firm_field}:{phrase} AND {date_field}:{window}",
                                    f"{date_field}:desc")
                _merge(merged, _items_for(file, records or [], firm_field, target.names),
                       target.entity_id)
            run.result.covered += 1
    except _RateLimited:
        run.result.stopped = "rate limit"
    result = run.result
    result.items = list(merged.values())
    if result.requests and result.failures == result.requests:
        raise RuntimeError(f"openFDA could not be read ({result.last_error})")
    return result


def _load_targets(engine: Engine) -> list[Target]:
    """The active companies of the watch register, in id order, with their names and aliases."""
    with Session(engine) as session:
        rows = session.exec(select(WatchEntity).where(
            WatchEntity.status == "active", WatchEntity.kind == "company")
            .order_by(WatchEntity.id)).all()
        return [Target(e.id, tuple(entity_names(e))) for e in rows]


def _cursor(engine: Engine) -> int:
    """The index of the company the next run starts with (0 when never run)."""
    with Session(engine) as session:
        row = session.get(RadarDoc, CURSOR_DOC)
    value = (loads(row.body, {}) or {}).get("next") if row else 0
    return value if isinstance(value, int) and value >= 0 else 0


def _save_cursor(engine: Engine, position: int) -> None:
    """Remember where the next run starts."""
    with Session(engine) as session:
        row = session.get(RadarDoc, CURSOR_DOC) or RadarDoc(key=CURSOR_DOC, body="{}")
        row.body, row.updated_at = dumps({"next": position}), utcnow()
        session.add(row)
        session.commit()


def _detail(new: int, result: FdaResult) -> str:
    """The status sentence of a run, starting 'N new' like the other collectors."""
    kinds = {"510k": 0, "denovo": 0, "pma": 0, "recall": 0}
    for item in result.items:
        kinds[item.external_id.split(":")[1]] += 1
    text = (f"{new} new of {len(result.items)} found ({kinds['510k']} 510(k), {kinds['denovo']} "
            f"De Novo, {kinds['pma']} PMA, {kinds['recall']} recalls); {result.requests} requests")
    if result.failures:
        text += f"; {result.failures} failed ({result.last_error})"
    if result.stopped:
        text += f"; stopped at the {result.stopped}, continuing next run"
    return text


def collect_fda(engine: Engine, settings, *, fetch: FetchFn | None = None,
                sleep: Callable[[float], None] = time.sleep, today: date | None = None,
                max_requests: int = MAX_REQUESTS) -> tuple[int, str]:
    """Look up and store the FDA decisions for the watch list; returns (new items, status text).

    Raises NotConfigured when the source is switched off, and RuntimeError when openFDA could not
    be read at all (the collector runner records either; neither stops the cycle).
    """
    if not getattr(settings, "radar_fda_enabled", True):
        raise NotConfigured("FDA device decisions are switched off")
    codes = parse_list(getattr(settings, "radar_fda_product_codes", ""), CODE_PATTERN)
    keywords = parse_list(getattr(settings, "radar_fda_keywords", ""), KEYWORD_PATTERN)
    targets = _load_targets(engine)
    if not (targets or codes or keywords):
        return 0, "0 new (no companies on the watch list)"
    start = _cursor(engine) % len(targets) if targets else 0
    order = targets[start:] + targets[:start]
    result = search(order, codes=codes, keywords=keywords, fetch=fetch, sleep=sleep, today=today,
                    max_requests=max_requests)
    if targets:
        _save_cursor(engine, (start + result.covered) % len(targets))
    new = store_items(engine, result.items)
    return new, _detail(new, result)
