"""Measure the radar's relevance judgement, per model.

The labelled set is built from the user's own saved and rejected items.

Positives: items the user saved or gave a thumbs-up, plus bookmarks (pages the user chose to
save). Negatives: items the user rejected or gave a thumbs-down. Firehose: a random sample of a
broad, unfiltered feed; it is unlabelled and presumed mostly noise, so it is reported as "share
kept", never as accuracy.

No leakage: the liked/disliked examples placed in the prompt never include an item being
scored. Positives and negatives are split into two folds; fold B is scored with examples drawn
from fold A and the reverse. The firehose is scored with fold A's examples. Only the triage
stage is measured, because triage is the gate that decides what the reader ever sees.

Run from the repository root (it reads `.env`, so the branch database and key are used):
    uv run python scripts/radar_eval.py --models deepseek/deepseek-v4-flash,openai/gpt-6-luna
"""

import argparse
import json
import logging
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, or_, select

from spyglass_service.config import Settings
from spyglass_service.db import create_db_engine
from spyglass_service.models import Card, Item
from spyglass_service.radar.assess import Judge, triage_rows
from spyglass_service.radar.assess_prompt import triage_row
from spyglass_service.radar.llm_claude import USAGE, claude_chat_json
from spyglass_service.radar.profile import clean_title, profile_prompt_block, section_keys
from spyglass_service.radar.profile_defaults import DEFAULT_PROFILE, load_profile

logger = logging.getLogger("radar_eval")

_URL = "https://openrouter.ai/api/v1/chat/completions"
_RETRY_STATUS = {429, 500, 502, 503, 504}
# Items per parallel unit of work; matches the production triage batch.
_CHUNK = 20


class CallStats:
    """Thread-safe tally of cost, tokens and time spent in model calls."""

    def __init__(self) -> None:
        """Start every counter at zero."""
        self._lock = threading.Lock()
        self.calls = 0
        self.cost = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.seconds = 0.0

    def add(self, usage: dict, seconds: float) -> None:
        """Record one call's usage block and wall time."""
        with self._lock:
            self.calls += 1
            self.cost += float(usage.get("cost") or 0.0)
            self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(usage.get("completion_tokens") or 0)
            self.seconds += seconds


def make_llm(api_key: str, stats: CallStats, client: httpx.Client):
    """An LlmFn with the production request shape that also records usage and latency."""

    def call(messages: list[dict], schema: dict, model: str) -> dict:
        """Post one structured-output request (retrying transient errors); return the object."""
        payload = {"model": model, "messages": messages, "usage": {"include": True},
                   "response_format": {"type": "json_schema", "json_schema": schema}}
        headers = {"Authorization": f"Bearer {api_key}"}
        for attempt in range(3):
            started = time.perf_counter()
            response = client.post(_URL, json=payload, headers=headers)
            elapsed = time.perf_counter() - started
            if response.status_code == 200:
                body = response.json()
                stats.add(body.get("usage") or {}, elapsed)
                return json.loads(body["choices"][0]["message"]["content"])
            if response.status_code not in _RETRY_STATUS:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
            time.sleep(1.0 + attempt)
        raise RuntimeError(f"HTTP {response.status_code} after retries")

    return call


def make_claude_llm(settings: Settings, stats: CallStats):
    """An LlmFn that answers through the installed Claude Code command and records wall time."""

    def call(messages: list[dict], schema: dict, model: str) -> dict:
        """Run one structured-output call through Claude Code."""
        started = time.perf_counter()
        try:
            return claude_chat_json(messages, schema, model=model, settings=settings)
        finally:
            stats.add({}, time.perf_counter() - started)

    return call


def _row(item: Item, when: datetime | None) -> dict:
    """An evaluation record: the triage input plus the time used to order examples.

    The source is masked: "raindrop" would tell the model the reader saved the item.
    """
    return {**triage_row(item.id, item.title, item.origin, "web", item.summary),
            "when": (when or item.fetched_at).isoformat()}


def load_sets(engine, *, firehose_n: int, seed: int) -> dict[str, list[dict]]:
    """Positives, negatives and the firehose sample from the database."""
    with Session(engine) as session:
        pos: dict[int, dict] = {}
        neg: dict[int, dict] = {}
        for card, item in session.exec(select(Card, Item).join(Item, Item.id == Card.item_id)
                                       .where(Card.feedback.in_(("up", "down")))).all():
            target = pos if card.feedback == "up" else neg
            target[item.id] = {**_row(item, card.feedback_at), "kind": "thumbs"}
        for item in session.exec(select(Item).where(Item.source == "raindrop")).all():
            pos.setdefault(item.id, {**_row(item, None), "kind": "bookmark"})
        labelled = set(pos) | set(neg)
        pool = session.exec(select(Item).where(or_(
            Item.origin == "cs.AI updates on arXiv.org", Item.feed_url.contains("arxiv.org/rss"),
        ))).all()
    candidates = sorted((i for i in pool if i.id not in labelled), key=lambda i: i.id)
    firehose = [_row(i, None) for i in random.Random(seed).sample(candidates, firehose_n)]
    keep = [r for r in pos.values() if r["title"].strip()]
    return {"positives": keep, "negatives": list(neg.values()), "firehose": firehose}


def split(rows: list[dict], seed: int) -> tuple[list[dict], list[dict]]:
    """A seeded two-way split."""
    shuffled = sorted(rows, key=lambda r: r["id"])
    random.Random(seed).shuffle(shuffled)
    half = len(shuffled) // 2
    return shuffled[:half], shuffled[half:]


def examples_from(pos: list[dict], neg: list[dict], max_each: int = 25) -> dict:
    """Example titles the way production derives them: newest first, cleaned, capped."""
    def titles(rows: list[dict]) -> list[str]:
        """Cleaned, de-duplicated titles, newest first."""
        out: list[str] = []
        for row in sorted(rows, key=lambda r: r["when"], reverse=True):
            text = clean_title(row["title"])
            if text and text not in out and len(out) < max_each:
                out.append(text)
        return out

    return {"liked": titles(pos), "disliked": titles(neg)}


def score_rows(judge: Judge, rows: list[dict], workers: int) -> dict[int, int | None]:
    """Triage scores per item id (None when the item could not be judged)."""
    chunks = [rows[i:i + _CHUNK] for i in range(0, len(rows), _CHUNK)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(lambda chunk: triage_rows(judge, chunk), chunks))
    scores: dict[int, int | None] = {r["id"]: None for r in rows}
    for outcome in outcomes:
        scores.update({i: r.score for i, r in outcome.results.items()})
    return scores


def stored_profile(engine) -> dict:
    """The reader's saved profile, or the default when none is saved (or no radar tables yet)."""
    try:
        with Session(engine) as session:
            return load_profile(session)
    except OperationalError:
        return DEFAULT_PROFILE


def evaluate(model: str, sets: dict, profile: dict, args, api_key: str,
             settings: Settings | None = None) -> dict:
    """Run the two-fold triage evaluation for one model; returns metrics and per-item scores."""
    stats = CallStats()
    started_all = time.perf_counter()
    USAGE.reset()
    keys = section_keys(profile)
    pos_a, pos_b = split(sets["positives"], args.seed)
    neg_a, neg_b = split(sets["negatives"], args.seed)
    plan = [(pos_b + neg_b, examples_from(pos_a, neg_a)),
            (pos_a + neg_a, examples_from(pos_b, neg_b)),
            (sets["firehose"], examples_from(pos_a, neg_a))]
    scores: dict[int, int | None] = {}
    with httpx.Client(timeout=120.0) as client:
        llm = (make_claude_llm(settings, stats) if args.provider == "claude_code"
               else make_llm(api_key, stats, client))
        for rows, examples in plan:
            judge = Judge(llm=llm, block=profile_prompt_block(profile, examples), keys=keys,
                          version=0, triage_model=model, digest_model=model, gate=args.gate)
            scores.update(score_rows(judge, rows, args.workers))

    if args.provider == "claude_code":
        used = USAGE.snapshot()  # cost is the list price the command reports, not a charge
        stats.cost, stats.prompt_tokens, stats.completion_tokens = (
            used["cost_usd"], used["input_tokens"] + used["cache_tokens"], used["output_tokens"])

    def share(rows: list[dict], kept: bool) -> float:
        """Share of rows at or over the gate (kept) or under it."""
        judged = [scores[r["id"]] for r in rows if scores.get(r["id"]) is not None]
        hits = sum(1 for s in judged if (s >= args.gate) == kept)
        return hits / len(judged) if judged else 0.0

    total = sum(len(v) for v in sets.values())
    return {
        "model": model,
        "recall_pos": share(sets["positives"], True),
        "recall_thumbs": share([r for r in sets["positives"] if r["kind"] == "thumbs"], True),
        "recall_bookmarks": share([r for r in sets["positives"] if r["kind"] == "bookmark"], True),
        "reject_neg": share(sets["negatives"], False),
        "firehose_kept": share(sets["firehose"], True),
        "unjudged": sum(1 for s in scores.values() if s is None),
        "cost_per_100": stats.cost / total * 100,
        "seconds_per_100": stats.seconds / total * 100,
        "cost_total": stats.cost, "calls": stats.calls,
        "wall_s": time.perf_counter() - started_all,
        "tokens": [stats.prompt_tokens, stats.completion_tokens],
        "scores": scores,
    }


def report(results: list[dict], sets: dict, gate: int) -> None:
    """Log the comparison table and, per model, the labelled items it got wrong."""
    logger.info("| model | positives recall (thumbs-up / bookmarks) | negatives rejection "
                "| firehose kept | unjudged | $ per 100 | s per 100 (sequential) |")
    logger.info("|---|---|---|---|---|---|---|")
    for r in results:
        logger.info("| %s | %.0f%% (%.0f%% / %.0f%%) | %.0f%% | %.0f%% | %d | $%.4f | %.1f |",
                    r["model"], r["recall_pos"] * 100, r["recall_thumbs"] * 100,
                    r["recall_bookmarks"] * 100, r["reject_neg"] * 100, r["firehose_kept"] * 100,
                    r["unjudged"], r["cost_per_100"], r["seconds_per_100"])
    titles = {row["id"]: row["title"][:90] for rows in sets.values() for row in rows}
    for r in results:
        logger.info("\n## %s misses (wall time %.0f s, %d calls)", r["model"],
                    r.get("wall_s", 0.0), r["calls"])
        for label, want in (("positives", True), ("negatives", False)):
            wrong = [(r["scores"].get(row["id"]), row["id"]) for row in sets[label]
                     if r["scores"].get(row["id"]) is not None
                     and (r["scores"][row["id"]] >= gate) != want]
            logger.info("%s wrong (%d):", label, len(wrong))
            for score, item_id in sorted(wrong, key=lambda w: w[0]):
                logger.info("  %3d  %s", score, titles[item_id])


def main() -> int:
    """Parse arguments, run every model, write the detail file and log the report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", required=True,
                        help="comma-separated model ids (OpenRouter ids, or Claude aliases)")
    parser.add_argument("--provider", choices=("openrouter", "claude_code"), default="openrouter",
                        help="claude_code runs the installed Claude Code command on its plan")
    parser.add_argument("--gate", type=int, default=None, help="default: radar_digest_gate")
    parser.add_argument("--firehose", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    args.gate = args.gate if args.gate is not None else settings.radar_digest_gate
    if args.provider == "openrouter" and not settings.openrouter_api_key:
        logger.error("No OpenRouter key configured")
        return 2
    engine = create_db_engine(settings.db_path)
    try:
        sets = load_sets(engine, firehose_n=args.firehose, seed=args.seed)
        profile = stored_profile(engine)
    finally:
        engine.dispose()
    logger.info("positives %d, negatives %d, firehose %d, gate %d", len(sets["positives"]),
                len(sets["negatives"]), len(sets["firehose"]), args.gate)
    results = [evaluate(m.strip(), sets, profile, args, settings.openrouter_api_key, settings)
               for m in args.models.split(",") if m.strip()]
    out_dir = settings.data_dir / "radar_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"gate": args.gate, "results": results}, indent=1), encoding="utf-8")
    report(results, sets, args.gate)
    logger.info("\ndetail: %s", Path(out).name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
