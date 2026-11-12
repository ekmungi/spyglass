"""Measure what the AI calls of Spyglass cost in tokens, through the service's own code paths.

Run from the repository root (it reads the same settings the service does: environment, `.env` and
the data folder's settings file). Real calls go through the installed `claude` command and use the
reader's plan, so keep the counts small. Sub-commands:

  overhead            one-word prompt through the chat launch and the bulk-judging launch
  chat                a conversation about one stored item (--resume-off sends each turn as a new
                      session; --wait-before-last waits that many seconds before the final turn)
  bulk                consecutive triage batches and digest calls built from real items
  dupes               how many recent items repeat one that was already judged
  report              the rows of the usage table
  control             triage batches launched the old way with memory off (separates two changes)

Example: uv run python scripts/usage_probe.py chat --item-id 123 --turns 4 --model haiku
Writes only what the normal code path writes (assistant threads, usage rows). Reads no secrets.
"""

import argparse
import json
import sys
import time
from datetime import timedelta

from sqlmodel import Session, select

from spyglass_service.config import Settings, apply_overlay
from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item
from spyglass_service.radar import assess, usage
from spyglass_service.radar.assess_prompt import (
    TEXT_CHARS,
    build_digest_messages,
    digest_schema,
    plain_title,
    triage_row,
)
from spyglass_service.radar.assist import threads
from spyglass_service.radar.models import Assessment, AssistThread, utcnow

QUESTIONS = [
    "What is the main argument of this text, in two sentences?",
    "Which organisations or people does it name?",
    "What does it say about how work or organisations will change?",
    "Quote one short passage that supports the main argument.",
    "In one sentence, what should a product manager take from this?",
]
COLUMNS = ("input", "cache_written", "cache_read", "output", "cost_usd")


def out(text: str = "") -> None:
    """Write one line to standard output."""
    sys.stdout.write(text + "\n")


def load_settings() -> Settings:
    """The settings in effect, with the Claude Code assistant engine switched on for the probe."""
    return apply_overlay(Settings()).model_copy(update={"assist_claude_code_enabled": True})


def row_line(label: str, row: dict) -> str:
    """One table line for a usage figure dict."""
    cells = [str(row.get(k, "")) for k in
             ("input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens")]
    cost = row.get("cost_usd")
    return f"| {label} | " + " | ".join(cells) + f" | {cost if cost is not None else ''} |"


def header() -> None:
    """The table header shared by every measurement."""
    out("| call | fresh input | cache written | cache read | output | cost (list price, USD) |")
    out("|---|---|---|---|---|---|")


def last_rows(engine, after_id: int, purpose: str | None = None) -> list[usage.UsageCall]:
    """Usage rows written after `after_id`."""
    with Session(engine) as session:
        query = select(usage.UsageCall).where(usage.UsageCall.id > after_id)
        if purpose:
            query = query.where(usage.UsageCall.purpose == purpose)
        return list(session.exec(query.order_by(usage.UsageCall.id)).all())


def max_usage_id(engine) -> int:
    """The newest usage row id, or 0."""
    usage.ensure_table(engine)
    with Session(engine) as session:
        row = session.exec(select(usage.UsageCall).order_by(usage.UsageCall.id.desc())).first()
        return row.id if row else 0


def as_dict(row: usage.UsageCall) -> dict:
    """A usage row as the figure dict `row_line` prints."""
    return {"input_tokens": row.input_tokens, "cache_write_tokens": row.cache_write_tokens,
            "cache_read_tokens": row.cache_read_tokens, "output_tokens": row.output_tokens,
            "cost_usd": None if row.cost_usd is None else round(row.cost_usd, 5)}


def cmd_overhead(args, settings, engine) -> None:
    """One-word prompt through the chat launch and through the bulk launch."""
    from spyglass_service.radar.assist.engines.claude_code import ClaudeCodeEngine
    from spyglass_service.radar.llm_claude import claude_chat_json

    header()
    chat = ClaudeCodeEngine(settings, enabled=True)
    for number in range(args.repeat):
        tokens = None
        for event in chat.stream(system="", messages=[{"role": "user", "content": "hi"}],
                                 model=args.model):
            if event.kind == "usage":
                tokens = event.data
        figures = {"input_tokens": tokens.input, "cache_write_tokens": tokens.cache_write,
                   "cache_read_tokens": tokens.cache_read, "output_tokens": tokens.output,
                   "cost_usd": tokens.cost_usd} if tokens else {}
        out(row_line(f"chat launch, one word, call {number + 1}", figures))
    schema = {"name": "w", "schema": {"type": "object", "properties": {"w": {"type": "string"}},
                                      "required": ["w"], "additionalProperties": False}}
    before = max_usage_id(engine)
    for number in range(args.repeat):
        with usage.call_scope(settings, "other"):
            claude_chat_json([{"role": "user", "content": "Reply with the word hi in key w."}],
                             schema, model=args.model, settings=settings)
        out(row_line(f"bulk launch, one word, call {number + 1}",
                     as_dict(last_rows(engine, before)[number])))


def cmd_chat(args, settings, engine) -> None:
    """A conversation about one item through `threads.run_turn`."""
    if args.condense_limit:
        from spyglass_service.radar.assist import condense

        condense.LIMIT_TOKENS = args.condense_limit  # only to see a condensing happen on a short run
    thread_id = threads.create_or_get_thread(engine, item_id=args.item_id, new=True)["id"]
    header()
    for number in range(args.turns + (1 if args.wait_before_last else 0)):
        if args.wait_before_last and number == args.turns:
            out(f"(waiting {args.wait_before_last} s)")
            time.sleep(args.wait_before_last)
        if args.resume_off and number:
            with Session(engine) as session:
                thread = session.get(AssistThread, thread_id)
                thread.external_session = None
                session.add(thread)
                session.commit()
        started = time.monotonic()
        events = list(threads.run_turn(engine, settings, thread_id, content=QUESTIONS[number % 5],
                                       engine_id=args.engine, model=args.model))
        done = events[-1]
        if done["type"] != "done":
            out(f"| turn {number + 1} | error: {done.get('message')} |")
            return
        label = (f"turn {number + 1}" + (" (new session)" if args.resume_off and number else "")
                 + (" (condensed)" if done.get("usage", {}).get("condensed") else ""))
        out(row_line(label, done.get("usage", {})) + f" {time.monotonic() - started:.1f} s |")


def pick_items(engine, limit: int, *, judged: bool | None) -> list[Item]:
    """Recent items with stored text; `judged` filters on whether an assessment exists."""
    from spyglass_service.content_store import get_fulltext

    found: list[Item] = []
    with Session(engine) as session:
        query = select(Item).order_by(Item.id.desc())
        for item in session.exec(query):
            has = session.exec(select(Assessment.id).where(Assessment.item_id == item.id)).first()
            if judged is not None and bool(has) != judged:
                continue
            found.append(item)
            if len(found) >= limit * 5:
                break
        for item in found:
            session.expunge(item)
    if judged is None:
        return found[:limit]
    return [i for i in found if (get_fulltext(engine, i.id) or {}).get("markdown")][:limit]


def cmd_bulk(args, settings, engine) -> None:
    """Consecutive triage batches and digest calls, through the judge and the real model seam."""
    from spyglass_service.content_store import get_fulltext

    judge = assess.make_judge(engine, settings)
    judge = judge.__class__(**{**judge.__dict__, "triage_model": args.model, "digest_model": args.model})
    header()
    rows = pick_items(engine, args.batch * args.calls, judged=False)
    before = max_usage_id(engine)
    for number in range(args.calls):
        batch = rows[number * args.batch:(number + 1) * args.batch]
        assess._triage_batch(judge, [triage_row(i.id, i.title, i.origin, i.source, i.summary)  # noqa: SLF001
                                     for i in batch])
        new = last_rows(engine, before, "triage")
        out(row_line(f"triage batch of {len(batch)}, call {number + 1}", as_dict(new[-1])))
        before = new[-1].id
    with_text = pick_items(engine, args.calls, judged=True)
    for number, item in enumerate(with_text):
        text = get_fulltext(engine, item.id)["markdown"][:TEXT_CHARS]
        meta = {"title": plain_title(item.title), "publication": item.origin or "",
                "source": item.source, "url": item.url}
        messages = build_digest_messages(judge.block, meta, text)
        assess._call(judge.llm, messages, digest_schema(judge.keys), judge.digest_model, "digest")  # noqa: SLF001
        new = last_rows(engine, before, "digest")
        out(row_line(f"digest, call {number + 1}", as_dict(new[-1])))
        before = new[-1].id


def cmd_control(args, settings, engine) -> None:
    """Control for `bulk`: triage batches launched the old way (instructions on standard input) but
    with memory switched off, to separate the two changes. Calls `claude` through the same runner."""
    from pathlib import Path

    from spyglass_service.claude_jobs import find_claude, parse_result
    from spyglass_service.radar import llm_claude
    from spyglass_service.radar.assess_prompt import build_triage_messages, triage_schema
    from spyglass_service.radar.privacy import prepare_bulk_messages
    from spyglass_service.radar.usage_parse import claude_tokens

    judge = assess.make_judge(engine, settings)
    rows = pick_items(engine, args.batch * args.calls, judged=False)
    schema = llm_claude.schema_body(triage_schema(judge.keys))
    header()
    for number in range(args.calls):
        batch = rows[number * args.batch:(number + 1) * args.batch]
        messages = prepare_bulk_messages(
            build_triage_messages(judge.block, [triage_row(i.id, i.title, i.origin, i.source, i.summary)
                                                for i in batch]), settings)
        command = llm_claude.build_command(find_claude(settings), args.model, schema)
        cwd = Path(settings.data_dir) / "llm_cwd"
        run = llm_claude.default_runner(command, llm_claude.render_prompt(messages, None), cwd, 240.0)
        tokens = claude_tokens(parse_result(run.stdout))
        out(row_line(f"old launch, memory off, triage batch call {number + 1}",
                     {"input_tokens": tokens.input, "cache_write_tokens": tokens.cache_write,
                      "cache_read_tokens": tokens.cache_read, "output_tokens": tokens.output,
                      "cost_usd": tokens.cost_usd}))


def cmd_batches(args, settings, engine) -> None:
    """Triage the same real, unjudged items in batches of 20 and of 40 (and optionally at low
    effort) and compare tokens per item and agreement of the resulting tiers."""
    import os

    from spyglass_service.radar.assess_prompt import tier_for

    judge = assess.make_judge(engine, settings)
    judge = judge.__class__(**{**judge.__dict__, "triage_model": args.model})
    rows = [triage_row(i.id, i.title, i.origin, i.source, i.summary)
            for i in pick_items(engine, args.items, judged=False)]

    def run(label: str, size: int, limit: int, effort: str | None) -> dict[int, int]:
        """Triage the first `limit` rows in batches of `size`; print the totals; return id -> score."""
        before = max_usage_id(engine)
        if effort:
            os.environ["CLAUDE_CODE_EFFORT_LEVEL"] = effort
        else:
            os.environ.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
        scores: dict[int, int] = {}
        for start in range(0, limit, size):
            got, _bad = assess._triage_batch(judge, rows[start:start + size])  # noqa: SLF001
            scores.update({i: r.score for i, r in got.items()})
        used = last_rows(engine, before, "triage")
        total = lambda f: sum(getattr(r, f) or 0 for r in used)  # noqa: E731
        context = total("input_tokens") + total("cache_write_tokens") + total("cache_read_tokens")
        out(f"| {label} | {len(used)} | {len(scores)} | {context / max(1, len(scores)):.0f} | "
            f"{total('cache_read_tokens') / max(1, len(scores)):.0f} | {total('output_tokens') / max(1, len(scores)):.0f} | "
            f"{sum(r.cost_usd or 0 for r in used) / max(1, len(scores)):.5f} |")
        return scores

    out("| config | calls | items judged | prompt tokens per item | of which cache read | output tokens per item | cost per item (list USD) |")
    out("|---|---|---|---|---|---|---|")
    base = run("20 per call, default effort", 20, args.items, None)
    wide = run("40 per call, default effort", 40, args.items, None)
    low = run("20 per call, effort low (first 40 items)", 20, 40, "low") if args.effort_low else {}
    os.environ.pop("CLAUDE_CODE_EFFORT_LEVEL", None)

    def compare(name: str, other: dict[int, int]) -> None:
        """Print tier agreement and score difference between the baseline and `other`."""
        common = [i for i in base if i in other]
        same = sum(tier_for(base[i]) == tier_for(other[i]) for i in common)
        gate = sum((base[i] >= 50) == (other[i] >= 50) for i in common)
        diff = sum(abs(base[i] - other[i]) for i in common) / max(1, len(common))
        out(f"{name}: {len(common)} items in common, same tier {same}/{len(common)}, same side of the gate (50) {gate}/{len(common)}, mean score difference {diff:.1f}")

    compare("40 per call vs 20 per call", wide)
    if low:
        compare("effort low vs default (20 per call)", low)


def cmd_dupes(args, settings, engine) -> None:
    """Recent items that repeat an already judged item (same address, or near-identical title)."""
    import numpy as np
    from sqlalchemy import text

    from spyglass_service.radar.brief.addresses import normalize_address

    cutoff = utcnow() - timedelta(days=args.days)
    with Session(engine) as session:
        recent = session.exec(select(Item).where(Item.fetched_at >= cutoff)).all()
        judged = {r[0]: r[1] for r in session.exec(
            text("select a.item_id, a.assessed_at from assessment a")).all()}
        by_address: dict[str, list[tuple[int, object]]] = {}
        for item in session.exec(select(Item).where(Item.id.in_(list(judged)))).all():
            by_address.setdefault(normalize_address(item.url), []).append((item.id, item.fetched_at))
        vectors = {r[0]: np.frombuffer(r[1], dtype=np.float32) for r in session.exec(
            text("select item_id, vector from embedding")).all()}
    exact = near = judged_twice = 0
    for item in recent:
        earlier = [i for i, fetched in by_address.get(normalize_address(item.url), [])
                   if i != item.id and fetched <= item.fetched_at]
        if earlier:
            exact += 1
            judged_twice += item.id in judged
            continue
        mine = vectors.get(item.id)
        if mine is None or item.id not in judged:
            continue
        for other_id in judged:
            if other_id == item.id or other_id not in vectors:
                continue
            if float(mine @ vectors[other_id]) >= 0.95 and other_id < item.id:
                near += 1
                break
    out(json.dumps({"collected_in_window": len(recent), "exact_address_repeat": exact,
                    "of_which_judged_twice": judged_twice, "near_duplicate_by_vector": near}))


def cmd_report(args, settings, engine) -> None:
    """Print the usage rows newer than a row id."""
    header()
    for row in last_rows(engine, args.after):
        out(row_line(f"{row.purpose}/{row.provider}/{row.model}", as_dict(row)))


def main() -> None:
    """Parse the command line and run one sub-command."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("overhead", cmd_overhead), ("chat", cmd_chat), ("bulk", cmd_bulk),
                     ("dupes", cmd_dupes), ("report", cmd_report), ("control", cmd_control), ("batches", cmd_batches)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--model", default="haiku")
        p.add_argument("--engine", default="claude_code")
        p.add_argument("--repeat", type=int, default=2)
        p.add_argument("--item-id", type=int)
        p.add_argument("--turns", type=int, default=4)
        p.add_argument("--resume-off", action="store_true")
        p.add_argument("--wait-before-last", type=int, default=0)
        p.add_argument("--batch", type=int, default=20)
        p.add_argument("--calls", type=int, default=3)
        p.add_argument("--days", type=int, default=7)
        p.add_argument("--after", type=int, default=0)
        p.add_argument("--items", type=int, default=80)
        p.add_argument("--condense-limit", type=int, default=0)
        p.add_argument("--effort-low", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    engine = create_db_engine(settings.db_path)
    try:
        init_db(engine)
        args.fn(args, settings, engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
