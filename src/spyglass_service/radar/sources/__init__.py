"""Radar collectors: news search, Hacker News, community papers, Gmail, Slack, the watch sweep and FDA.

`collect_all` runs them one after another. Each is isolated: a failure is logged as a RunLog row
and never stops the others. The watch sweep (one news search per watched organisation) and the
FDA device decisions for the watched companies run once a day, not every cycle, unless the reader
explicitly asks for them. The news search runs in every cycle. Gmail and Slack are read under the
lock the capture poll also takes.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session

from spyglass_service.cards import materialize_cards
from spyglass_service.config import Settings
from spyglass_service.ingest import store_items
from spyglass_service.radar.models import RadarDoc, dumps, loads, utcnow
from spyglass_service.radar.sources._common import NotConfigured, capture_sources_lock, log_run

logger = logging.getLogger(__name__)

# Keys of the returned counts, in run order.
COLLECTORS = ("news", "hn", "hf_papers", "gmail", "slack", "watch", "fda")
# Collector key -> the RunLog source name its runs are recorded under.
RUN_SOURCES = {key: f"radar:{key}" for key in COLLECTORS}
# RadarDoc holding {"last_ok_at": iso} of the last successful watch sweep.
WATCH_DOC = "watch_sweep"
# The daily collectors, each with the RadarDoc that remembers its last successful run.
DAILY_DOCS = {"watch": WATCH_DOC, "fda": "fda_sweep"}
# The sweep is daily; a little under a day so a cycle drifting earlier still runs it.
WATCH_EVERY = timedelta(hours=20)
# Collectors that read the capture inbox and must not overlap the capture poll.
_CAPTURE_KEYS = ("gmail", "slack")
# Seconds a cycle's Gmail or Slack collector waits for a running capture poll.
CAPTURE_LOCK_WAIT = 300


def _news(engine: Engine, settings: Settings) -> tuple[int, str]:
    """Run the topic news search."""
    from spyglass_service.radar.sources.news_search import collect_news

    new = collect_news(engine, settings)
    return new, f"{new} new"


def _hn(engine: Engine, settings: Settings) -> tuple[int, str]:
    """Run the Hacker News collector."""
    from spyglass_service.radar.sources.hackernews import collect_hackernews

    new = collect_hackernews(engine, settings)
    return new, f"{new} new"


def _hf(engine: Engine, settings: Settings) -> tuple[int, str]:
    """Run the community papers collector."""
    from spyglass_service.radar.sources.hf_papers import collect_hf_papers

    new = collect_hf_papers(engine, settings)
    return new, f"{new} new"


def _gmail(engine: Engine, settings: Settings) -> tuple[int, str]:
    """Read newsletters and mailed-in links from Gmail."""
    from spyglass_service.radar.sources.gmail import collect_gmail

    result = collect_gmail(engine, settings)
    detail = f"{result['newsletter']} new newsletters, {result['capture']} links captured"
    return result["newsletter"] + result["capture"], detail


def _slack(engine: Engine, settings: Settings) -> tuple[int, str]:
    """Read links posted in the Slack capture channel."""
    from spyglass_service.radar.sources.slack import collect_slack

    captured = collect_slack(engine, settings)
    return captured, f"{captured} links and files captured"


def _watch(engine: Engine, settings: Settings) -> tuple[int, str]:
    """Run the watch-list sweep (provided by the watch package) and store its items."""
    try:
        from spyglass_service.radar.watch.sweep import watch_collect
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("spyglass_service.radar.watch"):
            raise NotConfigured("watch sweep is not available") from exc
        raise
    items = watch_collect(engine, settings)
    new = store_items(engine, items)
    return new, f"{new} new of {len(items)} found"


def _fda(engine: Engine, settings: Settings) -> tuple[int, str]:
    """Look up FDA device decisions for the watched companies and store them."""
    from spyglass_service.radar.sources.fda import collect_fda

    return collect_fda(engine, settings)


_RUNNERS: dict[str, Callable[[Engine, Settings], tuple[int, str]]] = {
    "news": _news, "hn": _hn, "hf_papers": _hf, "gmail": _gmail, "slack": _slack,
    "watch": _watch, "fda": _fda,
}


def last_watch_sweep(engine: Engine, key: str = "watch") -> datetime | None:
    """When the last successful run of a daily collector started (aware UTC), or None."""
    with Session(engine) as session:
        row = session.get(RadarDoc, DAILY_DOCS[key])
    text = (loads(row.body, {}) or {}).get("last_ok_at") if row else None
    try:
        when = datetime.fromisoformat(text) if text else None
    except (TypeError, ValueError):
        return None
    return when.replace(tzinfo=UTC) if when and when.tzinfo is None else when


def _record_watch_sweep(engine: Engine, started: datetime, key: str = "watch") -> None:
    """Remember a successful daily run's start time."""
    with Session(engine) as session:
        row = session.get(RadarDoc, DAILY_DOCS[key]) or RadarDoc(key=DAILY_DOCS[key], body="{}")
        row.body, row.updated_at = dumps({"last_ok_at": started.isoformat()}), utcnow()
        session.add(row)
        session.commit()


def _watch_skip_reason(engine: Engine, now: datetime, key: str = "watch") -> str | None:
    """Why a daily collector is not due now (it ran less than WATCH_EVERY ago), or None when due."""
    last = last_watch_sweep(engine, key)
    if last is None or now - last >= WATCH_EVERY:
        return None
    hours = (now - last).total_seconds() / 3600
    return f"ran {hours:.1f} hours ago; this runs once a day"


def _run_one(key: str, runner: Callable, engine: Engine, settings: Settings) -> tuple[int, str]:
    """Run one collector; Gmail and Slack wait for (and then hold) the capture lock."""
    if key not in _CAPTURE_KEYS:
        return runner(engine, settings)
    if not capture_sources_lock.acquire(timeout=CAPTURE_LOCK_WAIT):
        raise TimeoutError("the capture poll held the inbox for too long; retried next cycle")
    try:
        return runner(engine, settings)
    finally:
        capture_sources_lock.release()


def collect_all(
    engine: Engine,
    settings: Settings,
    *,
    runners: dict[str, Callable[[Engine, Settings], tuple[int, str]]] | None = None,
    force_watch: bool = False,
) -> dict[str, int]:
    """Run every radar collector and return the new-item count per collector.

    Each run is logged as a RunLog row: "ok", "error" (with the message) or "skipped" (the
    collector is not configured, or the watch sweep already ran today). A collector that fails
    or is skipped counts 0.

    Args:
        engine: Database engine.
        settings: Runtime settings.
        runners: Replacement collectors keyed like COLLECTORS (tests).
        force_watch: Run the watch sweep even when it ran less than a day ago (the reader
            asked for it explicitly).
    """
    table = {**_RUNNERS, **(runners or {})}
    counts: dict[str, int] = {}
    for key in COLLECTORS:
        started = datetime.now(UTC)
        skip = None if key not in DAILY_DOCS or force_watch else _watch_skip_reason(engine, started, key)
        if skip:
            counts[key] = 0
            log_run(engine, RUN_SOURCES[key], "skipped", skip, started)
            continue
        try:
            counts[key], detail = _run_one(key, table[key], engine, settings)
            log_run(engine, RUN_SOURCES[key], "ok", detail, started)
            if key in DAILY_DOCS:
                _record_watch_sweep(engine, started, key)
        except NotConfigured as exc:
            counts[key] = 0
            log_run(engine, RUN_SOURCES[key], "skipped", f"not configured: {exc}", started)
        except Exception as exc:  # noqa: BLE001 -- one collector must never stop the others
            logger.exception("collector %s failed", key)
            counts[key] = 0
            log_run(engine, RUN_SOURCES[key], "error", f"{type(exc).__name__}: {exc}", started)
    # Every stored item gets a card so the older screens and the embedding step see it.
    materialize_cards(engine)
    return counts
